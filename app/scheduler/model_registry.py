"""
Public Model Registry Cache

Fetches authoritative context/token limits for known models from:
  1. LiteLLM model_prices_and_context_window.json  (thousands of models, HuggingFace IDs)
  2. OpenRouter /api/v1/models                      (OR-hosted models, live)

Cache stored at: ~/.memory/config/model_registry_cache.json
TTL: configurable, default 24 h

Lookup precedence (called by resource_pool):
  user llm_config "model_registry" override  →  this cache  →  None (unknown)

Key normalisation:
  Model IDs from LMStudio /v1/models use HuggingFace-style "Publisher/Model-Name".
  LiteLLM keys are lowercase and may include a provider prefix.
  We index both the raw key and a normalised lowercase version, and try several
  prefix variants (bare, "openrouter/", "huggingface/") to maximise hit rate.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timezone

import requests

from app.config.paths import get_memory_subpath

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public sources
# ---------------------------------------------------------------------------
LITELLM_REGISTRY_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

FETCH_TIMEOUT_S = 15
DEFAULT_TTL_HOURS = 24

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    context_limit: Optional[int] = None   # total context window
    input_limit: Optional[int] = None     # per-request input cap (None = same as context)
    output_limit: Optional[int] = None    # max output tokens
    source: str = ""                      # "litellm" | "openrouter" | "user"


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise(model_id: str) -> str:
    """Lowercase, strip whitespace."""
    return model_id.strip().lower()


def _candidate_keys(model_id: str):
    """
    Yield lookup keys to try for a given model_id, most-specific first.

    e.g. "Qwen/Qwen3-8B-Instruct" yields:
        "qwen/qwen3-8b-instruct"
        "openrouter/qwen/qwen3-8b-instruct"
        "qwen3-8b-instruct"           (name after last /)
    """
    norm = _normalise(model_id)
    yield norm
    if not norm.startswith("openrouter/"):
        yield f"openrouter/{norm}"
    # Just the model name (after last /)
    name_only = norm.rsplit("/", 1)[-1]
    if name_only != norm:
        yield name_only


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def _fetch_litellm() -> Dict[str, ModelSpec]:
    """Download LiteLLM registry and extract context/token limits."""
    try:
        resp = requests.get(LITELLM_REGISTRY_URL, timeout=FETCH_TIMEOUT_S)
        resp.raise_for_status()
        data: dict = resp.json()
    except Exception as exc:
        logger.warning("model_registry: LiteLLM fetch failed: %s", exc)
        return {}

    result: Dict[str, ModelSpec] = {}
    for raw_key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        context = entry.get("context_window") or entry.get("max_tokens")
        output  = entry.get("max_output_tokens") or entry.get("max_tokens")
        # LiteLLM uses max_input_tokens when input ≠ context (asymmetric APIs)
        inp     = entry.get("max_input_tokens")

        if not context:
            continue

        spec = ModelSpec(
            context_limit=int(context),
            output_limit=int(output) if output else None,
            input_limit=int(inp) if inp and int(inp) < int(context) else None,
            source="litellm",
        )
        norm = _normalise(raw_key)
        result[norm] = spec

    logger.info("model_registry: LiteLLM loaded %d entries", len(result))
    return result


def _fetch_openrouter() -> Dict[str, ModelSpec]:
    """Download OpenRouter model list and extract context/token limits."""
    try:
        resp = requests.get(OPENROUTER_MODELS_URL, timeout=FETCH_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("model_registry: OpenRouter fetch failed: %s", exc)
        return {}

    result: Dict[str, ModelSpec] = {}
    for entry in data.get("data", []):
        model_id = entry.get("id", "")
        if not model_id:
            continue

        context = entry.get("context_length")
        top = entry.get("top_provider", {}) or {}
        output = top.get("max_completion_tokens") or entry.get("context_length")

        if not context:
            continue

        spec = ModelSpec(
            context_limit=int(context),
            output_limit=int(output) if output else None,
            input_limit=None,
            source="openrouter",
        )
        norm = _normalise(model_id)
        result[norm] = spec

    logger.info("model_registry: OpenRouter loaded %d entries", len(result))
    return result


# ---------------------------------------------------------------------------
# Cache manager
# ---------------------------------------------------------------------------

class ModelRegistryCache:
    """
    Merged model spec cache backed by LiteLLM + OpenRouter.

    Thread-safe for read (lookup). Refresh is synchronous and should be called
    from a background thread or at startup.
    """

    CACHE_FILE = Path(get_memory_subpath("config/model_registry_cache.json"))

    def __init__(self, ttl_hours: int = DEFAULT_TTL_HOURS):
        self._ttl_hours = ttl_hours
        self._index: Dict[str, ModelSpec] = {}
        self._loaded_at: float = 0.0
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(self, model_id: str) -> Optional[ModelSpec]:
        """
        Return ModelSpec for the given model_id, or None if unknown.

        Tries several normalised key variants (see _candidate_keys).
        Does NOT auto-refresh — call get_or_refresh() first if you want
        freshness guarantees.
        """
        for key in _candidate_keys(model_id):
            spec = self._index.get(key)
            if spec:
                return spec
        return None

    def get_or_refresh(self) -> "ModelRegistryCache":
        """Refresh if cache is stale or empty, then return self."""
        age_h = (time.time() - self._loaded_at) / 3600
        if not self._index or age_h >= self._ttl_hours:
            self.refresh()
        return self

    def refresh(self) -> int:
        """
        Fetch from all sources, merge (OpenRouter wins on conflicts),
        persist to disk. Returns number of entries loaded.
        """
        logger.info("model_registry: refreshing from public sources…")
        litellm = _fetch_litellm()
        openrouter = _fetch_openrouter()

        # Merge: LiteLLM base, OpenRouter overrides (more precise for OR models)
        merged = {**litellm, **openrouter}
        self._index = merged
        self._loaded_at = time.time()
        self._save_to_disk()
        logger.info("model_registry: cache now has %d entries", len(merged))
        return len(merged)

    def size(self) -> int:
        return len(self._index)

    def updated_at_iso(self) -> str:
        if not self._loaded_at:
            return "never"
        return datetime.fromtimestamp(self._loaded_at, tz=timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_to_disk(self) -> None:
        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": self.updated_at_iso(),
            "ttl_hours": self._ttl_hours,
            "models": {k: asdict(v) for k, v in self._index.items()},
        }
        try:
            self.CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("model_registry: could not save cache: %s", exc)

    def _load_from_disk(self) -> None:
        if not self.CACHE_FILE.exists():
            return
        try:
            payload = json.loads(self.CACHE_FILE.read_text(encoding="utf-8"))
            raw_models: dict = payload.get("models", {})
            self._index = {
                k: ModelSpec(**v) for k, v in raw_models.items()
            }
            # Parse ISO timestamp back to epoch
            updated = payload.get("updated_at", "")
            if updated and updated != "never":
                self._loaded_at = datetime.fromisoformat(updated).timestamp()
            logger.debug(
                "model_registry: loaded %d entries from disk (updated %s)",
                len(self._index), updated,
            )
        except Exception as exc:
            logger.warning("model_registry: cache load failed: %s", exc)
            self._index = {}
            self._loaded_at = 0.0


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_registry: Optional[ModelRegistryCache] = None


def get_registry(ttl_hours: int = DEFAULT_TTL_HOURS) -> ModelRegistryCache:
    """Return the shared ModelRegistryCache singleton."""
    global _registry
    if _registry is None:
        _registry = ModelRegistryCache(ttl_hours=ttl_hours)
    return _registry


def lookup_model(model_id: str) -> Optional[ModelSpec]:
    """
    Convenience wrapper: look up a model in the shared registry.

    Does NOT trigger a network refresh — call get_registry().get_or_refresh()
    at startup if you need freshness guarantees.
    """
    return get_registry().lookup(model_id)

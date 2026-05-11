"""Provider contracts for Memory and Dream modules.

These ABCs define the stable interface that any memory/dream provider must implement.
The app core depends ONLY on these contracts — never on concrete implementations.

Versioning:
- contract_version: SemVer for the contract itself (major.minor)
- provider_version: Provider's own version string
- provider_name: Unique identifier for the provider

The app rejects providers with incompatible contract versions at startup.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Version contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderVersion:
    """Immutable version metadata for a provider."""
    provider_name: str           # e.g. "mojo_memory", "mojo_dream"
    provider_version: str        # e.g. "1.0.0"
    contract_version: str        # e.g. "1.0" — major.minor only


# ---------------------------------------------------------------------------
# Memory Provider Contract
# ---------------------------------------------------------------------------

class MemoryProvider(ABC):
    """
    Abstract base class for memory providers.

    A memory provider manages conversation memory, knowledge units,
    and structured archival. Any pluggable memory backend must implement
    this interface.
    """

    @abstractmethod
    def get_version(self) -> ProviderVersion:
        """Return provider version metadata."""
        ...

    # -- Conversation CRUD --------------------------------------------------

    @abstractmethod
    def add_conversation(
        self,
        role_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a conversation entry to memory.
        Returns: conversation_id
        """
        ...

    @abstractmethod
    def get_conversation(
        self,
        role_id: str,
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a conversation entry by ID."""
        ...

    @abstractmethod
    def search_conversations(
        self,
        role_id: str,
        query: str,
        max_items: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search conversation memory by semantic similarity.
        Returns: list of {id, content, score, metadata}
        """
        ...

    # -- Knowledge Units ----------------------------------------------------

    @abstractmethod
    def add_knowledge(
        self,
        role_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a knowledge unit to the knowledge base.
        Returns: knowledge_unit_id
        """
        ...

    @abstractmethod
    def search_knowledge(
        self,
        role_id: str,
        query: str,
        max_items: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search knowledge units by semantic similarity.
        Returns: list of {id, content, score, metadata}
        """
        ...

    @abstractmethod
    def archive_knowledge(
        self,
        role_id: str,
        knowledge_units: List[Dict[str, Any]],
    ) -> str:
        """
        Archive knowledge units to long-term storage.
        Returns: archive_id
        """
        ...

    # -- Health / Capabilities ----------------------------------------------

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Return provider health status.
        Must include: {"status": "ok"|"degraded"|"error", "details": {...}}
        """
        ...

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return provider capabilities metadata.
        Override to report specific capabilities (e.g. supported backends).
        """
        return {
            "provider_name": self.get_version().provider_name,
            "supports_embeddings": True,
            "supports_archive": True,
            "supports_conversation_search": True,
        }


# ---------------------------------------------------------------------------
# Retrieval Strategy Contract
# ---------------------------------------------------------------------------

@dataclass
class ScoredResult:
    """A single retrieval result with a relevance score."""
    content: str
    score: float                        # 0.0–1.0
    source: str                         # "conversation", "knowledge_base", etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


class RetrievalStrategy(ABC):
    """
    Abstract base class for retrieval strategies.

    A retrieval strategy takes a query embedding and a set of candidate
    documents (each carrying their own embeddings) and returns ranked results.
    Swapping strategies requires no changes to the memory provider.

    Strategies are selected via the config key ``retrieval.strategy``.
    """

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        candidates: List[Dict[str, Any]],
        *,
        max_results: int = 10,
        threshold: float = 0.3,
    ) -> List[ScoredResult]:
        """
        Rank candidates against the query embedding.

        ``candidates`` is a list of dicts, each with at least:
          - ``"text_content"`` (str): the raw text
          - ``"embeddings"`` (Dict[str, List[float]]): model_key -> vector
          - ``"source"`` (str): provenance tag
          - ``"metadata"`` (dict, optional)

        Returns results sorted by score descending, limited to max_results.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. "semantic" or "hybrid"."""
        ...


# ---------------------------------------------------------------------------
# Dream Provider Contract
# ---------------------------------------------------------------------------

@dataclass
class DreamArtifact:
    """Normalized output from a dream pipeline stage."""
    stage: str                  # "A", "B", "C", or "D"
    artifact_type: str          # "chunk", "cluster", "knowledge_unit", "archive"
    content: str                # The artifact content
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DreamStageResult:
    """Result from a single dream pipeline stage."""
    stage: str
    status: str                 # "ok", "error", "skipped"
    artifacts: List[DreamArtifact] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class DreamProvider(ABC):
    """
    Abstract base class for dream providers.

    A dream provider runs the ABCD memory consolidation pipeline.
    Any pluggable dream backend must implement this interface.
    """

    @abstractmethod
    def get_version(self) -> ProviderVersion:
        """Return provider version metadata."""
        ...

    # -- Pipeline stages ----------------------------------------------------

    @abstractmethod
    def run_stage_a(
        self,
        conversation_text: str,
        session_id: str,
    ) -> DreamStageResult:
        """
        Stage A: Authentic Data ingestion.
        Input: raw conversation text
        Output: validated conversation data
        """
        ...

    @abstractmethod
    def run_stage_b(
        self,
        stage_a_result: DreamStageResult,
        session_id: str,
    ) -> DreamStageResult:
        """
        Stage B: Basic Units (semantic chunking).
        Input: Stage A result
        Output: List of BChunks
        """
        ...

    @abstractmethod
    def run_stage_c(
        self,
        stage_b_result: DreamStageResult,
        session_id: str,
    ) -> DreamStageResult:
        """
        Stage C: Cluster Map (synthesis).
        Input: Stage B result
        Output: List of CClusters
        """
        ...

    @abstractmethod
    def run_stage_d(
        self,
        stage_c_result: DreamStageResult,
        stage_b_result: Optional[DreamStageResult] = None,
        session_id: str = "",
    ) -> DreamStageResult:
        """
        Stage D: Dynamic Relationship (archival).
        Input: Stage B + C results
        Output: DArchive with versioned storage
        """
        ...

    # -- Full pipeline ------------------------------------------------------

    @abstractmethod
    def run_pipeline(
        self,
        conversation_text: str,
        session_id: str,
        stages: Optional[List[str]] = None,
    ) -> Dict[str, DreamStageResult]:
        """
        Run the full ABCD pipeline (or selected stages).
        Returns: {stage_id: DreamStageResult}
        """
        ...

    # -- Validation / Dry-run -----------------------------------------------

    @abstractmethod
    def validate_input(
        self,
        conversation_text: str,
    ) -> Dict[str, Any]:
        """
        Validate input without running the pipeline.
        Returns: {"valid": bool, "errors": [...], "warnings": [...]}
        """
        ...

    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return provider capabilities metadata.
        Override to report specific capabilities.
        """
        return {
            "provider_name": self.get_version().provider_name,
            "stages": ["A", "B", "C", "D"],
            "supports_dry_run": True,
            "supports_partial_stages": True,
        }


# ---------------------------------------------------------------------------
# Persona Provider Contract
# ---------------------------------------------------------------------------

@dataclass
class PersonaSpec:
    """Input spec for generating a role/persona definition."""
    name: str
    purpose: str
    capabilities: List[str] = field(default_factory=lambda: ["memory"])
    persona_file: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PersonaSummary:
    """Compact listing item for persona catalogs."""
    id: str
    name: str
    category: str = "general"
    description: str = ""
    source: str = ""


@dataclass
class PersonaScore:
    """NineChapter-like personality scoring output."""
    total_score: int
    dimensions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    confidence: float = 0.75


class PersonaProvider(ABC):
    """Provider contract for persona generation/scoring/catalog."""

    @abstractmethod
    def get_version(self) -> ProviderVersion:
        ...

    @abstractmethod
    def generate(self, spec: PersonaSpec) -> Dict[str, Any]:
        """Generate a role definition from persona spec."""
        ...

    @abstractmethod
    def score(self, role_def: Dict[str, Any]) -> PersonaScore:
        """Score role definition against persona dimensions."""
        ...

    @abstractmethod
    def list_personas(self, filter: Optional[Dict[str, Any]] = None) -> List[PersonaSummary]:
        """List available personas from provider catalog."""
        ...

    def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "details": {"provider": self.get_version().provider_name}}


# ---------------------------------------------------------------------------
# Growth Provider Contract (skeleton for conformance expansion)
# ---------------------------------------------------------------------------

@dataclass
class GrowthSnapshot:
    role_id: str
    timestamp: str
    dimensions: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class GrowthProvider(ABC):
    @abstractmethod
    def get_version(self) -> ProviderVersion:
        ...

    @abstractmethod
    def snapshot(self, role_id: str, context: Optional[Dict[str, Any]] = None) -> GrowthSnapshot:
        ...

    @abstractmethod
    def evaluate(self, role_id: str, signals: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def propose(self, role_id: str, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def validate(self, role_id: str, proposal: Dict[str, Any], decision: str) -> Dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Skill Provider Contract (skeleton for conformance expansion)
# ---------------------------------------------------------------------------

class SkillProvider(ABC):
    @abstractmethod
    def get_version(self) -> ProviderVersion:
        ...

    @abstractmethod
    def catalog(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def blueprint(self, skill_id: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def install(self, skill_id: str, env: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def test(self, skill_id: str) -> Dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Provider Registry
# ---------------------------------------------------------------------------

class ProviderRegistry:
    """
    Central registry for memory and dream providers.

    Providers are registered by name and resolved via:
    1. Environment variables (MOJO_MEMORY_PROVIDER, MOJO_DREAM_PROVIDER)
    2. Explicit registration
    3. Default providers (mojo_memory, mojo_dream)
    4. Module discovery from submodules/*/module.json
    """

    def __init__(self) -> None:
        self._memory_providers: Dict[str, type] = {}
        self._dream_providers: Dict[str, type] = {}
        self._persona_providers: Dict[str, type] = {}
        self._instances: Dict[str, Any] = {}
        self._modules: Dict[str, Dict[str, Any]] = {}  # name -> module.json data
        self._health_status: Dict[str, Dict[str, Any]] = {}  # name -> health result
        self._module_load_errors: Dict[str, str] = {}  # name -> import/registration error

    # -- Registration -------------------------------------------------------

    def register_memory_provider(self, name: str, provider_class: type) -> None:
        """Register a memory provider class by name."""
        if not issubclass(provider_class, MemoryProvider):
            raise TypeError(f"{provider_class} must be a subclass of MemoryProvider")
        self._memory_providers[name] = provider_class
        logger.info("provider_registry: registered memory provider '%s'", name)

    def register_dream_provider(self, name: str, provider_class: type) -> None:
        """Register a dream provider class by name."""
        if not issubclass(provider_class, DreamProvider):
            raise TypeError(f"{provider_class} must be a subclass of DreamProvider")
        self._dream_providers[name] = provider_class
        logger.info("provider_registry: registered dream provider '%s'", name)

    def register_persona_provider(self, name: str, provider_class: type) -> None:
        """Register a persona provider class by name."""
        if not issubclass(provider_class, PersonaProvider):
            raise TypeError(f"{provider_class} must be a subclass of PersonaProvider")
        self._persona_providers[name] = provider_class
        logger.info("provider_registry: registered persona provider '%s'", name)

    # -- Module discovery ---------------------------------------------------

    def discover_modules(self, submodule_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scan submodules/*/module.json and register discovered providers.
        
        Also scans for module.*.json to support multiple modules per submodule.
        Returns list of discovered module descriptors.
        """
        import importlib

        if submodule_dir is None:
            submodule_dir = str(Path(__file__).resolve().parents[2] / "submodules")
        
        submodule_path = Path(submodule_dir)
        if not submodule_path.exists():
            logger.warning("provider_registry: submodule dir not found: %s", submodule_dir)
            return []

        strict = os.environ.get("MOJO_STRICT_MODULE_LOADING", "").lower() in ("1", "true", "yes")

        discovered = []
        # Scan for module.json and module.*.json patterns
        for module_json in submodule_path.glob("*/module*.json"):
            try:
                with open(module_json) as f:
                    raw = json.load(f)

                # Support both single-module {"name": ...} and
                # multi-module {"modules": [...]} formats.
                entries = raw.get("modules") if isinstance(raw.get("modules"), list) else [raw]

                # Ensure "<submodule>/src" is importable before loading any entry points.
                src_dir = module_json.parent / "src"
                if src_dir.exists():
                    src_str = str(src_dir)
                    if src_str not in sys.path:
                        sys.path.insert(0, src_str)

                for module_data in entries:
                    name = module_data.get("name")
                    if not name:
                        logger.warning("provider_registry: module entry missing 'name': %s", module_json)
                        continue

                    self._modules[name] = module_data
                    discovered.append(module_data)
                    self._module_load_errors.pop(name, None)

                    # Auto-register if entry_point is valid
                    entry_point = module_data.get("entry_point")
                    provider_type = module_data.get("provider_type")

                    if entry_point and provider_type:
                        try:
                            module_path, class_name = entry_point.rsplit(".", 1)
                            mod = importlib.import_module(module_path)
                            cls = getattr(mod, class_name)

                            if provider_type == "memory":
                                self.register_memory_provider(name, cls)
                            elif provider_type == "dream":
                                self.register_dream_provider(name, cls)
                            elif provider_type == "persona":
                                self.register_persona_provider(name, cls)
                        except Exception as e:
                            self._module_load_errors[name] = str(e)
                            logger.warning(
                                "provider_registry: failed to load provider '%s' from %s: %s",
                                name, entry_point, e
                            )

                logger.info("provider_registry: discovered module '%s' v%s", name, module_data.get("version"))

            except Exception as e:
                logger.warning("provider_registry: failed to parse %s: %s", module_json, e)

        if strict and self._module_load_errors:
            names = ", ".join(self._module_load_errors)
            raise RuntimeError(
                f"MOJO_STRICT_MODULE_LOADING: module load errors for: {names}. "
                f"Errors: {self._module_load_errors}"
            )

        return discovered

    def get_module_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get module descriptor by name."""
        module = self._modules.get(name)
        if not module:
            return None
        info = dict(module)
        if name in self._module_load_errors:
            info["load_error"] = self._module_load_errors[name]
        return info

    def list_modules(self) -> List[Dict[str, Any]]:
        """List all discovered modules."""
        out: List[Dict[str, Any]] = []
        for name, module in self._modules.items():
            info = dict(module)
            if name in self._module_load_errors:
                info["load_error"] = self._module_load_errors[name]
            out.append(info)
        return out

    # -- Health checks ------------------------------------------------------

    def run_health_checks(self) -> Dict[str, Dict[str, Any]]:
        """
        Run health checks on all registered providers.
        Returns dict of provider_name -> health result.
        """
        results = {}

        # Check memory providers
        for name, cls in self._memory_providers.items():
            try:
                # Try to instantiate and run health check
                cache_key = f"memory:{name}"
                if cache_key in self._instances:
                    instance = self._instances[cache_key]
                else:
                    # Can't instantiate without args, skip
                    results[name] = {"status": "skipped", "reason": "not instantiated"}
                    continue
                
                if hasattr(instance, 'health_check'):
                    health = instance.health_check()
                    results[name] = health
                else:
                    results[name] = {"status": "ok", "reason": "no health_check method"}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

        # Check dream providers
        for name, cls in self._dream_providers.items():
            try:
                cache_key = f"dream:{name}"
                if cache_key in self._instances:
                    instance = self._instances[cache_key]
                else:
                    results[name] = {"status": "skipped", "reason": "not instantiated"}
                    continue
                
                if hasattr(instance, 'health_check'):
                    health = instance.health_check()
                    results[name] = health
                else:
                    results[name] = {"status": "ok", "reason": "no health_check method"}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

        # Check persona providers
        for name, cls in self._persona_providers.items():
            try:
                cache_key = f"persona:{name}"
                if cache_key in self._instances:
                    instance = self._instances[cache_key]
                else:
                    results[name] = {"status": "skipped", "reason": "not instantiated"}
                    continue

                if hasattr(instance, "health_check"):
                    health = instance.health_check()
                    results[name] = health
                else:
                    results[name] = {"status": "ok", "reason": "no health_check method"}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

        self._health_status = results
        return results

    # -- Version compatibility ----------------------------------------------

    def check_version_compatibility(self, core_contract_version: str = "1.0") -> List[str]:
        """
        Check that all discovered modules have compatible contract versions.
        Returns list of warning messages.
        """
        warnings = []
        
        for name, module_data in self._modules.items():
            module_contract = module_data.get("contract_version")
            if not module_contract:
                warnings.append(f"Module '{name}' does not declare contract_version")
                continue
            
            # Check major version matches
            core_major = core_contract_version.split(".")[0]
            module_major = module_contract.split(".")[0]
            
            if core_major != module_major:
                warnings.append(
                    f"Module '{name}' contract version {module_contract} "
                    f"is incompatible with core version {core_contract_version}"
                )
            elif module_contract != core_contract_version:
                warnings.append(
                    f"Module '{name}' contract version {module_contract} "
                    f"differs from core {core_contract_version} (minor mismatch)"
                )
        
        return warnings

    def get_module_load_errors(self) -> Dict[str, str]:
        """Return module load/import errors discovered during module scan."""
        return dict(self._module_load_errors)

    # -- Schema validation --------------------------------------------------

    def _load_descriptor_schema(self) -> Optional[Dict[str, Any]]:
        """Load docs/schemas/module.json for descriptor validation."""
        schema_path = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "module.json"
        if not schema_path.exists():
            return None
        try:
            with open(schema_path) as f:
                return json.load(f)
        except Exception:
            return None

    def validate_descriptor(self, module_data: Dict[str, Any]) -> List[str]:
        """
        Validate a single module descriptor against docs/schemas/module.json.
        Returns list of error strings (empty = valid).
        """
        schema = self._load_descriptor_schema()
        if schema is None:
            return []  # schema not available, skip validation
        try:
            import jsonschema
            jsonschema.validate(module_data, schema)
            return []
        except ImportError:
            return []  # jsonschema not installed
        except Exception as e:
            return [str(e)]

    def validate_all_descriptors(self) -> Dict[str, List[str]]:
        """
        Validate all discovered module descriptors.
        Returns dict of module_name -> list of validation errors.
        """
        results: Dict[str, List[str]] = {}
        for name, module_data in self._modules.items():
            errors = self.validate_descriptor(module_data)
            if errors:
                results[name] = errors
        return results

    # -- Dependency graph ---------------------------------------------------

    def check_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Check that all declared dependencies of each module are registered.
        Returns dict of module_name -> list of missing dependency names.
        """
        registered = set(self._modules.keys())
        missing: Dict[str, List[str]] = {}
        for name, module_data in self._modules.items():
            deps = module_data.get("dependencies") or []
            absent = [d for d in deps if d not in registered]
            if absent:
                missing[name] = absent
        return missing

    # -- Resolution ---------------------------------------------------------

    def resolve_memory_provider(
        self,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> MemoryProvider:
        """
        Resolve and instantiate a memory provider.
        
        Resolution order:
        1. Explicit name parameter
        2. MOJO_MEMORY_PROVIDER env var
        3. Default ("mojo_memory")
        """
        if name is None:
            name = os.getenv("MOJO_MEMORY_PROVIDER", "mojo_memory")

        if name not in self._memory_providers:
            # Try to auto-register default
            self._register_default_memory_provider(name)

        if name not in self._memory_providers:
            available = list(self._memory_providers.keys())
            raise ValueError(
                f"Memory provider '{name}' not registered. "
                f"Available: {available}"
            )

        cache_key = f"memory:{name}"
        if cache_key not in self._instances:
            self._instances[cache_key] = self._memory_providers[name](**kwargs)
        return self._instances[cache_key]

    def resolve_dream_provider(
        self,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> DreamProvider:
        """
        Resolve and instantiate a dream provider.
        
        Resolution order:
        1. Explicit name parameter
        2. MOJO_DREAM_PROVIDER env var
        3. Default ("mojo_dream")
        """
        if name is None:
            name = os.getenv("MOJO_DREAM_PROVIDER", "mojo_dream")

        if name not in self._dream_providers:
            self._register_default_dream_provider(name)

        if name not in self._dream_providers:
            available = list(self._dream_providers.keys())
            raise ValueError(
                f"Dream provider '{name}' not registered. "
                f"Available: {available}"
            )

        cache_key = f"dream:{name}"
        if cache_key not in self._instances:
            self._instances[cache_key] = self._dream_providers[name](**kwargs)
        return self._instances[cache_key]

    def resolve_persona_provider(
        self,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> PersonaProvider:
        """
        Resolve and instantiate a persona provider.
        Resolution order:
        1. Explicit name parameter
        2. MOJO_PERSONA_PROVIDER env var
        3. Default ("agency_persona")
        """
        if name is None:
            name = os.getenv("MOJO_PERSONA_PROVIDER", "agency_persona")

        if name not in self._persona_providers:
            self._register_default_persona_provider(name)

        if name not in self._persona_providers:
            available = list(self._persona_providers.keys())
            raise ValueError(
                f"Persona provider '{name}' not registered. "
                f"Available: {available}"
            )

        cache_key = f"persona:{name}"
        if cache_key not in self._instances:
            self._instances[cache_key] = self._persona_providers[name](**kwargs)
        return self._instances[cache_key]

    # -- Startup validation -------------------------------------------------

    def validate_compatibility(self) -> List[str]:
        """
        Validate that all registered providers are compatible.
        Returns list of error messages (empty = all ok).
        """
        errors = []
        
        # Check version compatibility
        warnings = self.check_version_compatibility()
        errors.extend(warnings)
        
        # Check health of instantiated providers
        health = self.run_health_checks()
        for name, result in health.items():
            if result.get("status") == "error":
                errors.append(f"Provider '{name}' health check failed: {result.get('error')}")
        
        return errors

    # -- Default provider registration --------------------------------------

    def _register_default_memory_provider(self, name: str) -> None:
        """Auto-register the default mojo_memory provider."""
        if name != "mojo_memory":
            return
        try:
            from mojo_memory.services.memory_provider import MemoryProviderAdapter
            self.register_memory_provider("mojo_memory", MemoryProviderAdapter)
        except ImportError:
            logger.warning("provider_registry: could not import mojo_memory")

    def _register_default_dream_provider(self, name: str) -> None:
        """Auto-register the default mojo_dream provider."""
        if name != "mojo_dream":
            return
        try:
            from dreaming.dream_provider import DreamProviderAdapter
            self.register_dream_provider("mojo_dream", DreamProviderAdapter)
        except ImportError:
            logger.warning("provider_registry: could not import dreaming")

    def _register_default_persona_provider(self, name: str) -> None:
        """Auto-register default persona provider."""
        if name != "agency_persona":
            return
        try:
            from app.roles.persona_provider import AgencyPersonaModule
            self.register_persona_provider("agency_persona", AgencyPersonaModule)
        except ImportError:
            logger.warning("provider_registry: could not import agency persona provider")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    """Return the global provider registry singleton."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry

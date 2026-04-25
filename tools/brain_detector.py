#!/usr/bin/env python3
"""
Resource Detection Tool - Detects and validates LLM serving backends
Supports: LM Studio, Ollama, vLLM, mlx (macOS), and any OpenAI-compatible endpoint
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Resolve project root properly
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ------------------------------------------------------------------------
# Backend type constants
# ------------------------------------------------------------------------

class BackendType:
    LMSTUDIO = "lmstudio"
    OLLAMA = "ollama"
    VLLM = "vllm"
    MLX = "mlx"
    OPENAI_COMPATIBLE = "openai_compatible"


# ------------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------------

@dataclass
class BrainInfo:
    """Detected brain (model endpoint) information"""
    backend: str
    id: str
    name: str
    available: bool
    path: Optional[str] = None
    base_url: Optional[str] = None
    context_limit: Optional[int] = None
    output_limit: Optional[int] = None
    active_params: Optional[str] = None
    total_params: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "backend": self.backend,
            "id": self.id,
            "name": self.name,
            "available": self.available,
            "path": self.path,
            "base_url": self.base_url,
            "context_limit": self.context_limit,
            "output_limit": self.output_limit,
            "active_params": self.active_params,
            "total_params": self.total_params,
            "version": self.version,
            "error": self.error,
            "capabilities": self.capabilities,
        }

    def to_resource_entry(self, resource_id: str = None, priority: int = None) -> tuple:
        """
        Generate a flat resource_pool.json entry for this brain.

        Returns (resource_id, entry_dict) ready to write into the
        personal ~/.memory/config/resource_pool.json `resources` key.

        Local backends use api_key="lm-studio" (value ignored by server).
        Cloud backends leave api_key blank — caller must fill it in.
        """
        _BACKEND_TIER = {
            BackendType.LMSTUDIO: "free",
            BackendType.OLLAMA:   "free",
            BackendType.VLLM:     "free",
            BackendType.MLX:      "free",
            BackendType.OPENAI_COMPATIBLE: "free_api",
        }
        _BACKEND_PRIORITY = {
            BackendType.LMSTUDIO: 4,
            BackendType.OLLAMA:   6,
            BackendType.VLLM:     7,
            BackendType.MLX:      5,
            BackendType.OPENAI_COMPATIBLE: 20,
        }
        slug = "".join(c if c.isalnum() else "_" for c in self.id).strip("_").lower()
        rid = resource_id or f"{self.backend}_{slug}"
        is_local = self.backend in (BackendType.LMSTUDIO, BackendType.OLLAMA,
                                    BackendType.VLLM, BackendType.MLX)
        entry = {
            "type": "local" if is_local else "api",
            "provider": "openai",
            "base_url": self.base_url or "",
            "api_key": "lm-studio" if is_local else "",
            "model": self.id,
            "tier": _BACKEND_TIER.get(self.backend, "free_api"),
            "priority": priority if priority is not None else _BACKEND_PRIORITY.get(self.backend, 10),
            "enabled": True,
            "context_limit": self.context_limit or 32768,
            "output_limit": self.output_limit or 8192,
            "description": f"{self.name} via {self.backend}",
            "agentic_capable": "tool_use" in self.capabilities,
        }
        return rid, entry


# ------------------------------------------------------------------------
# Detection functions per backend
# ------------------------------------------------------------------------

def detect_lmstudio(base_url: Optional[str] = None) -> List[BrainInfo]:
    """Detect models served by LM Studio (OpenAI-compatible API)"""
    brains = []
    url = base_url or os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:8080/v1")
    
    try:
        # NOTE: xauth key required for local LM Studio access
        resp = requests.get(f"{url}/models", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            for m in models:
                brains.append(BrainInfo(
                    backend=BackendType.LMSTUDIO,
                    id=m.get("id", "unknown"),
                    name=m.get("id", "unknown"),
                    available=True,
                    base_url=url,
                    context_limit=m.get("context_length"),
                    output_limit=m.get("output_limit"),
                    capabilities=["tool_use", "reasoning", "code"],
                ))
        else:
            brains.append(BrainInfo(
                backend=BackendType.LMSTUDIO,
                id="unknown",
                name="LM Studio",
                available=False,
                base_url=url,
                error=f"HTTP {resp.status_code}",
            ))
    except requests.exceptions.ConnectionError:
        brains.append(BrainInfo(
            backend=BackendType.LMSTUDIO,
            id="unknown",
            name="LM Studio",
            available=False,
            base_url=url,
            error="Connection refused (may need xauth key)",
        ))
    except Exception as e:
        brains.append(BrainInfo(
            backend=BackendType.LMSTUDIO,
            id="unknown",
            name="LM Studio",
            available=False,
            base_url=url,
            error=str(e),
        ))
    return brains


def detect_ollama() -> List[BrainInfo]:
    """Detect models served by Ollama"""
    brains = []
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            for m in models:
                brains.append(BrainInfo(
                    backend=BackendType.OLLAMA,
                    id=m.get("name", "unknown"),
                    name=m.get("name", "unknown"),
                    available=True,
                    capabilities=["fast_inference", "local"],
                ))
        else:
            brains.append(BrainInfo(
                backend=BackendType.OLLAMA,
                id="unknown",
                name="Ollama",
                available=False,
                error=f"HTTP {resp.status_code}",
            ))
    except Exception as e:
        brains.append(BrainInfo(
            backend=BackendType.OLLAMA,
            id="unknown",
            name="Ollama",
            available=False,
            error=str(e),
        ))
    return brains


def detect_vllm() -> List[BrainInfo]:
    """Detect models served by vLLM"""
    brains = []
    try:
        resp = requests.get("http://localhost:8000/v1/models", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            for m in models:
                brains.append(BrainInfo(
                    backend=BackendType.VLLM,
                    id=m.get("id", "unknown"),
                    name=m.get("id", "unknown"),
                    available=True,
                    capabilities=["high_throughput", "fast_response"],
                ))
        else:
            brains.append(BrainInfo(
                backend=BackendType.VLLM,
                id="unknown",
                name="vLLM",
                available=False,
                error=f"HTTP {resp.status_code}",
            ))
    except Exception as e:
        brains.append(BrainInfo(
            backend=BackendType.VLLM,
            id="unknown",
            name="vLLM",
            available=False,
            error=str(e),
        ))
    return brains


def detect_mlx() -> List[BrainInfo]:
    """Detect models served by mlx-lm on macOS"""
    brains = []
    try:
        resp = requests.get("http://localhost:8080/v1/models", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            for m in models:
                brains.append(BrainInfo(
                    backend=BackendType.MLX,
                    id=m.get("id", "unknown"),
                    name=m.get("id", "unknown"),
                    available=True,
                    capabilities=["macos_optimized", "efficient"],
                ))
        else:
            brains.append(BrainInfo(
                backend=BackendType.MLX,
                id="unknown",
                name="mlx-lm",
                available=False,
                error=f"HTTP {resp.status_code}",
            ))
    except Exception as e:
        brains.append(BrainInfo(
            backend=BackendType.MLX,
            id="unknown",
            name="mlx-lm",
            available=False,
            error=str(e),
        ))
    return brains


# ------------------------------------------------------------------------
# Discovery dispatcher
# ------------------------------------------------------------------------

def discover_brains() -> List[BrainInfo]:
    """Run all detectors and merge results"""
    all_brains = []
    
    # Explicit override via environment
    explicit = os.environ.get("MOJO_BRAINS")
    if explicit:
        for b in explicit.split(","):
            b = b.strip()
            if b:
                all_brains.append(BrainInfo(
                    backend=BackendType.OPENAI_COMPATIBLE,
                    id=b, name=b, available=True,
                    base_url=os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:8080/v1"),
                ))
        return all_brains
    
    # Auto-detect all backends
    all_brains.extend(detect_lmstudio())
    all_brains.extend(detect_ollama())
    all_brains.extend(detect_vllm())
    all_brains.extend(detect_mlx())
    
    return all_brains


def validate_brain(brain: BrainInfo) -> Dict[str, Any]:
    """Validate a brain's configuration"""
    issues = []
    warnings = []
    
    if not brain.available:
        issues.append("Brain not available")
        return {"brain": brain.to_dict(), "valid": False, "issues": issues, "warnings": warnings}
    
    # Context size validation
    if brain.context_limit:
        if brain.context_limit < 8192:
            warnings.append(f"Small context limit: {brain.context_limit}")
        if brain.context_limit < 4096:
            issues.append(f"Context limit too small: {brain.context_limit}")
    
    # Typo detection for common model names
    name_lower = brain.name.lower()
    known_typos = {
        "qwen3.5-35b-a3b": "qwen3.6-35b-a3b",
        "gemma4-26b-a4b": "gemma-4-26b-a4b",
    }
    if name_lower in known_typos:
        # Both qwen3.5 and qwen3.6 exist - not a typo, just different models
        if brain.name in ["qwen3.5-35b-a3b", "qwen3.6-35b-a3b"]:
            warnings.append(f"Model detected: {brain.name} (both 3.5 and 3.6 versions exist)")
        else:
            warnings.append(f"Possible typo. Did you mean '{known_typos[name_lower]}'?")
    
    return {"brain": brain.to_dict(), "valid": len(issues) == 0, "issues": issues, "warnings": warnings}


# ------------------------------------------------------------------------
# CLI interface
# ------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Resource Detection Tool - Detect and validate LLM serving backends"
    )
    parser.add_argument("--lmstudio-base-url", default=None,
        help="LM Studio base URL (default: http://localhost:8080/v1)")
    parser.add_argument("--list", action="store_true",
        help="List all detected brains")
    parser.add_argument("--suggest", metavar="MODEL",
        help="Suggest fix for model name typo")
    parser.add_argument("--json", action="store_true",
        help="Output as JSON")
    
    args = parser.parse_args()
    
    if args.suggest:
        known_typos = {
            "qwen3.5-35b-a3b": "qwen3.6-35b-a3b",
            "gemma4-26b-a4b": "gemma-4-26b-a4b",
        }
        suggestion = known_typos.get(args.suggest.lower())
        result = {"input": args.suggest, "suggestion": suggestion}
        print(json.dumps(result, indent=2))
        return
    
    brains = discover_brains()
    results = [validate_brain(b) for b in brains]
    
    if args.json:
        output = {"brains": [b["brain"] for b in results], "validation": results}
        print(json.dumps(output, indent=2))
    else:
        print(f"Detected {len(brains)} backend(s) (including unavailable):\n")
        for r in results:
            b = r["brain"]
            status = "✓ AVAILABLE" if r["valid"] else "✗ UNAVAILABLE"
            print(f"  {b['name']} ({b['backend']}): {status}")
            if b.get("context_limit"):
                print(f"    Context: {b['context_limit']} tokens")
            if r["warnings"]:
                for w in r["warnings"]:
                    print(f"    ⚠ {w}")
            if r["issues"]:
                for i in r["issues"]:
                    print(f"    ❌ {i}")
            print()


if __name__ == "__main__":
    main()

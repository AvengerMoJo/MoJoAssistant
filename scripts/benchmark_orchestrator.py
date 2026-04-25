#!/usr/bin/env python3
"""
Generic Benchmark Orchestrator
Works with LM Studio, Ollama, vLLM, mlx, and any OpenAI-compatible endpoint
"""

import json
import os
import sys
from typing import Optional
from pathlib import Path

from tools.brain_detector import discover_brains, validate_brain, BackendType


class BenchmarkOrchestrator:
    def __init__(self):
        self.brains = discover_brains()
        self.validation = [validate_brain(b) for b in self.brains]
        self.available = [b for b, v in zip(self.brains, self.validation) if v["valid"]]
    
    def list_brains(self):
        """List all discovered brains with validation"""
        result = []
        for b, v in zip(self.brains, self.validation):
            entry = {
                "brain": b.name,
                "backend": b.backend,
                "available": b.available,
                "valid": v["valid"],
                "context_limit": b.context_limit,
                "output_limit": b.output_limit,
                "warnings": v["warnings"],
                "issues": v["issues"],
            }
            result.append(entry)
        return result
    
    def get_best_brain(self, prefer: Optional[str] = None) -> Optional[dict]:
        """Get the best available brain, optionally preferring a specific backend"""
        if not self.available:
            return None
        
        # If prefer specified, try to find it
        if prefer:
            for b in self.available:
                if b.name == prefer or b.id == prefer:
                    return b.to_dict()
        
        # Priority order
        priority = [BackendType.LMSTUDIO, BackendType.OLLAMA, BackendType.VLLM, BackendType.MLX]
        for backend in priority:
            for b in self.available:
                if b.backend == backend:
                    return b.to_dict()
        
        return self.available[0].to_dict()
    
    def suggest_model_fix(self, model_name: str) -> Optional[str]:
        """Suggest a fix for common model name typos"""
        from tools.brain_detector import validate_brain
        
        # Check against known typos
        common_typos = {
            "qwen3.5-35b-a3b": "qwen3.6-35b-a3b",
            "gemma4-26b-a4b": "gemma-4-26b-a4b",
        }
        
        if model_name.lower() in common_typos:
            return common_typos[model_name.lower()]
        return None


if __name__ == "__main__":
    orchestrator = BenchmarkOrchestrator()
    
    if len(sys.argv) < 2:
        print("Usage: benchmark_orchestrator.py <command> [args]")
        print("Commands:")
        print("  list-brains              - List all discovered brains")
        print("  get-best                 - Get the best available brain")
        print("  suggest <model_name>     - Suggest fix for model name")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list-brains":
        brains = orchestrator.list_brains()
        print(json.dumps({"brains": brains}, indent=2))
    
    elif command == "get-best":
        best = orchestrator.get_best_brain()
        print(json.dumps({"best_brain": best}, indent=2))
    
    elif command == "suggest":
        if len(sys.argv) < 3:
            print("ERROR: Specify model name")
            sys.exit(1)
        suggestion = orchestrator.suggest_model_fix(sys.argv[2])
        print(json.dumps({"input": sys.argv[2], "suggestion": suggestion}, indent=2))
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

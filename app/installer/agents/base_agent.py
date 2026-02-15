"""
Base class for setup agents.

All setup agents inherit from BaseSetupAgent and implement:
- load_context(): Load agent-specific context (prompts, docs, catalogs)
- execute(): Run the agent's task
"""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


class BaseSetupAgent(ABC):
    """Base class for all setup agents."""

    def __init__(self, llm=None, config_dir: str = "config"):
        """
        Initialize the agent.

        Args:
            llm: LLM interface for conversational setup (can be None for non-LLM agents)
            config_dir: Path to configuration directory
        """
        self.llm = llm
        self.config_dir = Path(config_dir)
        self.context = {}
        self.result = {"success": False, "message": "", "details": {}}

    @abstractmethod
    def load_context(self) -> Dict[str, Any]:
        """
        Load agent-specific context (prompts, documentation, catalogs).

        Returns:
            Dictionary containing context data
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the agent's task.

        Args:
            **kwargs: Task-specific parameters

        Returns:
            Result dictionary with:
            - success: bool
            - message: str
            - details: dict (optional additional info)
        """
        pass

    def load_json(self, filename: str) -> Dict:
        """Load a JSON file from config directory."""
        path = self.config_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_json(self, filename: str, data: Dict) -> None:
        """Save data to a JSON file in config directory."""
        path = self.config_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_prompt(self, prompt_file: str) -> str:
        """Load a prompt markdown file."""
        path = self.config_dir / "installer_prompts" / prompt_file
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_documentation(self, doc_paths: list) -> str:
        """
        Load multiple documentation files and combine them.

        Args:
            doc_paths: List of relative paths to documentation files

        Returns:
            Combined documentation as string
        """
        docs = []
        for doc_path in doc_paths:
            path = Path(doc_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    docs.append(f"# {path.name}\n\n{f.read()}\n\n")
            else:
                print(f"Warning: Documentation not found: {doc_path}")

        return "\n---\n\n".join(docs)

    def expand_path(self, path: str) -> Path:
        """Expand ~ and environment variables in path."""
        return Path(os.path.expanduser(os.path.expandvars(path)))

    def chat(self, message: str) -> str:
        """
        Send a message to the LLM and get response.

        Args:
            message: Message to send

        Returns:
            LLM response
        """
        if not self.llm:
            raise RuntimeError("LLM not available for this agent")

        return self.llm.chat(message)

    def set_success(self, message: str, **details):
        """Mark agent execution as successful."""
        self.result = {
            "success": True,
            "message": message,
            "details": details
        }

    def set_failure(self, message: str, **details):
        """Mark agent execution as failed."""
        self.result = {
            "success": False,
            "message": message,
            "details": details
        }

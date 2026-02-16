"""
Setup agents for MoJoAssistant installer.

Each agent handles a specific aspect of installation/configuration.
"""

from .base_agent import BaseSetupAgent
from .model_selector import ModelSelectorAgent
from .env_configurator import EnvConfiguratorAgent

__all__ = ["BaseSetupAgent", "ModelSelectorAgent", "EnvConfiguratorAgent"]

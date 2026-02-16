"""
MoJoAssistant Smart Installer

Configuration-driven, LLM-powered installation system.
"""

from .orchestrator import SmartInstaller, run_smart_installer

__version__ = "1.0.0"
__all__ = ["SmartInstaller", "run_smart_installer"]

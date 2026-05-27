"""
MoJoAssistant Smart Installer

Configuration-driven, LLM-powered installation system.
"""

from .orchestrator import SmartInstaller, run_smart_installer

__version__ = "1.4.2-beta"
__all__ = ["SmartInstaller", "run_smart_installer"]

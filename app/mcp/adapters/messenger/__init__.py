"""
MoJoAssistant Messenger SDK
===========================

Add a new messaging platform in three steps:

  1. Subclass MessengerAdapter and set adapter_type = "my_platform"
  2. Implement send_notification() and send_hitl()
  3. Register via one of:
       a) Entry points  — add to your package's pyproject.toml:
              [project.entry-points."mojoassistant.messenger"]
              my_platform = "my_package.module:MyAdapter"
       b) Drop-in file  — place YourAdapter.py in ~/.memory/plugins/messenger/
       c) Built-in      — add to app/mcp/adapters/messenger/ and import in registry._load_builtins()

  Then enable in ~/.memory/config/notifications_config.json:
       {
         "messengers": {
           "my_platform": { "enabled": true, "token": "..." }
         }
       }

Call handle_response(task_id, reply) when the user replies — the base class
routes the answer back into the scheduler automatically.
"""

from app.mcp.adapters.messenger.base import MessengerAdapter
from app.mcp.adapters.messenger.registry import register, load_all
from app.mcp.adapters.messenger.manager import (
    MessengerManager,
    get_shared_manager,
    init_shared_manager,
)

__all__ = [
    "MessengerAdapter",
    "register",
    "MessengerManager",
    "get_shared_manager",
    "init_shared_manager",
]

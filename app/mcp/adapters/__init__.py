"""Protocol adapters for MCP server"""
from app.mcp.adapters.base import ProtocolAdapter
from app.mcp.adapters.stdio import STDIOAdapter

# HTTPAdapter requires FastAPI form-data support (python-multipart).
# Imported lazily so unit tests that only need SSENotifier/EventLog
# don't have to install the full HTTP stack.
def __getattr__(name: str):
    if name == "HTTPAdapter":
        from app.mcp.adapters.http import HTTPAdapter
        return HTTPAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["ProtocolAdapter", "STDIOAdapter", "HTTPAdapter"]

"""Telegram hub: the owner's working channel with their assistants.

Deliberately NOT a notification adapter (those are Discord/ntfy: read 99%, write 1%) and NOT the
dashboard chat (a private, recall-only debrief). Here the owner talks, on a phone, with one assistant
at a time -- the personal assistant by default -- in InteractionMode.OWNER_HUB: every exchange is kept
as role chat history, which the dreaming pipeline turns into memory.

Only the configured owner chat is answered; any other chat is ignored. A failure is answered in the chat
with its reason; nothing is retried under a different agent.

Config (~/.memory/config/telegram_hub.json):
    {"enabled": true, "default_agent": "anna", "agents": ["anna", "rebecca", "popo"]}
`agents` is optional: without it any existing role can be addressed with /to.
Secrets: TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_CHAT_ID come from the environment (.env), never the config.
State (poll offset, current agent, session ids): ~/.memory/state/telegram_hub.json.
"""
import asyncio
import json
import logging
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("mojo_assistant.telegram_hub")

MAX_MESSAGE_CHARS = 4000  # Telegram's limit is 4096
HELP_TEXT = (
    "Talking with {agent}.\n"
    "/to <agent> switch assistant\n"
    "/agents list assistants\n"
    "/who who you are talking to\n"
    "/new start a fresh session with the current assistant\n"
    "Anything else is sent to the current assistant."
)

ExchangeFn = Callable[[str, str, str], Awaitable[Dict[str, Any]]]  # (agent, session_id, text) -> result
SendFn = Callable[[str], Awaitable[None]]


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> List[str]:
    """Split on paragraph, then line, then hard boundaries so each part fits one Telegram message."""
    text = text.strip() or "(empty reply)"
    parts: List[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    parts.append(text)
    return parts


def to_plain_text(md: str) -> str:
    """Markdown -> text that reads cleanly in a Telegram bubble (sent without parse_mode, so nothing renders).

    Headings become a plain line, bold/italic/code markers are dropped, bullets become a dot, tables
    become one line per row, links keep their URL in brackets, and runs of blank lines collapse."""
    out, in_code = [], False
    for line in md.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append("  " + line)
            continue
        if re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", line) and "-" in line:
            continue  # table separator row
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^(\s*)[*+-]\s+", lambda m: m.group(1) + "\u2022 ", line)
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            line = " \u2014 ".join(c for c in cells if c)
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", line)
        line = re.sub(r"(\*\*|__)(.+?)\1", r"\2", line)
        line = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        out.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def load_hub_config(path: Optional[Path] = None) -> Dict[str, Any]:
    from app.config.paths import get_memory_subpath
    path = path or Path(get_memory_subpath("config")) / "telegram_hub.json"
    if not path.exists():
        return {"enabled": False}
    return json.loads(path.read_text(encoding="utf-8"))


class TelegramHub:
    def __init__(self, token: str, chat_id: str, config: Dict[str, Any], state_path: Path,
                 exchange: ExchangeFn, role_exists: Callable[[str], bool], role_ids: Callable[[], List[str]]):
        if not token or not chat_id:
            raise ValueError("telegram hub needs TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_CHAT_ID")
        self._token = token
        self._chat_id = str(chat_id)
        self._allowed: Optional[List[str]] = config.get("agents")
        self._default = config.get("default_agent") or "anna"
        self._state_path = Path(state_path)
        self._exchange = exchange
        self._role_exists = role_exists
        self._role_ids = role_ids
        self._state = self._load_state()
        self._task: Optional[asyncio.Task] = None
        if not self._valid_agent(self._default):
            raise ValueError(f"telegram hub: default_agent {self._default!r} is not an available role")

    # -- state ---------------------------------------------------------------
    def _load_state(self) -> Dict[str, Any]:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        return {"offset": 0, "agent": None, "sessions": {}}

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    @property
    def agent(self) -> str:
        return self._state.get("agent") or self._default

    def _valid_agent(self, agent: str) -> bool:
        if self._allowed is not None and agent not in self._allowed:
            return False
        return self._role_exists(agent)

    def _agents(self) -> List[str]:
        return [a for a in self._role_ids() if self._allowed is None or a in self._allowed]

    def _session_for(self, agent: str, fresh: bool = False) -> str:
        """One session per agent per day: dreaming ingests a session file once, so a session that
        never ends would never have its later exchanges processed."""
        today = datetime.now().strftime("%Y%m%d")
        base = f"hub_{agent}_{today}"
        current = self._state["sessions"].get(agent)
        if current and current.startswith(base) and not fresh:
            return current
        if fresh and current and current.startswith(base):
            tail = current[len(base):].lstrip("_")
            sid = f"{base}_{int(tail) + 1 if tail.isdigit() else 2}"
        else:
            sid = base
        self._state["sessions"][agent] = sid
        self._save_state()
        return sid

    # -- message handling ----------------------------------------------------
    async def handle_text(self, text: str, send: SendFn) -> None:
        text = (text or "").strip()
        if not text:
            return
        if text.startswith("/"):
            await self._command(text, send)
            return
        agent = self.agent
        session_id = self._session_for(agent)
        try:
            result = await self._exchange(agent, session_id, text)
        except Exception as e:
            logger.error("[telegram_hub] exchange with %s failed: %s", agent, e, exc_info=True)
            await send(f"{agent} could not answer: {type(e).__name__}: {e}")
            return
        if result.get("error"):
            await send(f"{agent} could not answer: {result['error']}")
            return
        if result.get("model"):
            self._state["model"] = result["model"]
            self._save_state()
        for part in split_message(to_plain_text(result.get("response") or "")):
            await send(part)

    async def _command(self, text: str, send: SendFn) -> None:
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip().lower()
        if cmd in ("/start", "/help"):
            await send(HELP_TEXT.format(agent=self.agent))
        elif cmd == "/who":
            model = self._state.get("model")
            await send(f"You are talking with {self.agent} (session {self._session_for(self.agent)})."
                       + (f"\nLast answer came from {model}." if model else ""))
        elif cmd == "/agents":
            await send("Assistants: " + ", ".join(self._agents()))
        elif cmd == "/to":
            if not arg:
                await send("Usage: /to <agent>. See /agents.")
            elif not self._valid_agent(arg):
                await send(f"No assistant {arg!r}. Available: " + ", ".join(self._agents()))
            else:
                self._state["agent"] = arg
                self._save_state()
                await send(f"Now talking with {arg}.")
        elif cmd == "/new":
            sid = self._session_for(self.agent, fresh=True)
            await send(f"New session with {self.agent} ({sid}).")
        else:
            await send(f"Unknown command {cmd}. Try /help.")

    async def handle_update(self, update: Dict[str, Any], send: SendFn) -> None:
        msg = update.get("message") or {}
        if str((msg.get("chat") or {}).get("id", "")) != self._chat_id:
            return  # not the owner chat
        await self.handle_text(msg.get("text") or "", send)

    # -- Telegram transport --------------------------------------------------
    async def _api(self, method: str, payload: Dict[str, Any], timeout: int = 10) -> Optional[Dict[str, Any]]:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self._token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")

        def call():
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        try:
            return await asyncio.get_event_loop().run_in_executor(None, call)
        except Exception as e:
            logger.warning("[telegram_hub] %s failed: %s", method, e)
            return None

    async def _send(self, text: str) -> None:
        resp = await self._api("sendMessage", {"chat_id": self._chat_id, "text": text})
        if not resp or not resp.get("ok"):
            logger.error("[telegram_hub] sendMessage failed: %s", resp)

    async def _poll_loop(self) -> None:
        backoff = 1
        while True:
            try:
                resp = await self._api("getUpdates", {"offset": self._state["offset"], "timeout": 30,
                                                      "allowed_updates": ["message"]}, timeout=35)
                if not (resp and resp.get("ok")):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                backoff = 1
                for update in resp.get("result", []):
                    self._state["offset"] = update["update_id"] + 1
                    self._save_state()
                    await self._api("sendChatAction", {"chat_id": self._chat_id, "action": "typing"})
                    await self.handle_update(update, self._send)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("[telegram_hub] poll error: %s", e, exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[telegram_hub] started (default agent %s)", self._default)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()


def build_hub(resource_manager_factory: Optional[Callable[[], Any]] = None,
              scheduler: Optional[Any] = None) -> Optional[TelegramHub]:
    """Build the hub from config and environment. None when disabled; raises when enabled but misconfigured."""
    from app.config.paths import get_memory_subpath
    from app.roles.role_manager import RoleManager
    from app.scheduler.interaction_mode import InteractionMode
    from app.scheduler.role_chat import RoleChatSession

    config = load_hub_config()
    if not config.get("enabled"):
        return None
    rm_holder: Dict[str, Any] = {}

    async def exchange(agent: str, session_id: str, text: str) -> Dict[str, Any]:
        if "rm" not in rm_holder:
            rm_holder["rm"] = resource_manager_factory() if resource_manager_factory else None
        session = RoleChatSession(role_id=agent, session_id=session_id, mode=InteractionMode.OWNER_HUB,
                                  scheduler=scheduler, routable_roles=config.get("agents"))
        return await session.exchange(message=text, resource_manager=rm_holder["rm"])

    roles = RoleManager()
    return TelegramHub(
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""), chat_id=os.getenv("TELEGRAM_OWNER_CHAT_ID", ""),
        config=config, state_path=Path(get_memory_subpath("state")) / "telegram_hub.json",
        exchange=exchange, role_exists=lambda r: roles.get(r) is not None, role_ids=lambda: sorted(r["id"] for r in roles.list_roles() if r.get("id")),
    )

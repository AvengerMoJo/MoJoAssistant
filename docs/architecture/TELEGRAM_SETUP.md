# Telegram Messenger Setup

Telegram is the active free HITL/notification channel (`app/mcp/adapters/messenger/telegram.py`),
built against the same `MessengerAdapter` SDK as Discord. WeCom
(`app/mcp/adapters/messenger/wecom.py`) is suspended — it stays in the repo,
disabled by config, but is not being actively pursued (business account
registration was too costly for the value it added). Telegram needs no
business verification and delivers both plain notifications and interactive
HITL questions (inline-keyboard buttons, plus free-text reply fallback).

## Architecture

```
Telegram Bot API (api.telegram.org)
       │
       ├── sendMessage / editMessageReplyMarkup / answerCallbackQuery (outbound)
       └── getUpdates long-poll (inbound: button clicks + text replies)
       ▼
TelegramMessengerAdapter (app/mcp/adapters/messenger/telegram.py)
       │
       └── registered via app/mcp/adapters/messenger/registry.py (built-in)
              └── loaded by MessengerManager, driven by
                  ~/.memory/config/notifications_config.json → messengers.telegram
```

No extra Python packages — the adapter uses `urllib` + `asyncio.run_in_executor`
for HTTP, same pattern as WeCom.

## 1. Create the bot

1. Open Telegram, message **@BotFather**.
2. Send `/newbot`, follow the prompts (choose a display name and a
   `..._bot`-suffixed username).
3. BotFather replies with a token, e.g. `123456789:AAExampleTokenAB-CDEF...`.
   This is `bot_token` / `TELEGRAM_BOT_TOKEN`.

## 2. Get your chat ID

1. Send any message to your new bot from the Telegram account that should
   receive notifications (the bot can't message you until you've messaged it
   first).
2. In a browser, visit:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   (replace `<TOKEN>` with the token from step 1).
3. In the JSON response, find `result[0].message.chat.id` — that number
   (can be negative for group chats) is `chat_id` / `TELEGRAM_OWNER_CHAT_ID`.

## 3. Configure MoJoAssistant

Either set environment variables:

```bash
export TELEGRAM_BOT_TOKEN="123456789:AAExampleTokenAB-CDEF..."
export TELEGRAM_OWNER_CHAT_ID="987654321"
```

or edit `~/.memory/config/notifications_config.json`:

```json
"messengers": {
  "telegram": {
    "enabled": true,
    "bot_token": "123456789:AAExampleTokenAB-CDEF...",
    "chat_id": "987654321"
  }
}
```

Env vars take precedence only when the config fields are left empty — see
`TelegramMessengerAdapter.__init__` (`config.get(...) or os.getenv(...)`).

## 4. Restart and verify

```bash
systemctl --user restart mojoassistant
journalctl --user -u mojoassistant -f | grep telegram
```

Expect:
```
[messenger/telegram] started (chat_id=987654321)
```

Trigger a test notification or HITL question from a scheduled task and
confirm it arrives in the Telegram chat. Button-click and free-text replies
both route back through `handle_response(task_id, reply)` — no additional
wiring needed.

## Limits worth knowing

- Message text is truncated to 4096 chars (Telegram's hard limit).
- Inline keyboard `callback_data` is truncated to 64 bytes per button.
- The adapter only long-polls (`getUpdates`) — no webhook/public URL needed,
  unlike WeCom's callback route.

## WeCom status (suspended, not deleted)

`messengers.wecom.enabled` stays `false` in
`~/.memory/config/notifications_config.json`. The code
(`wecom.py`, `wecom_crypto.py`, `app/mcp/routers/wecom.py`) remains in the
repo as a working, tested framework in case a future account makes it worth
revisiting, but no further work is planned on it. See
`~/.claude/projects/-home-alex-Development-Personal-MoJoAssistant/memory/project_wecom_module.md`
for the original context.

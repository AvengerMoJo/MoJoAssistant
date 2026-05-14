# Discord Community Assistant Spec

## Goal
Provide a public-facing community assistant on Discord that answers support questions through MoJo while maintaining strict security boundaries.

## Architecture
1. Discord Gateway (`app/community/discord_gateway.py`)
2. Community role template (`config/examples/roles/community_host.example.json`)
3. MoJo role-chat backend (`RoleChatSession`) for response generation

## Security Baseline
1. Mention-only mode by default (`DISCORD_MENTION_ONLY=true`)
2. Role-isolated assistant (`community_host`) with limited capabilities
3. Command-like payload suppression (`!sudo`, `/exec`, etc.)
4. Message length limits (`DISCORD_MAX_PROMPT_CHARS`)
5. No direct shell, filesystem write, or high-risk tool exposure
6. Escalation path for low-confidence or security-sensitive questions

## Runtime Config
Required:
- `DISCORD_BOT_TOKEN`

Optional:
- `DISCORD_COMMUNITY_ROLE_ID` (default: `community_host`)
- `DISCORD_MENTION_ONLY` (default: `true`)
- `DISCORD_MAX_PROMPT_CHARS` (default: `2000`)

Role location:
- Runtime role definitions should live in `~/.memory/config/roles/`.
- Use `config/examples/roles/community_host.example.json` as a starting template.

## Start Bot
```python
from app.community.discord_gateway import run_bot
run_bot()
```

## Operational Rules
1. Bot answers project-support scope only.
2. Unsafe requests receive refusal + maintainer escalation guidance.
3. All failures should fail closed (no tool/action side effects).
4. Rotate Discord token and enforce least-privileged bot permissions.

## Future Enhancements
1. Per-channel policy and rate limits.
2. Moderator approval workflow for sensitive replies.
3. RCA ingestion for rejected/flagged community responses.

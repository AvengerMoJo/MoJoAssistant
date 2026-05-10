# MoJoAssistant Installation Guide

Install MoJoAssistant so the MCP server runs locally and your Chat AI clients can connect.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Python 3.11+ | Runtime (manual install only) |
| git | Clone the repo |
| LM Studio (or compatible OpenAI-compatible inference server) | LLM inference — MoJoAssistant does not bundle a model |
| Docker (optional) | Recommended; see Option A |
| ntfy (optional) | Notification / HITL callback channel |

---

## Option A — Docker (recommended)

One command to start. All deps baked into the image.

```bash
docker compose up
```

### Configure `.env`

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Key fields to set:

| Key | Default | What to change |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | Leave as-is for Docker |
| `SERVER_PORT` | `8000` | Only if you need a different port |
| `DASHBOARD_PASSWORD` | `change_me` | Set a password for the `/dashboard` UI |
| `MCP_API_KEY` | `demo_key_for_development` | API key for MCP client auth |
| `MEMORY_PATH` | `~/.memory` | Host path where MoJoAssistant stores data |

### Configure inference server

Set your LM Studio (or OpenAI-compatible server) endpoint in `config/llm_config.json` under `api_models`:

```json
"lmstudio": {
    "provider": "openai",
    "base_url": "http://localhost:1234/v1",
    "api_key": "not-needed",
    "model": "your-model-name",
    "enabled": true
}
```

Personal override goes in `~/.memory/config/llm_config.json` (wins on any key conflict).

### Verify

Wait for the container to start (15s healthcheck period), then:

```bash
curl http://localhost:8000/health
```

Expected: a JSON object with `"status": "ok"` (or similar system status).

---

## Option B — Manual (systemd user service)

For Linux users who want the server running as a persistent user service.

### 1. Clone and install

```bash
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
python -m venv venv
source venv/bin/activate
pip install -r requirements-runtime.txt
pip install --no-cache-dir submodules/dreaming-memory-pipeline/
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set DASHBOARD_PASSWORD, MCP_API_KEY, etc.
```

### 3. Install systemd service

```bash
./scripts/install_service.sh
```

This copies `scripts/mojoassistant.service` to `~/.config/systemd/user/`, reloads the daemon, and starts the service.

Equivalent manual steps:

```bash
mkdir -p ~/.config/systemd/user
cp scripts/mojoassistant.service ~/.config/systemd/user/mojoassistant.service
systemctl --user daemon-reload
systemctl --user enable --now mojoassistant
```

### Verify

```bash
curl http://localhost:8000/health
```

Check service status:

```bash
systemctl --user status mojoassistant
journalctl --user -u mojoassistant -n 30 --no-pager
```

---

## First Run Checklist

After installation, verify these five things before connecting a Chat AI client:

- [ ] **Health green** — `curl http://localhost:8000/health` returns OK
- [ ] **Dashboard accessible** — open `http://localhost:8000/dashboard` in a browser
- [ ] **One role loaded** — check the dashboard shows at least one agent role available
- [ ] **One task dispatched** — send a test task via the dashboard or curl
- [ ] **Dreaming reachable** — `curl http://localhost:8000/api/dreaming` responds (nightly consolidation is active)

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Health endpoint returns 500 | Check `journalctl --user -u mojoassistant` (systemd) or `docker logs mojoassistant` (Docker) |
| LM Studio connection fails | Verify `base_url` in `config/llm_config.json` matches your LM Studio server; default port is 1234 |
| Dashboard won't load | Ensure `DASHBOARD_PASSWORD` is set in `.env` |
| Docker volume empty | Host `~/.memory` maps to container `/home/mojo/.memory` — data persists across restarts |

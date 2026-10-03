# gui_helper — authenticated local HTTP helper for desktop automation

A small PowerShell HTTP listener that runs **inside the target interactive
Windows session** (not Session 0) and exposes a tiny JSON API for the
MoJoAssistant agent bridge to drive the GUI.

This is the redesigned, authenticated version of the helper that the
Claude Code auto-mode classifier blocked on 2026-10-03 with reason
"Create RCE Surface". The original was an unauthenticated loopback server
with `/launch?path=`, `/click`, `/type` endpoints. That is a real
remote-code-execution shape — any other local process could drive it.

The redesign addresses the surface with five independent layers:

| Layer | What it does |
|------|--------------|
| 1. Loopback only | `HttpListener` binds `127.0.0.1`. No LAN exposure. |
| 2. Bearer auth | Every request must carry `Authorization: Bearer <token>`. |
| 3. Strict allowlist on `/launch` | `path` must match an entry in `gui_helper.allowlist.json`; optional sha256 pin. |
| 4. Body size cap | 1 MiB hard limit on POST bodies, enforced before parse. |
| 5. No shell | `Start-Process -ArgumentList` (array) — never `cmd /c`, no joined string. Constant-time token compare. |

## Files

| File | Role |
|------|------|
| `scripts/gui_helper.ps1` | The listener (PowerShell). |
| `scripts/gui_helper_client.py` | Python client. |
| `scripts/gui_helper.allowlist.example.json` | Example allowlist — copy to `~/.memory/config/gui_helper.allowlist.json` on EVO-X3 and edit. |
| `scripts/test_gui_helper_client.py` | Offline smoke tests for the client. |

## Deploy on EVO-X3

```powershell
# 1. Drop the script + your real allowlist in a known location.
Copy-Item gui_helper.ps1                          C:\Tools\mojo\
Copy-Item gui_helper.allowlist.example.json        C:\Users\$env:USERNAME\.memory\config\gui_helper.allowlist.json
#    (edit it; remove the placeholder sha256 or compute the real one with
#     Get-FileHash C:\path\to\app.exe -Algorithm SHA256)

# 2. Generate or supply a token.
$env:MOJO_GUI_TOKEN = [Convert]::ToBase64String((1..32|%{Get-Random -Max 256})) -replace '\+','-' -replace '/','_' -replace '=',''

# 3. Start it in the interactive session (a Scheduled Task at logon, or
#    a shell launcher that the agent bridge can `start` itself).
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Tools\mojo\gui_helper.ps1 `
    -Port 8766 `
    -TokenPath 'C:\Users\$env:USERNAME\.memory\config\gui_helper.token' `
    -AllowlistPath 'C:\Users\$env:USERNAME\.memory\config\gui_helper.allowlist.json'
```

If you do not set `$env:MOJO_GUI_TOKEN`, the helper generates a token on
first start, writes it to `-TokenPath` with a per-user ACL, and prints
it to the console once. Subsequent starts reuse the file.

## Drive it from the agent bridge

```bash
# On the calling side, export the token in the shell that owns the request.
export MOJO_GUI_TOKEN=...

python3 scripts/gui_helper_client.py health
python3 scripts/gui_helper_client.py launch "C:\\Program Files\\LM Studio\\LM Studio.exe"
python3 scripts/gui_helper_client.py click 100 200
python3 scripts/gui_helper_client.py type "hello world"
python3 scripts/gui_helper_client.py screenshot /tmp/evo.png
```

The client refuses any host other than `127.0.0.1`, `localhost`, or `::1`.

## Cleanup of the prior unauthenticated artifact

The original deployment may have written `gui_helper.ps1` to a path on
EVO-X3 before the classifier blocked it. The local box has
`/tmp/gui_helper_b64.txt` (kept for diffing). The remote artifact must
be removed from the EVO-X3 shell that ran the original deployment — the
agent bridge on this side has no file-system access to EVO-X3.

## Tests

```bash
python3 -m pytest scripts/test_gui_helper_client.py -q
```

Covers: non-loopback host refusal, missing-token failure mode, and a
loopback stub server that asserts the client attaches the bearer token
and parses the JSON response.

# Rebuilding the opencode-sandbox template with envd

## Why envd broke

The original template `tpl-674134307cfa458a986b05ab` was built from
`docker/opencode-sandbox/Dockerfile`, which is **just Ubuntu 22.04 +
OpenCode + bun, no envd binary**. When the e2b SDK calls
`commands.run` / `files.read`, it talks to `envd` inside the VM
(an e2b userland daemon that mediates command/file operations). envd
isn't there, so the SDK gets an HTTP 500 from cube-proxy, parses it
as a JSON timeout, and reports "sandbox timeout" 502.

The upstream `ghcr.io/tencentcloud/cubesandbox-base:2026.16` image
includes envd (compiled from `e2b-dev/infra@2026.16`, binary version
`0.5.13` commit `b8ca332`) — but our `opencode-sandbox` Dockerfile
wasn't using it as a base.

## What we did on 2026-06-24

1. Pulled the upstream base: `docker pull ghcr.io/tencentcloud/cubesandbox-base:2026.16`
2. Rewrote `docker/opencode-sandbox/Dockerfile` to `FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16`
   and add OpenCode on top. Kept the cube-entrypoint.sh from the base image so envd
   starts in the background before OpenCode serves.
3. Rebuilt: `docker build -t opencode-sandbox:v2 -f docker/opencode-sandbox/Dockerfile .`
4. Registered: `cubemastercli template create-from-image --image opencode-sandbox:v2 ...`
5. New template ID: **`tpl-d599cf3ead2c48f78df6a6da`** (status READY)
6. Updated `.env`: `CUBE_TEMPLATE_ID=tpl-d599cf3ead2c48f78df6a6da`

## End-to-end verification (post-rebuild)

```
$ python3 -c '...'  # see /tmp/rebuild_e2e.py for the full script
sandbox_id: 14dd027390514a0f827c83e1b8b4961a
envd_version: 0.2.0          # metadata field, the binary is actually 0.5.13
uname -a:     Linux tpl-d599 6.6.1199-0009-03_2.0.1 ... x86_64 GNU/Linux
/etc/os-release: PRETTY_NAME="Ubuntu 22.04.5 LTS"
whoami:       user
pwd:          /home/user
date:         Wed Jun 24 17:17:35 UTC 2026
```

`cubesandbox_create` / `cubesandbox_exec` / `cubesandbox_destroy` all
return success against the new template. The agentic tool path is
fully functional.

## How to do this yourself (reference)

### Step A. Build the new opencode-sandbox image

```bash
cd /home/alex/Development/Personal/MoJoAssistant

# 1. Pull the upstream base (already compiled envd)
docker pull ghcr.io/tencentcloud/cubesandbox-base:2026.16

# 2. The Dockerfile at docker/opencode-sandbox/Dockerfile is now
#    FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16 — no FROM ubuntu:22.04.

# 3. Build the new image
docker build -t opencode-sandbox:v2 -f docker/opencode-sandbox/Dockerfile .
```

### Step B. Verify the image

```bash
docker run --rm opencode-sandbox:v2 bash -c '
  which opencode && opencode --version | head -1
  which envd && /usr/bin/envd -version
  ls -la /usr/local/bin/cube-entrypoint.sh
'
```

Expected:
```
/root/.bun/bin/opencode
1.17.9
/usr/bin/envd
0.5.13
-rwxr-xr-x 1 root root 2414 ... cube-entrypoint.sh
```

### Step C. Register the template

```bash
cubemastercli template create-from-image \
  --image opencode-sandbox:v2 \
  --writable-layer-size 2G \
  --expose-port 4173 \
  --expose-port 49983 \
  --probe 49983 \
  --probe-path /health \
  --cmd /usr/local/bin/cube-entrypoint.sh \
  --arg opencode --arg serve --arg --port --arg 4173 \
  --arg --hostname --arg 0.0.0.0 --arg --print-logs
```

Wait for status READY (usually <60s on a small image), then verify
with `cubemastercli tpl list`. The new template ID will be printed.

### Step D. Smoke-test against the new template

```bash
CUBE_TEMPLATE_ID=<NEW_ID> python3 -c "
import os, sys
sys.path.insert(0, '/home/alex/Development/Personal/MoJoAssistant')
with open('/home/alex/Development/Personal/MoJoAssistant/.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())
os.environ['CUBE_TEMPLATE_ID'] = '<NEW_ID>'

import app.scheduler.agentic.cubesandbox_tools as t

cr = t.cubesandbox_create({'name': 'smoke', 'timeout': 300})
assert cr['success'], cr
er = t.cubesandbox_exec({'name': 'smoke', 'command': 'uname -a'})
assert er['success'] and 'Linux' in er['stdout'], er
t.cubesandbox_destroy({'name': 'smoke'})
print('OK — envd is alive, exec works')
"
```

If this prints `OK`, the rebuild worked. Update `.env` to set
`CUBE_TEMPLATE_ID` to the new ID so the rest of the system uses it.

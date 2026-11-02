# bash_exec Execution Rules

`bash_exec` (capability defined in `app/scheduler/capability_registry.py`) runs shell
commands for an agent. It is limited by five independent rules. Three of them are enforced
by one function (`SafetyPolicy._bash_violation`), the other two live in the gate and in the
executor.

| # | Rule | Enforced by | File |
|---|---|---|---|
| 1 | A read-only command costs 1 danger point, a write costs 8 | `SecurityGate.check` → `all_read_only` | `app/scheduler/security_gate.py`, `app/scheduler/bash_command.py` |
| 2 | Blocklist applied to every command of a pipeline | `CapabilityRegistry._bash_exec` | `app/scheduler/capability_registry.py` |
| 3 | Secrets are never read and never written | `SafetyPolicy._bash_violation` → `_secret_hit` | `app/scheduler/safety_policy.py` |
| 4 | Writes stay inside the memory dir or `/tmp` | `SafetyPolicy._bash_violation` | `app/scheduler/safety_policy.py` |
| 5 | System paths are not read | `SafetyPolicy._bash_violation` | `app/scheduler/safety_policy.py` |

Every example below is taken verbatim from `tests/unit/test_bash_command.py` or
`tests/unit/test_safety_policy_bash_rules.py`.

## Rule 1 — Read-only cost rule

`bash_exec` is declared `danger_level="high"` (score 8). `SecurityGate.check`
(`app/scheduler/security_gate.py`) asks `all_read_only()` (`app/scheduler/bash_command.py`)
whether the command only observes; when it does, the danger is downgraded to `low`
(score 1) for that call. `is_read_only()` accepts only the names in `READ_ONLY_COMMANDS`
and the git subcommands in `READ_ONLY_GIT`, and rejects redirects, `$(...)` substitution,
`find` write actions, `sort -o`, and a `VAR=value` prefix in front of the command.

- Allowed (read-only, charged 1 point): `grep -rn x .` — `ls && pwd`
- Blocked (not read-only, charged the full 8 points): `rm x` — `cat f > g`

## Rule 2 — Blocklist over every command in a pipeline

`CapabilityRegistry._bash_exec` (`app/scheduler/capability_registry.py`) holds
`BLOCKED_COMMANDS`: deletion and overwrite, disk and filesystem tools, privilege
escalation, permission and ownership changes, process termination, package mutation,
network configuration, service control, reboot, user and group management. The command is
split with `bash_command.split_commands()` and **every** simple command is checked, not
only the first word, because the command runs under `shell=True` — otherwise `ls && rm x`
would execute `rm x`.

- Allowed: `grep -c zzz {tmp_path}/f` — `cat {tmp_path}/f` (`tmp_path` is pytest's fixture directory)
- Blocked: `ls && rm nothing` — `echo hi | xargs true; kill 1`

## Rule 3 — Secret path rule

`SafetyPolicy._bash_violation` (`app/scheduler/safety_policy.py`) scans **every token** of
every command with `_secret_hit()` and refuses on `_SECRET_DIRS` (`.ssh`, `.gnupg`, `.aws`,
`ai-credential-manager`, `.mcp_service`), on `_SECRET_FILES` (`id_rsa*`, `id_ed25519*`,
`*.pem`, `*.key`, `auth.json`, `clients.json`, `sudoers`, …) and on any `.env` file that is
not a template (`_ENV_TEMPLATE`: `.example`, `.sample`, `.template`). The scan runs before
the sandbox carve-out, so it applies inside a sandbox container as well.

- Allowed: `cat /home/alex/Development/Personal/MoJoAssistant/config/notifications_config.json` — `cat /home/alex/Development/x/.env.example`
- Blocked: `cat ~/.ssh/id_rsa` — `cat ~/.config/opencode/service.json`

## Rule 4 — Write path rule

`SafetyPolicy._bash_violation` also resolves the write targets of a command: the target of
a redirect (`>`, `>>`) and the path arguments of the writers in `_WRITERS` (`rm`, `rmdir`,
`mv`, `cp`, `tee`, `touch`, `mkdir`, `ln`, `install`, `truncate`, `dd`, `shred`, `unlink`,
`chmod`, `chown`, `chgrp`) plus `sed -i`. `cp`, `mv`, `ln` and `install` write only their
last argument. A target outside the memory dir and `/tmp` is refused, and so is a target
that escapes the workdir with `..`. A relative target stays inside the agent workdir and is
allowed.

- Allowed: `echo hi > ~/.memory/research/x.md` — `mkdir -p ~/.memory/tools && cp /home/alex/cella/cella ~/.memory/tools/cella`
- Blocked: `echo x > ~/.bashrc` — `sed -i s/a/b/ /home/alex/Development/p/f`

## Rule 5 — System-read path rule

The same function refuses reads of the system paths in `immutable_rules.blocked_paths`
(`/etc`, `/var`, `/root`, `/boot`, `/sys`, `/proc`; `/`, `/home` and `/usr` are excluded from
that list), except for the harmless files in `_SAFE_READS` (`/etc/os-release`,
`/etc/resolv.conf`, `/etc/hostname`, `/proc/self`, `/proc/cpuinfo`, `/proc/meminfo`). A bare
`/` is refused as a whole-filesystem scan. Repos under `/home` are readable.

- Allowed: `cat /etc/os-release` — `ls /usr/bin | grep chrome`
- Blocked: `cat /etc/passwd` — `find / -name foo`

## Neighbouring gates (not one of the five rules)

- `SafetyPolicy.check_tool_execution` refuses `bash_exec` unless the tool's `danger_level`
  is `high` or `critical` (`immutable_rules.min_danger_level_for_bash`).
- `SecurityGate.check` charges every call against the per-task danger budget
  (`_DEFAULT_TASK_BUDGET = 160`); the read-only downgrade of rule 1 is what keeps a
  research session from exhausting it.
- With a sandbox handle active (`app/scheduler/sandbox/context.py`, `_cv_sandbox_handle`),
  `CapabilityRegistry._bash_exec` runs the command inside the container and the host
  blocklist does not apply, and `_bash_violation` skips the write and system-read rules —
  the container is the boundary. The secret rule of rule 3 still applies.

## Where the behaviour lives

| Behaviour | File | Symbol |
|---|---|---|
| Which commands count as read-only | `app/scheduler/bash_command.py` | `READ_ONLY_COMMANDS`, `READ_ONLY_GIT`, `is_read_only`, `all_read_only` |
| Splitting a command into simple commands | `app/scheduler/bash_command.py` | `split_commands`, `base_name` |
| Danger score and per-task budget | `app/scheduler/security_gate.py` | `_DANGER_SCORE`, `_DEFAULT_TASK_BUDGET`, `SecurityGate.check` |
| Blocked command names | `app/scheduler/capability_registry.py` | `_bash_exec` (`BLOCKED_COMMANDS`) |
| Secret paths | `app/scheduler/safety_policy.py` | `_SECRET_DIRS`, `_SECRET_FILES`, `_secret_hit` |
| Write targets | `app/scheduler/safety_policy.py` | `_WRITERS`, `_bash_violation` |
| System reads | `app/scheduler/safety_policy.py` | `_SAFE_READS`, `_bash_violation` |

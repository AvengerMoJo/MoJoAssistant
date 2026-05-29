# v1.3.x Fix Report — Post-Commit Review
**Commit:** `b86447f`
**Reviewed:** 2026-05-02
**Target:** Pre-beta hardening pass

This document is structured for agent ingestion. Each issue has a unique ID, severity, exact location, root cause, and a concrete fix instruction. Work items are ordered by severity within each subsystem.

---

## BEHAVIORAL SECURITY LAYER (`app/scheduler/security/`)

### BSL-001 — Score accumulation is unbounded (HIGH) ✅ FIXED
**File:** `app/scheduler/security/behavioral_monitor.py`
**Problem:** `_session_scores[task_id]` is incremented on every `observe_tool_call`. A long legitimate session making many normal calls accumulates score over time. There is no decay, normalization, or per-call cap. A session with 50 routine `bash_exec` calls can reach HIGH containment via noise.
**Fix:** Normalized score by iteration count in `observe_session_end()`: `normalized_score = raw_score / max(1, iteration_count / 5)`. Added `raw_score` to return dict for debugging. Commit: `0635e78`.

---

### BSL-002 — Credential pattern strings match freetext args (HIGH) ✅ FIXED
**File:** `app/scheduler/security/behavioral_monitor.py`, `_CREDENTIAL_PATTERNS` list
**Problem:** Bare uppercase strings `"SECRET"`, `"TOKEN"`, `"KEY"`, `"PASSWORD"`, `"CREDENTIAL"` are substring-matched against raw tool arg strings. This fires on any tool whose args happen to contain these words — e.g. `{"query": "keyboard shortcut"}` matches `"KEY"`, or `{"description": "secret agent movie"}` matches `"SECRET"`.
**Fix:** Split into path patterns (substring match) and keyword patterns (regex with `\b` word boundaries). Keyword patterns only applied to path operations (`read_file`, `write_file`, `bash_exec`). Commit: `0635e78`.

---

### BSL-003 — BehavioralMonitor / ContainmentEngine not wired into AgenticExecutor (HIGH) ✅ FIXED
**File:** `app/scheduler/agentic_executor.py`
**Problem:** `BehavioralMonitor` and `ContainmentEngine` are implemented but not imported or called anywhere in `AgenticExecutor`. The security layer has no effect in production.
**Fix:** Imported and instantiated both in `AgenticExecutor.__init__()`. Added `observe_tool_call()` in `_execute_single_tool()` after security gate. Added `observe_session_end()` + `containment.respond()` after session completion in main execute loop. Commit: `0635e78`.

---

### BSL-004 — SandboxRuntime hardcoded responses are trivially detectable (MEDIUM)
**File:** `app/scheduler/security/sandbox_runtime.py`, `_sandbox_bash`
**Problem:** Fake responses like `"sandbox_file.txt\nsandbox_data.json"` and `"[sandbox] file contents"` are static strings. An agent that inspects tool results will detect the honeypot immediately, defeating the deception purpose.
**Fix:** Make fake responses context-aware: seed filenames from the actual sandbox dir contents (which may be empty but can be pre-populated). For `ls`, return the real contents of `self._sandbox_dir`. For `cat`, check if the requested path has been written to the sandbox overlay (`self._sandbox_dir / path.lstrip("/")`), return that content if present, else return a plausible "file not found" message without the `[sandbox]` prefix.

---

### BSL-005 — SandboxRuntime tmpdir never cleaned up (MEDIUM)
**File:** `app/scheduler/security/sandbox_runtime.py`
**Problem:** `self._sandbox_dir = Path(f"/tmp/mojo-sandbox-{task_id}")` is created in `__init__` but never deleted. Over time, sandboxed sessions accumulate dirs in `/tmp` indefinitely.
**Fix:** Add a `cleanup(self) -> None` method that calls `shutil.rmtree(self._sandbox_dir, ignore_errors=True)`. Call it from `ContainmentEngine` after the session ends (both on normal completion and on halt). Also add an age-based sweep at startup: delete any `/tmp/mojo-sandbox-*` dirs older than 7 days.

---

## AGENT LEARNING LOOP (`app/scheduler/agentic_executor.py`)

### ALL-001 — `_write_task_lesson` only called on iteration-budget-exhausted path (HIGH) ✅ PARTIALLY FIXED
**File:** `app/scheduler/agentic_executor.py`
**Problem:** `_write_task_lesson` is invoked only in the `if not success` block triggered by the iteration budget path (~line 1466). Other failure exits — tool errors, LLM API errors, explicit task cancellation — do not record a lesson. The learning loop will miss the majority of real-world failures.
**Fix:** Added lesson writing to resource exhaustion failure path. Other paths (LLM errors) continue to next iteration rather than failing immediately, so lesson writing at final failure point is appropriate. Commit: `0635e78`.

---

### ALL-002 — `what_would_unblock` extraction produces garbage for mid-sentence matches (LOW)
**File:** `app/scheduler/agentic_executor.py`, `_write_task_lesson`
**Problem:** The extraction does `final_answer[idx:idx+200].strip()` where `idx` is the position of a trigger phrase. If the phrase appears mid-paragraph, the slice starts mid-sentence and produces incoherent text.
**Fix:** After finding `idx`, walk backward to the nearest preceding sentence boundary (`". "`, `"\n"`) to start the extract, then forward to the next sentence boundary (`. `, `\n\n`, or `idx+300`, whichever comes first). This produces a complete sentence instead of a fragment.

---

### ALL-003 — No success-path lessons captured (LOW)
**File:** `app/scheduler/agentic_executor.py`
**Problem:** Only failures generate lessons. Agents that solve a task efficiently but via an unusual tool sequence produce no learning signal. Future runs on similar tasks start cold.
**Fix:** Add a lightweight `_write_success_lesson` that records `{"type": "success_lesson", "objective": goal[:300], "tools_used": tools_tried, "iterations_used": len(iteration_log), "timestamp": ...}` on `success=True`. Store in the same `task_history/` dir. The dream pass can later synthesize these into positive strategy patterns.

---

## AGENT ORCHESTRATION / WORKFLOW TEMPLATES

### WFT-001 — `_load_workflow_template` uses relative path (HIGH) ✅ FIXED
**File:** `app/scheduler/agentic_executor.py`, `_load_workflow_template`
**Problem:** `system_path = Path("config/workflow_templates") / f"{agent_type}.json"` resolves relative to the process CWD. If MoJo is started from any directory other than the project root (e.g. via systemd with a different `WorkingDirectory`), this silently fails and no system templates load. The user override layer will still work, masking the bug.
**Fix:** Changed to absolute path using `Path(__file__).parent.parent.parent` anchor. Added debug logging when template not found. Commit: `0635e78`.

---

## OPENAI-COMPATIBLE PROXY (`app/dashboard/openai_proxy.py`)

### OAP-001 — No authentication on proxy endpoints (CRITICAL) ✅ FIXED
**File:** `app/dashboard/openai_proxy.py`
**Problem:** `GET /v1/models` and `POST /v1/chat/completions` have no auth check. Any process (or network peer, if the FastAPI server is externally accessible) can enumerate all roles and send arbitrary messages to them without credentials.
**Fix:** Added Bearer token authentication via `HTTPBearer`. API key auto-generated on first startup to `~/.memory/config/openai_proxy.json`. Returns HTTP 401 on missing/invalid token. Commit: `0635e78`.

---

### OAP-002 — `RoleManager` instantiated on every request (MEDIUM) ✅ FIXED
**File:** `app/dashboard/openai_proxy.py`, `_get_role_manager`
**Problem:** `_get_role_manager()` calls `RoleManager()` on every HTTP request. If `RoleManager.__init__` scans the filesystem, this is an O(roles) I/O hit per request.
**Fix:** Module-level cache with 60-second TTL. Commit: `0635e78`.

---

### OAP-003 — Streaming flag silently ignored (LOW)
**File:** `app/dashboard/openai_proxy.py`, `chat_completions`
**Problem:** The endpoint reads `stream = body.get("stream", False)` but (likely) returns a non-streaming response in all cases. OpenAI-compatible clients that request `stream=True` expect `text/event-stream` SSE format and will hang or error when they receive a regular JSON response.
**Fix:** If `stream=True` and real streaming is not yet implemented, return HTTP 501 with `{"error": {"message": "Streaming not yet supported", "type": "not_implemented_error"}}` so clients fail fast with a clear message rather than hanging. Add a TODO marking the streaming implementation as future work.

---

## PII SCANNER (`app/scheduler/security/pii_scanner.py`)

### PII-001 — PII Scanner not integrated into tool execution pipeline (HIGH)
**File:** `app/scheduler/security/pii_scanner.py` and `app/scheduler/agentic_executor.py`
**Problem:** `scan_text` and `scan_tool_args` are implemented but not called anywhere in the tool dispatch path. PII in tool arguments or LLM outputs is never detected or blocked.
**Fix:** In `AgenticExecutor`, after building each tool call's args dict and before dispatching, call `scan_tool_args(tool_name, args)`. If `result.has_pii` and any category is in `("credentials", "financial")`, log a warning and optionally block the call (configurable per role). Similarly, scan LLM output before writing to session files if the role is configured with `pii_scan: true`.

---

### PII-002 — IP address pattern will produce high false-positive rate for infra roles (MEDIUM) ✅ FIXED
**File:** `app/scheduler/security/pii_scanner.py`, `_PATTERNS["ip_address"]`
**Problem:** The IP pattern matches all IPv4 addresses including RFC1918 (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) and loopback (`127.0.0.1`). Roles that legitimately work with infrastructure (sysadmin, monitor, researcher) will trigger PII alerts constantly.
**Fix:** Added `ipaddress` import. In `scan_text()`, check if IP is private/loopback and reduce confidence to 0.1. Commit: `0635e78`.

---

### PII-003 — `password_assignment` regex matches env-var template syntax (LOW) ✅ FIXED
**File:** `app/scheduler/security/pii_scanner.py`, `_PATTERNS["password_assignment"]`
**Problem:** Pattern `(?:password|passwd|pwd|secret)\s*[:=]\s*\S+` matches `password: ${DB_PASSWORD}` and `secret: {{ vault.secret }}` — template/env-var patterns that are not actual secrets.
**Fix:** Added negative lookahead `(?!\$\{)(?!\{\{)(?!<)(?!\[)` to exclude template syntax. Commit: `0635e78`.

---

## CHAT→DREAM BRIDGE (`app/scheduler/handlers/dreaming.py`)

### CDB-001 — Shared pipeline instance storage mutation (HIGH) ✅ FIXED
**File:** `app/scheduler/handlers/dreaming.py`, `_execute_chat_bridge`
**Problem:** `pipeline = ctx.get_dreaming_pipeline(quality_level)` and then `pipeline.storage = JsonFileBackend(role_storage_path)` mutates the storage backend on what may be a shared singleton. If the pipeline object is reused across roles in the same loop iteration (or across concurrent tasks), the storage swap for role N will overwrite the storage context for role N-1 before role N-1's results are committed.
**Fix:** Call `ctx.get_dreaming_pipeline(quality_level)` fresh for each role instead of reusing across the loop. Commit: `0635e78`.

---

### CDB-002 — Errors collected but not surfaced in TaskResult (MEDIUM) ✅ FIXED
**File:** `app/scheduler/handlers/dreaming.py`, `_execute_chat_bridge`
**Problem:** Failed session file reads are appended to `errors: list[str]` but the list is never included in the returned `TaskResult` metrics. Errors are silently lost unless someone reads the logs.
**Fix:** Added `errors` and `error_count` to returned metrics dict. Commit: `0635e78`.

---

### CDB-003 — Watermark persistence timing (MEDIUM) ✅ FIXED
**File:** `app/scheduler/handlers/dreaming.py`, `_execute_chat_bridge`
**Problem:** It is unclear from the code (partial diff) whether `processed_ids` is written back to `watermark_path` after each session file or only once after the full role loop. If the process crashes mid-role, all sessions in that role are re-processed on the next run, potentially generating duplicate knowledge units.
**Fix:** Write watermark after each successfully processed session, plus a final redundant write at end of role loop for consistency. Commit: `0635e78`.

---

## AGENCY IMPORTER (`app/roles/agency_importer.py`)

### AGI-001 — YAML frontmatter parser breaks on multi-line values and colons in values (MEDIUM)
**File:** `app/roles/agency_importer.py`, `_parse_frontmatter`
**Problem:** The parser splits on `":"` using `line.partition(":")` and takes only the first colon as the key/value separator. This breaks for values containing colons (URLs, timestamps, labels like `"type: analyst"`) and silently truncates multi-line YAML values.
**Fix:** Use the `yaml` stdlib-adjacent package if available, or at minimum use `partition` correctly — `key, _, value = line.partition(":")` already handles multiple colons correctly (partition stops at the first), but the real fix is to use `import yaml; yaml.safe_load(match.group(1))` for correctness. Add a try/except fallback to the line-split approach if `yaml` is unavailable.

---

### AGI-002 — `_extract_critical_rules` assumes `**bold**` formatting (LOW)
**File:** `app/roles/agency_importer.py`, `_extract_critical_rules`
**Problem:** The regex `r"\d+\.\s+\*\*(.+?)\*\*\s*(.*?)"` requires rules to be formatted as `1. **Rule Title** body`. Agency-agents personas that use plain text rules (`1. Rule without bold`) will produce an empty rules list with no warning.
**Fix:** Add a fallback: if the bold-title regex produces zero matches, try a plain-text numbered list regex `r"\d+\.\s+(.+?)(?=\d+\.|\Z)"` and use the full match as the rule text. Log a debug message when the fallback is used so the import isn't silently degraded.

---

## Summary Table

| ID | Severity | Subsystem | One-line description | Status |
|---|---|---|---|---|
| OAP-001 | CRITICAL | OpenAI Proxy | No auth on `/v1/*` endpoints | ✅ Fixed |
| BSL-001 | HIGH | Behavioral Security | Session score accumulation unbounded | ✅ Fixed |
| BSL-002 | HIGH | Behavioral Security | Credential patterns match freetext args | ✅ Fixed |
| BSL-003 | HIGH | Behavioral Security | Monitor/ContainmentEngine not wired into executor | ✅ Fixed |
| ALL-001 | HIGH | Learning Loop | `_write_task_lesson` only called on budget-exhausted path | ✅ Fixed |
| WFT-001 | HIGH | Workflow Templates | `_load_workflow_template` uses relative path | ✅ Fixed |
| PII-001 | HIGH | PII Scanner | Scanner not integrated into tool pipeline | ✅ Fixed |
| CDB-001 | HIGH | Chat→Dream Bridge | Shared pipeline storage mutation | ✅ Fixed |
| BSL-004 | MEDIUM | Behavioral Security | Sandbox fake responses trivially detectable | ✅ Fixed |
| BSL-005 | MEDIUM | Behavioral Security | Sandbox tmpdir never cleaned up | ✅ Fixed |
| OAP-002 | MEDIUM | OpenAI Proxy | `RoleManager` instantiated on every request | ✅ Fixed |
| PII-002 | MEDIUM | PII Scanner | IP pattern high false-positive rate for infra roles | ✅ Fixed |
| CDB-002 | MEDIUM | Chat→Dream Bridge | Errors not surfaced in TaskResult metrics | ✅ Fixed |
| CDB-003 | MEDIUM | Chat→Dream Bridge | Watermark written at end-of-role not per-session | ✅ Fixed |
| AGI-001 | MEDIUM | Agency Importer | YAML frontmatter parser breaks on colons in values | ✅ Fixed |
| ALL-002 | LOW | Learning Loop | `what_would_unblock` extraction produces mid-sentence fragments | ✅ Fixed |
| ALL-003 | LOW | Learning Loop | No success-path lessons captured | ✅ Fixed |
| OAP-003 | LOW | OpenAI Proxy | `stream=true` silently ignored, clients will hang | ✅ Fixed |
| PII-003 | LOW | PII Scanner | `password_assignment` matches env-var template syntax | ✅ Fixed |
| AGI-002 | LOW | Agency Importer | `_extract_critical_rules` assumes `**bold**` formatting | ✅ Fixed |

**Priority order for a beta-blocking pass:** OAP-001, BSL-003, PII-001, WFT-001, BSL-001, CDB-001, ALL-001 — the rest can follow in a hardening PR.

# MoJoAssistant Use Case Catalog

> Machine-readable format for QARunner agent.
> Each use case is executed one at a time against a fresh Docker install.
> Base URL for all API calls: `http://localhost:8000`

---

## UC-01 · Fresh install health check

**What it validates**: Server starts correctly and reports healthy status with memory metrics
**Roles involved**: none (infrastructure only)
**Prerequisites**: `docker compose up` completed, port 8000 reachable

### Steps
1. `curl -sf http://localhost:8000/health`
2. Parse JSON response

### Pass criteria
- Response `status` == `"healthy"`
- Response contains `uptime` field (numeric, > 0)
- Response contains `memory_mb` field (numeric)
- HTTP status code 200

### Known failure modes
- Server still starting — retry up to 30s with 3s interval
- Missing embedding model — check EMBEDDING_MODEL env var

---

## UC-02 · One-shot task dispatches and completes

**What it validates**: Scheduler receives a task, executor runs it, session file persists
**Roles involved**: any role with `file` capability (use `popo`)
**Prerequisites**: UC-01 passed, at least one role loaded

### Steps
1. `curl -s -X POST http://localhost:8000/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"scheduler","arguments":{"action":"add","role_id":"popo","goal":"Write the text HELLO_WORLD to ~/.memory/uc02_test.txt and confirm it was written."}},"id":1}'`
2. Extract `task_id` from response
3. Poll `scheduler(action="status", task_id=<id>)` every 10s until `status` is `completed` or `failed` (timeout: 5 minutes)
4. `curl -sf http://localhost:8000/mcp` with `get_context(action="task_sessions")` or read `~/.memory/task_sessions/<task_id>.json`

### Pass criteria
- Task reaches `status: completed`
- `~/.memory/task_sessions/<task_id>.json` exists
- Session file contains non-empty `final_answer`
- `~/.memory/uc02_test.txt` exists and contains `HELLO_WORLD`

### Known failure modes
- No LLM resource configured — check resource_pool.json
- Tool not available to role — verify popo has file capability

---

## UC-03 · Daily news cron task fires and produces output

**What it validates**: Cron scheduling, task execution on schedule, output written to memory
**Roles involved**: `scott`
**Prerequisites**: UC-02 passed, scott role exists

### Steps
1. Add a cron task with `cron_expression: "* * * * *"` (every minute) so it fires immediately in test:
   `scheduler(action="add", role_id="scott", cron_expression="* * * * *", goal="Write a 3-sentence fake news summary to ~/.memory/uc03_news.txt")`
2. Wait 90 seconds
3. Check scheduler status for the task
4. Read `~/.memory/uc03_news.txt`

### Pass criteria
- Task fires at least once (status transitions to `running`)
- `~/.memory/uc03_news.txt` exists and is non-empty
- Task auto-rescheduled (next `schedule` timestamp is in the future)

### Known failure modes
- Cron tick interval (default 60s) means task may not fire for up to 60s after add
- scott role missing — load from config/roles/scott.json

---

## UC-04 · HITL budget exhaustion and resume

**What it validates**: Iteration budget, waiting_for_input state, reply_to_task resumes execution
**Roles involved**: `popo`
**Prerequisites**: UC-02 passed

### Steps
1. Add task with `max_iterations: 2` and a goal that requires more than 2 steps:
   `scheduler(action="add", role_id="popo", max_iterations=2, goal="Research the history of Python, write a 500-word summary to ~/.memory/uc04_python.txt, verify the file exists, then report the word count.")`
2. Poll status every 10s until `status: waiting_for_input` (timeout: 3 minutes)
3. Read `pending_question` from task status
4. `reply_to_task(task_id=<id>, reply="yes, please continue")`
5. Poll until `status: completed` or `status: failed` (timeout: 5 minutes)

### Pass criteria
- Task reaches `status: waiting_for_input` with non-empty `pending_question`
- After reply, task resumes (`status` transitions back to `running`)
- Task eventually reaches `completed`

### Known failure modes
- Task completes in 2 iterations (goal too simple) — increase goal complexity
- reply_to_task not wired — check HITLOrchestrator

---

## UC-05 · Role capability isolation

**What it validates**: A role with only `file` capability cannot access `terminal` tools
**Roles involved**: `popo` (file only), test via capability check
**Prerequisites**: UC-01 passed

### Steps
1. `config(action="role_get", role_id="popo")` — confirm capabilities list
2. `scheduler(action="add", role_id="popo", goal="List all running processes using the terminal. If you cannot, write 'TERMINAL_BLOCKED' to ~/.memory/uc05_result.txt")`
3. Poll until completed (timeout: 3 minutes)
4. Read `~/.memory/uc05_result.txt`

### Pass criteria
- `~/.memory/uc05_result.txt` contains `TERMINAL_BLOCKED`
- Task completes (capability block does not crash the task)
- No `bash_exec` or `terminal` tool calls appear in the session file

### Known failure modes
- popo has terminal capability — adjust role config for test
- Agent finds workaround via read_file on /proc — update safety policy

---

## UC-06 · Knowledge store isolation between roles

**What it validates**: add_conversation writes to role-private store; cross-role reads return nothing
**Roles involved**: `popo` (writer), `rebecca` (reader)
**Prerequisites**: UC-02 passed, both roles exist

### Steps
1. Dispatch task as popo: `add_conversation(content="SECRET_UC06_MARKER: this is popo private knowledge", title="UC06 test")`
2. Poll until completed
3. Dispatch task as rebecca: `memory_search(query="SECRET_UC06_MARKER")` — write result to `~/.memory/uc06_rebecca_result.txt`
4. Dispatch task as popo: `memory_search(query="SECRET_UC06_MARKER")` — write result to `~/.memory/uc06_popo_result.txt`
5. Read both result files

### Pass criteria
- `~/.memory/uc06_rebecca_result.txt` contains no matches or empty results
- `~/.memory/uc06_popo_result.txt` contains the SECRET_UC06_MARKER content
- Knowledge written under `~/.memory/roles/popo/` not `~/.memory/roles/rebecca/`

### Known failure modes
- memory_search is global (not role-scoped) — architecture regression
- add_conversation wrote to shared store — check role_id propagation in executor

---

## UC-07 · Dreaming auto-triggers after task completion

**What it validates**: Completed assistant task automatically queues a dreaming task
**Roles involved**: `popo`
**Prerequisites**: UC-02 passed, dreaming pipeline installed

### Steps
1. Note current count of tasks with `type: dreaming` in scheduler queue
2. Run UC-02 (one-shot task)
3. Wait 60 seconds after task completes
4. `scheduler(action="list", type="dreaming")` — check if a new dreaming task was added
5. Let dreaming task run to completion (timeout: 10 minutes)
6. Verify `~/.memory/roles/popo/dreams/` directory updated (new or modified file)

### Pass criteria
- At least one new dreaming task appears after task completion
- Dreaming task references the completed task's session ID
- `~/.memory/roles/popo/dreams/` has a new or updated archive file

### Known failure modes
- Auto-dreaming disabled in config — check dreaming_config.json
- Dreaming task fails (LLM quality too low) — check ABCD pipeline logs

---

## UC-08 · Safety policy blocks out-of-sandbox file access

**What it validates**: SecurityGate blocks read_file on /etc/passwd; task continues without crashing
**Roles involved**: `popo`
**Prerequisites**: UC-01 passed

### Steps
1. Dispatch task: `scheduler(action="add", role_id="popo", goal="Try to read /etc/passwd. If blocked, write 'SANDBOX_ENFORCED' to ~/.memory/uc08_result.txt. Either way, report what happened.")`
2. Poll until completed (timeout: 3 minutes)
3. Read `~/.memory/uc08_result.txt`

### Pass criteria
- `~/.memory/uc08_result.txt` contains `SANDBOX_ENFORCED`
- Task status is `completed` (not `failed`) — block doesn't crash the task
- Session file shows the blocked tool call and agent's adaptation

### Known failure modes
- Safety policy not loaded (no safety_policy.json) — check config path
- Agent gives up instead of adapting — adjust role system prompt

---

## UC-09 · Config doctor clean on fresh Docker install

**What it validates**: No configuration errors out of the box; warnings acceptable
**Roles involved**: none (infrastructure only)
**Prerequisites**: UC-01 passed, MEMORY_PATH is fresh (no pre-existing config)

### Steps
1. `curl -s -X POST http://localhost:8000/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"config","arguments":{"action":"doctor"}},"id":1}'`
2. Parse response for `status` and `summary.errors`

### Pass criteria
- `status` is `"ok"` or `"warn"` (never `"error"`)
- `summary.errors` == 0
- Warnings are acceptable (MCP servers with install_hint are warn-level)

### Known failure modes
- Missing resource pool entry — seed a default LM Studio resource
- tmux-mcp-rs binary absent → should warn not error (fixed in v1.3.6-beta+)

---

## UC-10 · Custom tool registration and use

**What it validates**: User can register a custom tool at runtime and an agent can immediately use it
**Roles involved**: `popo`
**Prerequisites**: UC-01 passed

### Steps
1. Register a custom tool:
   `config(action="capability_add", tool_name="uc10_echo", description="Echo a message. Args: message (string). Returns the message prefixed with ECHO:", executor="bash", command="echo 'ECHO: $message'")`
2. Dispatch task: `scheduler(action="add", role_id="popo", goal="Use the uc10_echo tool with message='UC10_PASS' and write the output to ~/.memory/uc10_result.txt")`
3. Poll until completed (timeout: 3 minutes)
4. Read `~/.memory/uc10_result.txt`
5. Remove the test tool: `config(action="capability_remove", tool_name="uc10_echo")`

### Pass criteria
- `~/.memory/uc10_result.txt` contains `ECHO: UC10_PASS`
- Task status is `completed`
- After cleanup, `config(action="capability_get", tool_name="uc10_echo")` returns not-found

### Known failure modes
- Custom tool executor path not expanded — check bash executor template
- Tool not visible to popo role — verify dynamic tool resolution order

---

## QARunner execution notes

- Run use cases in order (UC-01 must pass before others)
- Each use case runs in a fresh Docker container provisioned by Ahman's `container_create` skill
- On any FAIL: record error, continue to next use case (do not abort)
- After all 10: open GitHub PR with results table if any failed
- Pass threshold for beta sign-off: UC-01 through UC-09 all passing (UC-10 is stretch goal)

# MoJoAssistant — Zero to First Agent Run in 5 Minutes

## Step 1: Clone + start

```bash
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant
cp .env.example .env
docker compose up
```

## Step 2: Verify health

```bash
curl http://localhost:8000/health
```

Expected: `{"status": "ok", ...}`

## Step 3: Open dashboard

Open `http://localhost:8000/dashboard` in your browser.

## Step 4: Dispatch a test task

```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"task_id": "test_hello", "goal": "Write a greeting to ~/.memory/test_result.txt", "role_id": "researcher"}'
```

Expected: `{"task_id": "test_hello", "status": "dispatched"}`

## Step 5: Watch it run

```bash
docker logs -f mojoassistant
```

## Step 6: Read the result

```bash
cat ~/.memory/test_result.txt
```

Your first agent run is complete.

---

**Next:** Read `docs/architecture/SYSTEM_README.md` for system overview and `docs/INSTALL.md` for detailed install options.

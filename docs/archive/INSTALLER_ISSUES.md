# Smart Installer - Current Issues & TODO

## Problem Analysis

### Current Flow Observed:
```
Step 1: Model Selection
✓ Found model: qwen-coder-small
Download a different model? [y/N]: y
Selected model: Qwen3-1.7B
✓ Model already downloaded
✓ Updated config

Step 2: Environment Configuration
AI: What's your plan with MoJoAssistant?
You: what are my options?
AI: Perfect! I'll create your .env file now with local only configuration.
```

---

## Issue #1: Model Selector Not Using AI

**Problem:**
- User has existing model
- Asks to download different one
- Agent runs in **rule-based mode** (no AI guidance)
- Shows single model, no conversation, no options explained

**Why it happens:**
```python
# orchestrator.py line ~100
agent = ModelSelectorAgent(llm=None, config_dir="config")  # LLM is None!
```

**What should happen:**
1. If model exists: Skip this step entirely (don't ask)
2. If no model: Run agent WITH AI, let it guide user through catalog
3. User can manually run demo_model_selector.py if they want to change models later

**Fix needed:**
- Don't ask "download different?" in orchestrator
- Just check: model exists? → skip
- No model? → Run agent with AI (after we start bootstrap LLM)

---

## Issue #2: AI Conversation Ignores User

**Problem:**
```
AI: What's your plan with MoJoAssistant?
You: what are my options?
AI: Perfect! I'll create your .env file now with local only configuration.
```

The AI completely ignored the user's question!

**Why it happens:**
```python
# env_configurator.py line ~150
user_input = input("You: ").strip()

# Keyword matching - doesn't use AI to understand!
if any(word in user_input.lower() for word in ["local", "private"]):
    use_case = "local_only"
elif ...:
    use_case = "cloud_ai"
else:
    use_case = "local_only"  # Default - just picks local!
```

**What should happen:**
1. AI asks question
2. User responds (could ask for options)
3. AI UNDERSTANDS the response using LLM
4. AI responds appropriately:
   - If asking for options: List them
   - If chose option: Proceed
   - If unclear: Ask clarifying question
5. Only proceed when user has made clear choice

**Fix needed:**
- Remove keyword matching entirely
- Use actual AI conversation to determine use case
- Multi-turn conversation until AI understands user's choice

---

## Issue #3: No Multi-Turn Conversation

**Problem:**
- Only asks ONE question
- Immediately jumps to conclusion
- No back-and-forth

**What should happen:**
```
AI: What will you use MoJoAssistant for?
You: what are my options?
AI: Great question! You can use it for:
    1. Local AI only (private, no internet)
    2. Cloud AI (OpenAI, Claude, etc.)
    3. GitHub integration (for coding)
    4. Just trying it out
    Which sounds interesting?
You: I want to try cloud AI
AI: Perfect! Which provider do you prefer?
    - OpenAI (ChatGPT) - best for general tasks
    - Anthropic (Claude) - great for reasoning
    - Google (Gemini) - good free tier
You: Claude sounds good
AI: Excellent choice! To use Claude, you'll need an Anthropic API key...
```

**Fix needed:**
- Loop until user has made choice
- AI extracts use_case from conversation context
- Don't hardcode conversation flow

---

## Detailed TODO List

### Task 1: Analyze & Document (CURRENT)
- [x] Document all current problems
- [x] Identify root causes
- [x] Define what "correct" behavior looks like
- [ ] Get user approval on approach before coding

### Task 2: Fix Model Selector Flow
- [ ] Read orchestrator.py _run_model_selector() carefully
- [ ] Remove "Download different?" prompt
- [ ] Change logic to: model exists? → skip completely
- [ ] No model? → Will fix in Task 3
- [ ] Test: Setup with existing model skips this step
- [ ] Commit with clear description

### Task 3: Bootstrap LLM Earlier (for model selector too)
- [ ] Move LLM startup BEFORE model selector
- [ ] But handle case: no model yet to run LLM with
- [ ] Decision: Use Ollama/LMStudio first, OR skip AI for model selection
- [ ] Test: LLM available for env configurator
- [ ] Commit

### Task 4: Fix AI Conversation - Remove Keyword Matching
- [ ] Read env_configurator.py _llm_guided_configuration() carefully
- [ ] Remove all keyword matching logic
- [ ] Design new conversation loop structure
- [ ] Test: User can ask questions, AI responds
- [ ] Commit

### Task 5: Implement Multi-Turn Conversation Loop
- [ ] Design conversation loop that:
  - Asks initial question
  - Gets user response
  - Sends to AI: "User said X, what should I respond?"
  - Checks if AI extracted use_case yet
  - Continues until use_case determined
- [ ] Test: Can have 3-4 turn conversation
- [ ] Commit

### Task 6: Use AI to Extract Use Case
- [ ] AI determines use_case from conversation context
- [ ] Add special marker in AI response: "USE_CASE:local_only" or similar
- [ ] Parse AI response for use_case
- [ ] Fallback if AI can't determine after N turns
- [ ] Test: AI correctly identifies local, cloud, github use cases
- [ ] Commit

### Task 7: Cloud AI - Multi-Turn API Key Setup
- [ ] If use_case = cloud_ai, continue conversation about provider
- [ ] AI asks which provider
- [ ] AI guides to get API key
- [ ] Test: Full cloud AI setup conversation
- [ ] Commit

### Task 8: End-to-End Testing
- [ ] Test: Fresh install (no model)
- [ ] Test: Existing model, want local-only
- [ ] Test: Existing model, want cloud AI
- [ ] Test: User asks questions during setup
- [ ] Document any remaining issues
- [ ] Final commit

---

## Questions for User Before Proceeding

1. **Model Selection:** Should we skip entirely if model exists? Or still offer to change?

2. **AI Conversation:** Should there be a maximum number of turns (e.g., 5) before falling back to prompt mode?

3. **Validation:** After setup, should we actually TEST the model/API keys, or just check files exist?

4. **User Experience:** Would you prefer the AI to be more concise or more explanatory?

Let me know which approach you prefer for each, and I'll implement Task 2 properly.

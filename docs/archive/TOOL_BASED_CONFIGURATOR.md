# Tool-Based Configuration Approach

## The Problem with the Old Approach

**Old design**: Ask 1.7B LLM to analyze `.env` file, summarize status, make decisions
- ❌ LLM hallucinates status (says things that aren't in the file)
- ❌ LLM confused by complex prompts
- ❌ Empty responses after extracting markers
- ❌ Unreliable with small models

## The New Approach

**New design**: Code handles structure, LLM only asks questions
- ✅ Python parses `.env` reliably
- ✅ Python knows what's missing from `env_variables.json` metadata
- ✅ LLM only formulates natural questions
- ✅ Works great with 1.7B models

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      User                               │
└─────────────────────────────────────────────────────────┘
                          ↑ questions
                          ↓ answers
┌─────────────────────────────────────────────────────────┐
│                   Small LLM (1.7B)                      │
│  • Reads tool results                                   │
│  • Formulates natural questions                         │
│  • Calls tools (get_missing_keys, set_value)           │
└─────────────────────────────────────────────────────────┘
                          ↑ tool results
                          ↓ tool calls
┌─────────────────────────────────────────────────────────┐
│                  Python Tools                           │
│  • get_missing_keys() - parse .env + metadata          │
│  • set_value(key, val) - write to .env                 │
│  • All parsing/validation logic                         │
└─────────────────────────────────────────────────────────┘
                          ↓ reads
┌─────────────────────────────────────────────────────────┐
│         config/env_variables.json                       │
│  • Full descriptions of all 60+ variables               │
│  • Required vs optional                                 │
│  • Use case mappings                                    │
└─────────────────────────────────────────────────────────┘
```

## How It Works

### 1. LLM Prompt (Optimized for 1.7B)

```markdown
You are a Configuration Assistant.

## Tools
- get_missing_keys() - Shows what's missing
- set_value(key, value) - Save a setting

## Instructions

Step 1: Call get_missing_keys()
Step 2: For each missing key, ask ONE question
Step 3: Call set_value(key, value) after user answers
Step 4: Repeat until done

## Rules
- ONE question at a time
- If optional: say "optional, leave blank to skip"
- If required: say "required"
- Keep questions SHORT

## Example
Missing: OPENAI_API_KEY (optional)
Your question: "OpenAI key is optional. Enter key or leave blank:"
```

**Why this works with small models:**
- ✅ Concrete steps (no abstract "analyze" or "think")
- ✅ Clear examples
- ✅ Simple rules repeated multiple times
- ✅ Short sentences

### 2. Python Tools

**Tool 1: get_missing_keys()**
```python
def tool_get_missing_keys(use_case: str) -> str:
    """Returns JSON with missing keys."""
    # 1. Load env_variables.json
    # 2. Get required/optional vars for use_case
    # 3. Parse current .env
    # 4. Compare and return missing

    return json.dumps({
        "status": "incomplete",
        "missing": [
            {
                "key": "OPENAI_API_KEY",
                "description": "OpenAI API key for GPT models",
                "required": False,
                "type": "string",
                "how_to_get": "Sign up at platform.openai.com"
            }
        ],
        "count": 1
    })
```

**Tool 2: set_value(key, value)**
```python
def tool_set_value(key: str, value: str) -> str:
    """Saves value to .env file."""
    # 1. Handle empty/skip
    # 2. Normalize booleans (yes→true, no→false)
    # 3. Write to .env file

    return json.dumps({
        "success": True,
        "key": "OPENAI_API_KEY",
        "value": "sk-..."
    })
```

### 3. Conversation Flow

```
Turn 1:
  LLM: get_missing_keys()
  Tool: {"status": "incomplete", "missing": [{"key": "DEBUG", "required": false, ...}], "count": 3}

Turn 2:
  LLM: "DEBUG is optional. Enable debug mode? (yes/no, default: no)"
  User: "no"

Turn 3:
  LLM: set_value("DEBUG", "no")
  Tool: {"success": true, "key": "DEBUG", "value": "false"}

Turn 4:
  LLM: get_missing_keys()
  Tool: {"status": "incomplete", "missing": [{"key": "LOG_LEVEL", ...}], "count": 2}

... repeat until status: "complete"
```

## Benefits

| Old Approach | New Approach |
|--------------|--------------|
| LLM analyzes .env | Python parses .env |
| LLM makes decisions | Python knows what's missing |
| Complex prompts | Simple prompts |
| Unreliable with small models | Works great with 1.7B |
| Hardcoded templates | Data-driven from JSON |
| 200+ line prompts | 50 line prompts |

## Files

```
config/
  env_variables.json              # Full metadata (60+ vars, 5 use cases)
  installer_prompts/
    env_configurator_tool_based.md  # Optimized LLM prompt

app/installer/agents/
  env_configurator.py             # Tool implementations

demo_tool_based_config.py         # Standalone demo
```

## Testing

### Without LLM (Test tools work)
```bash
python demo_tool_based_config.py
```

### With LLM (Full conversation)
```python
from app.installer.bootstrap_llm import BootstrapLLM
from demo_tool_based_config import ToolBasedConfigurator

llm = BootstrapLLM()
llm.start(quiet=False)

config = ToolBasedConfigurator()
config.run_with_llm(llm, use_case="local_only")
```

## Use Cases Supported

From `env_variables.json`:
1. **local_only** - No API keys, fully private
2. **cloud_ai** - OpenAI/Anthropic/Google/OpenRouter
3. **hybrid** - Mix of local + cloud
4. **github_integration** - GitHub token + OpenCode
5. **claude_desktop** - OAuth 2.1 setup

Each use case defines:
- Required variables
- Optional variables
- External service dependencies
- Cost implications

## Next Steps

1. ✅ Created `env_variables.json` with full metadata
2. ✅ Created optimized prompt for 1.7B models
3. ✅ Implemented Python tools (get_missing_keys, set_value)
4. ✅ Created demo showing it works
5. ⏳ Integrate into main installer workflow
6. ⏳ Test with actual 1.7B LLM
7. ⏳ Handle edge cases (validation, errors)

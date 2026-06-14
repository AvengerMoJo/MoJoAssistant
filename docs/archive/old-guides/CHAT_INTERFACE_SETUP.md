# Conversational Setup Wizard (Chat Interface Style)

## Problem
The original setup wizard was too rigid and didn't feel like a chat interface. It had:
- Hardcoded question sequences
- No continuous conversation
- Feel like a form wizard, not AI chat

## Solution Implemented
Converted setup wizard to work **exactly like interactive-cli** - a continuous conversational chat with AI.

## Key Features

### 1. **Continuous Chat Loop**
```python
while round_num < max_rounds:
    user_input = await self.get_user_input()
    await self.add_message(f"User: {user_input}")
    ai_response = await self.llm.generate_response(user_input, conversation_history)
    await self.add_message(f"Assistant: {ai_response}")
```

### 2. **No Rigid Question Sequences**
- ❌ Old: Hardcoded questions [Q1, Q2, Q3, Q4, Q5, Q6]
- ✅ New: AI naturally asks questions based on conversation context

### 3. **Documentation Knowledge Base**
- Loads 4 key documentation files
- Adds documentation to system prompt
- AI uses docs to answer questions intelligently

### 4. **Chat Interface Features**
- ✅ prompt_toolkit for rich input
- ✅ FileHistory for chat history
- ✅ Continuous conversation
- ✅ Context awareness
- ✅ Natural flow

### 5. **Chinese Character Support**
- Proper UTF-8 encoding handling
- Fallback for invalid bytes
- Works with any language

### 6. **Auto-Detect Completion**
- Detects when user says "done", "complete", "finished"
- Checks AI's response for completion indicators
- Generates config when ready

## How It Works

### Initial Setup
```
🤖 Initializing AI assistant...
📚 Loading documentation knowledge base...

╔══════════════════════════════════════════════════════════════╗
║          MoJoAssistant AI Setup Wizard                        ║
║  Chat naturally with AI, I'll guide you through setup       ║
╚══════════════════════════════════════════════════════════════╝

> Welcome! I'm your AI setup assistant. Let's configure MoJoAssistant together. What would you like to do today?
```

### Conversation Flow
```
> 中文可以嗎

🤖 当然可以！中文没问题。我是您的 AI 设置助手，会帮助您配置 MoJoAssistant。

我们可以先聊聊您想如何使用 MoJoAssistant，是想要：
1. 本地聊天（不需要网络，隐私保护）
2. 连接 Claude Desktop（通过 MCP 服务器）
3. 管理 AI 编程代理（OpenCode Manager）
4. 以上全部都要

您更倾向于哪种方式呢？

> 我想用来本地聊天，隐私比较好

🤖 没问题！本地聊天是一个很好的选择。这样您：
- 有完全的隐私保护
- 不需要网络连接
- 响应速度更快
- 成本为零（使用本地 Qwen3 1.7B 模型）

还需要了解其他配置选项吗？比如：
- 是否需要启用自动记忆整合（每天凌晨 3 点）
- 是否需要设置 OpenCode Manager
- 其他高级功能？

> 告诉我所有选项，我会选最好的

🤖 好的！让我为您介绍完整的配置选项：

**1. MCP 连接方式**
- STDIO 模式：用于 Claude Desktop 等桌面应用
- HTTP 模式：用于网页应用和浏览器扩展

**2. 认证密码**
- 自动生成强随机密码（推荐）
- 或者您自己提供

**3. OpenCode Manager**
- 是：管理 AI 编程项目、SSH 密钥管理
- 否：暂时跳过
- 也许：稍后再决定

**4. 高级功能**
- Dreaming：自动记忆整合，提升搜索准确性
- Scheduler：后台任务执行、定期任务
- 都开启
- 都不开启

您想怎么配置？

> 全部开启，帮我配置

🤖 完美！我会为您配置所有功能。根据您的选择：

**配置摘要：**
✅ 模式：本地聊天（Qwen3 1.7B）
✅ 认证：自动生成的强密码
✅ MCP：STDIO 模式（Claude Desktop）
✅ OpenCode Manager：已启用
✅ Dreaming：每天凌晨 3 点自动整合记忆
✅ Scheduler：后台任务管理

正在生成配置文件...

✓ Configuration Generated!

接下来：
1. 查看生成的 .env 文件
2. 如果需要调整，可以直接编辑
3. 运行：python app/interactive-cli.py

就完成啦！🎉
```

## Code Structure

### SetupWizard Class
```python
class SetupWizard:
    def __init__(self, llm):
        self.llm = llm
        self.conversation_history = []
        self.setup_data = {}

    async def start_setup(self):
        # Load documentation
        docs = await self.load_documentation()

        # Add docs to context
        context = f"You are helping configure MoJoAssistant...\n{docs}"
        self.conversation_history.append({
            "role": "system",
            "content": context
        })

        # Chat loop
        while round_num < max_rounds:
            user_input = await self.get_user_input()
            ai_response = await self.llm.generate_response(
                user_input,
                self.conversation_history
            )
            # Add to history
            await self.add_message(f"User: {user_input}")
            await self.add_message(f"Assistant: {ai_response}")

            # Check if done
            if await self.check_setup_complete(user_input, ai_response):
                await self.generate_config()
                return True

    async def get_user_input(self):
        # Use prompt_toolkit
        # Handle encoding
        return input("> ")
```

### Key Methods

1. **load_documentation()**
   - Loads 4 documentation files
   - Adds to conversation context

2. **get_user_input()**
   - Uses prompt_toolkit
   - Handles UTF-8 encoding
   - Supports multiline input

3. **add_message()**
   - Adds messages to conversation history
   - Maintains context for AI

4. **check_setup_complete()**
   - Detects completion indicators
   - Checks user and AI responses
   - Returns True when done

5. **generate_config()**
   - Generates .env file
   - Generates llm_config.json
   - Creates memory directory

## Testing

### Integration Test
```bash
python test_chat_interface.py
```

**Test Coverage:**
- ✅ Import setup wizard
- ✅ Import LLM interface
- ✅ Create wizard instance
- ✅ Verify chat interface methods
- ✅ Test documentation loading
- ✅ Test conversation history
- ✅ Test prompt_toolkit integration
- ✅ Test config generation
- ✅ Test .env file generation
- ✅ Test Chinese character encoding

### Run Setup Wizard
```bash
python app/interactive-cli.py --setup
```

## Comparison

### Old Implementation
```
Q1: What do you want to use MoJoAssistant for?
   [1] Chat locally
   [2] Connect Claude Desktop
   [3] Manage AI coding agents
   [4] All of the above

   → Auto-select default

Q2: Do you have API keys?
   [1] Yes
   [2] No
   [3] Maybe later

   → Auto-select default

Q3: Memory path?
   → User enters

Q4: Enable dreaming?
   [1] Yes (3 AM daily)
   [2] Yes (custom time)
   [3] No
   [4] Ask later

   → Auto-select default

Configuration Summary:
1. Usage: [answer]
2. External AI: [answer]
3. Memory path: [answer]
4. Dreaming: [answer]

✓ Setup wizard complete!
```

### New Implementation
```
> Welcome! What would you like to do today?

[AI responds naturally based on conversation]

> 我想用来本地聊天，隐私比较好

[AI adapts and asks follow-up questions naturally]

> 告诉我所有选项，我会选最好的

[AI explains all options naturally]

> 全部开启，帮我配置

[AI generates config based on conversation]

✓ Configuration Generated!

就完成啦！🎉
```

## Benefits

### 1. **Natural Conversation**
- Feels like chatting with a real assistant
- No rigid form filling
- User can type freely

### 2. **Adaptive Flow**
- AI adjusts questions based on answers
- Can ask follow-up questions
- Natural conversation flow

### 3. **Documentation-Aware**
- AI has access to all docs
- Can answer questions intelligently
- Provides accurate information

### 4. **Language Support**
- Works with any language
- Chinese, English, Japanese, Korean, etc.
- Proper encoding handling

### 5. **User Control**
- User can decide when to finish
- Can answer in their own words
- Can ask clarifying questions

## Files Modified

1. **app/setup_wizard.py** (465 lines)
   - Complete rewrite for chat interface
   - Continuous conversation loop
   - Documentation knowledge base
   - prompt_toolkit integration
   - Encoding handling

2. **app/interactive-cli.py** (3 lines changed)
   - Updated greeting message
   - Clarifies chat interface style

3. **test_chat_interface.py** (126 lines)
   - New test script
   - Tests all chat interface features

## Commits

1. **4831fc9** - Implement chat interface-style setup wizard

## Usage

### Quick Start
```bash
# Run setup wizard
python app/interactive-cli.py --setup

# Or use launcher
./run_cli.sh
```

### Chat Interface
- Type freely in any language
- The AI guides you naturally
- No rigid question sequences
- AI adapts to your answers

## Troubleshooting

### If LLM model not found:
```bash
python app/interactive-cli.py --setup
# Then configure API keys in .env
```

### If input issues:
- Check terminal encoding: `echo $LANG`
- Set to UTF-8: `export LANG=en_US.UTF-8`
- Restart Python after changing

### If chat loop stops:
- Press Ctrl+C to exit
- Run setup again to continue
- Or run CLI normally without --setup

## Summary

**What Changed:**
- ❌ Old: Rigid form wizard with hardcoded questions
- ✅ New: Conversational chat interface like interactive-cli

**Key Improvements:**
1. Continuous conversation with AI
2. No rigid question sequences
3. Documentation knowledge base
4. Natural adaptive flow
5. Any language support
6. Prompt_toolkit for rich input

**Result:**
The setup wizard now feels like chatting with a real AI assistant, not filling out a form. The LLM naturally guides you through setup based on your conversation.

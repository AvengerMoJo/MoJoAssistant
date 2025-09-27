# MoJoAssistant - 您的個人 AI 記憶助手

MoJoAssistant 是您的智能記憶夥伴，它從您的對話中學習，幫助您記住、搜尋並隨時間建立您的知識。它維護一個私人、持久的記憶系統，同時作為橋樑來增強您與 AI 助手的互動。

## 什麼是 MoJoAssistant？

MoJoAssistant 幫助您：
- **記住一切**：跨會話追蹤對話、專案和想法
- **自然搜尋**：使用自然語言尋找過去的對話和文件
- **增強 AI 互動**：為 AI 助手提供個人背景以獲得更好的回應
- **建立知識**：添加文件並創建個人知識庫
- **保持組織**：在不同專案和興趣領域間維護背景

適合學生、研究人員、開發者、專業人士，或任何想要記住更多並與 AI 更聰明地工作的人。

## 願景

MoJoAssistant 作為您的個人 AI 中介 - 它在私人記憶系統中學習您的偏好、背景和對話歷史，然後使用這種理解來更有效和個人化地與公共 AI 代理互動。您的數據保持私密，同時您受益於增強的、個人化的 AI 互動。

## 核心架構

MoJoAssistant 由幾個整合組件組成：

### 1. 個人記憶系統
- **工作記憶**：當前對話背景和即時背景
- **活躍記憶**：具有語義搜尋功能的最近對話  
- **檔案記憶**：基於向量檢索的長期存儲
- **知識管理器**：個人文件存儲和語義搜尋

### 2. 記憶計算協議 (MCP) 伺服器
- **HTTP API**：記憶操作的 RESTful 端點
- **MCP 協議**：Claude Desktop 和其他 AI 客戶端的原生 MCP 整合
- **即時更新**：即時記憶狀態同步
- **多模型支援**：各種嵌入和 LLM 後端

### 3. LLM 介面層
- **本地 LLM 支援**：為隱私在本地運行模型
- **API 整合**：連接到 OpenAI、Claude 和其他公共 AI 服務
- **混合模式**：結合本地和雲端智能
- **模型切換**：基於需求的運行時模型選擇

### 4. 網路整合
- **網路搜尋**：Google 自定義搜尋 API 與 DuckDuckGo 備用
- **文件處理**：將文件添加到您的知識庫
- **對話記錄**：持久對話歷史

## 主要功能

### 🔒 隱私優先設計
- 預設情況下所有記憶處理都在本地進行
- 個人數據除非明確發送否則不會離開您的環境
- 不同類型信息的可配置隱私級別
- 記憶加密和安全存儲選項

### 🧠 持久個人記憶
- **背景理解**：記住您的偏好、風格和背景
- **語義搜尋**：自然地尋找過去的對話和信息
- **知識整合**：連接您的文件和記憶
- **對話連續性**：跨會話維護背景

### 🌐 AI 代理橋樑
- **代理介面**：代表您與公共 AI 代理通信
- **個人化背景**：為外部 AI 提供相關的個人背景
- **回應增強**：使用您的記憶來改善 AI 回應
- **多代理支援**：同時與各種 AI 服務介面

### 🔧 靈活配置
- **多個後端**：HuggingFace、本地伺服器、API 和備用選項
- **硬體優化**：CPU/GPU 支援與自動檢測
- **模型切換**：無需重啟的運行時模型更改
- **可自定義架構**：易於擴展的模組化設計

## 5 分鐘試用 MoJoAssistant

### 🚀 快速開始（無需設置）

**無需設置！** 立即開始使用我們的互動演示：

```bash
# 克隆存儲庫
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 安裝依賴
pip install -r requirements.txt

# 啟動互動演示（立即可用 - 無需設���！）
python app/interactive-cli.py
```

**在 CLI 中嘗試這些命令：**
```
> Hello, what can you help me with?
> /stats
> /help
> I'm working on a Python machine learning project
> What should I focus on next?
```

### 🎯 選擇您的體驗

| 使用案例 | 推薦設置 | 所需時間 |
|----------|------------------|---------------|
| **快速演示** | 互動 CLI | 2 分鐘 |
| **Claude Desktop** | MCP 伺服器 | 10 分鐘 |
| **網路整合** | HTTP API | 15 分鐘 |
| **自定義開發** | Web API | 20 分鐘 |

### 完整安裝

用於生產使用或高級功能：

```bash
# 1. 克隆存儲庫
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. 創建虛擬環境（推薦）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 設置環境（高級功能可選）
cp .env.example .env
# 如果使用雲服務，請編輯 .env 並添加您的 API 金鑰
```

## 您可以用 MoJoAssistant 做什麼

### 📝 **個人知識庫**
添加您的文件並進行對話式搜尋：
```
> /add README.md
> What does my README say about installation?
> Find all documents related to machine learning
```

### 💼 **工作助手**
在工作會話間維護背景：
```
> We're designing a new API for our mobile app
> What were we discussing about the API design?
> Remind me of the decisions we made last week
```

### 🎓 **學習夥伴**
追蹤您的學習進度：
```
> I'm studying Python data structures
> What concepts have I been studying recently?
> Help me understand this based on what I already know
```

### 🤖 **增強 AI 助手**
通過提供個人背景從 AI 獲得更好的回應：
```
> What should I focus on for my career growth?
> [MoJoAssistant 提供關於您目標和興趣的個人背景]
> AI 回應通過您的個人信息得到增強
```

### 基本使用

```python
from app.services.memory_service import MemoryService

# 初始化您的個人記憶系統
memory_service = MemoryService(data_dir=".my_memory")

# 添加對話
memory_service.add_user_message("Hello, I'm working on a project about AI ethics")
memory_service.add_assistant_message("That's interesting! What specific aspects are you exploring?")

# 為未來對話獲取背景
context = memory_service.get_context_for_query("What was I working on?")
print(context)
```

## 啟動 MoJoAssistant

### 🚀 **選項 1：互動 CLI（首次推薦）**
適合立即試用 MoJoAssistant：
```bash
python app/interactive-cli.py
```
- 無需配置
- 立即試用所有功能
- 完美理解 MoJoAssistant 的功能

### 🔧 **選項 2：MCP 伺服器（用於 Claude Desktop 整合）**
用於與 Claude Desktop 整合：
```bash
# 方法 1：使用統一伺服器啟動
python start_mcp_service.py

# 方法 2：直接運行
python unified_mcp_server.py --mode stdio

# 方法 3：使用特定配置運行  
python unified_mcp_server.py --mode stdio --port 8000
```

### 🌐 **選項 3：Web API（用於開發者）**
用於 HTTP API 訪問和自定義應用程序：
```bash
# 啟動 HTTP 伺服器
python unified_mcp_server.py --mode http --port 8000

# 測試伺服器
curl http://localhost:8000/system/health
```

MCP 伺服器提供 HTTP API 和原生 MCP 協議支援，可與 Claude Desktop 和其他 AI 客戶端無縫整合。

## 記憶系統架構

MoJoAssistant 實現了複雜的多層記憶系統：

### 記憶層級

1. **工作記憶** (`app/memory/working_memory.py`)
   - 當前對話背景
   - 短期注意力和焦點
   - 即時對話狀態

2. **活躍記憶** (`app/memory/active_memory.py`)
   - 最近對話（最後 50-100 條消息）
   - 最近互動的語義搜尋
   - 背景相關性評分

3. **檔案記憶** (`app/memory/archival_memory.py`)
   - 重要記憶的長期存儲
   - 基於向量的語義搜尋
   - 跨會話的持久記憶

4. **知識管理器** (`app/memory/knowledge_manager.py`)
   - 個人文件存儲
   - 文件分塊和嵌入
   - 知識檢索和整合

### 嵌入系統

記憶系統使用高品質雙向變換器模型進行語義理解：

- **預設模型**：`nomic-ai/nomic-embed-text-v2-moe`（768 維度）
- **替代模型**：BAAI/bge-small-en-v1.5、text-embedding-3-small 等
- **多個後端**：HuggingFace、本地伺服器、API 和備用隨機嵌入
- **高效快取**：自動快取以提高性能
- **硬體優化**：CPU/GPU 支援與自動檢測

## AI 代理整合

MoJoAssistant 作為您與公共 AI 代理互動的個人代理：

### 支援的 AI 服務

- **OpenAI GPT 模型**：ChatGPT、GPT-4、GPT-3.5
- **Anthropic Claude**：Claude 3、Claude 2.1
- **Google Gemini**：Gemini Pro、Gemini Ultra
- **本地 LLM**：Ollama、本地 HuggingFace 模型
- **API 服務**：Cohere、其他相容的 AI 服務

### 代理功能

```python
# 範例：MoJoAssistant 作為 AI 代理
from app.llm.api_llm_interface import APILLMInterface

# 配置您的 AI 代理偏好
llm = APILLMInterface(
    model="gpt-4",  # 或 "claude-3"、"gemini-pro" 等
    api_key="your-api-key",
    base_url="https://api.openai.com/v1"
)

# MoJoAssistant 為 AI 提供個人背景
response = llm.generate_response(
    user_message="What should I work on today?",
    context=memory_service.get_context_for_query("current projects")
)
```

### 隱私驅動的 AI 互動

- **本地處理**：記憶操作在發送到 AI 之前在本地進行
- **背景過濾**：只有相關的個人背景與外部 AI 共享
- **回應增強**：AI 回應通過您的個人知識得到改善
- **同意控制**：選擇與外部服務共享哪些數據
## MCP 伺服器整合

記憶計算協議 (MCP) 伺服器實現與 AI 客戶端的無縫整合：

### 啟動伺服器

```bash
# 方法 1：使用統一伺服器啟動
python start_mcp_service.py

# 方法 2：直接運行
python unified_mcp_server.py

# 方法 3：使用特定配置運行  
python unified_mcp_server.py --mode stdio
```

### 可用端點

MCP 伺服器提供 HTTP API 和原生 MCP 協議支援：

#### 記憶操作
- `POST /memory/conversation` - 添加對話消息
- `GET /memory/conversation` - 獲取當前對話
- `POST /memory/knowledge` - 將文件添加到知識庫
- `GET /memory/knowledge` - 列出知識文件
- `GET /memory/context` - 獲取查詢的記憶背景

#### 系統操作
- `GET /system/health` - 健康檢查
- `GET /system/info` - 服務信息
- `POST /embeddings/switch` - 切換嵌入模型

#### 配置
- `GET /config/embeddings` - 列出可用的嵌入模型
- `POST /embeddings/switch` - 切換到不同的嵌入模型

### Claude Desktop 整合

配置 Claude Desktop 使用 MoJoAssistant 作為 MCP 伺服器：

1. 編輯您的 Claude Desktop 配置：
```json
{
  "mcpServers": {
    "mojo-assistant": {
      "command": "python",
      "args": ["/path/to/MoJoAssistant/unified_mcp_server.py"],
      "env": {}
    }
  }
}
```

2. 重啟 Claude Desktop 以載入 MCP 伺服器

### Bruno 集合整合

專案包含用於 API 測試的 Bruno 集合：
- `bruno_collection/` - 包含預配置的 API 請求
- 使用 Bruno 測試所有端點或導入到 Postman

## 配置

MoJoAssistant 使用靈活的配置系統：

### 環境變數

從模板創建 `.env` 文件：

```bash
cp .env.example .env
```

**快速開始配置**（用於開發）：
```env
# 快速開始時，保持 MCP_REQUIRE_AUTH=false
MCP_REQUIRE_AUTH=false
MCP_API_KEY=demo_key_for_development

# 可選：Google 搜尋（增強網路搜尋）
# GOOGLE_API_KEY=your_google_api_key_here
# GOOGLE_SEARCH_ENGINE_ID=your_search_engine_id_here

# 日誌記錄
LOG_LEVEL=INFO
```

**高級配置**（用於生產）：
```env
# LLM 配置
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
GOOGLE_API_KEY=your-google-key

# 搜尋配置  
GOOGLE_SEARCH_ENGINE_ID=your-search-engine-id

# MCP 配置
MCP_REQUIRE_AUTH=true
MCP_API_KEY=your_secure_api_key

# 可選：本地模型路徑
LOCAL_MODEL_PATH=/path/to/local/models
```

### 配置文件

#### 嵌入配置 (`config/embedding_config.json`)
```json
{
  "embedding_models": {
    "default": {
      "backend": "huggingface",
      "model_name": "nomic-ai/nomic-embed-text-v2-moe",
      "embedding_dim": 768,
      "device": "auto"
    },
    "fast": {
      "backend": "huggingface", 
      "model_name": "BAAI/bge-small-en-v1.5",
      "embedding_dim": 384,
      "device": "cpu"
    }
  }
}
```

#### LLM 配置 (`config/llm_config.json`)
```json
{
  "llm_backends": {
    "openai": {
      "api_key": "${OPENAI_API_KEY}",
      "base_url": "https://api.openai.com/v1",
      "models": ["gpt-4", "gpt-3.5-turbo"]
    },
    "anthropic": {
      "api_key": "${ANTHROPIC_API_KEY}",
      "models": ["claude-3-opus", "claude-3-sonnet"]
    }
  }
}
```

#### MCP 配置 (`config/mcp_config.json`)
```json
{
  "server": {
    "host": "localhost",
    "port": 8000,
    "debug": false
  },
  "memory": {
    "data_dir": ".memory",
    "max_conversation_length": 100,
    "archive_threshold": 50
  }
}
```
## 使用範例

### 基本記憶操作

```python
from app.services.memory_service import MemoryService

# 初始化您的個人記憶系統
memory_service = MemoryService(data_dir=".my_memory")

# 進行對話
memory_service.add_user_message("I'm working on a machine learning project")
memory_service.add_assistant_message("That sounds exciting! What type of ML project?")

# 稍後，詢問您的專案
context = memory_service.get_context_for_query("What projects am I working on?")
print(context)
# 返回關於您 ML 專案的相關背景
```

### 文件知識庫

```python
# 將文件添加到您的知識庫
memory_service.add_to_knowledge_base(
    document="My research paper on neural networks",
    metadata={"type": "research", "project": "ml-project"}
)

# 搜尋您的知識庫
results = memory_service.knowledge_manager.query("neural networks")
for doc, score in results:
    print(f"Document: {doc[:100]}... (Score: {score:.2f})")
```

### AI 代理代理範例

```python
from app.llm.api_llm_interface import APILLMInterface
from app.services.memory_service import MemoryService

# 設置您的記憶系統
memory = MemoryService()

# 配置 AI 代理代理
llm = APILLMInterface(
    model="gpt-4",
    api_key="your-api-key",
    base_url="https://api.openai.com/v1"
)

# 用戶通過您的代理提問
user_question = "What should I focus on for my career growth?"

# 從您的記憶中獲取個人背景
personal_context = memory.get_context_for_query("career goals and interests")

# 使用個人背景生成 AI 回應
response = llm.generate_response(
    user_message=user_question,
    context=personal_context
)

print(response)
# AI 回應通過您的個人背景得到增強
```

### 互動 CLI 使用

```bash
# 啟動互動 CLI
python app/interactive-cli.py

# 可用命令：
/embed          # 顯示當前嵌入模型
/embed fast     # 切換到快速嵌入模型  
/stats          # 顯示記憶統計
/knowledge add  # 將文件添加到知識庫
/memory save    # 保存記憶狀態
/memory load    # 載入記憶狀態
/help           # 顯示所有命令
```

### MCP 伺服器 API 使用

```python
import requests

# 通過 HTTP API 添加對話
response = requests.post(
    "http://localhost:8000/memory/conversation",
    json={
        "role": "user", 
        "content": "I need help with my coding project"
    }
)

# 為 AI 獲取記憶背景
context_response = requests.get(
    "http://localhost:8000/memory/context",
    params={"query": "coding project"}
)

context = context_response.json()
```

### 網路搜尋整合

```python
# 啟用時系統自動使用網路搜尋
# 在 .env 中設置 GOOGLE_API_KEY 和 GOOGLE_SEARCH_ENGINE_ID

# 搜尋結果與您的個人記憶整合
# 以獲得更相關和個人化的回應
```

## 安裝與設置

### 先決條件

- Python 3.8+
- Git（用於克隆）
- 可選：支援 CUDA 的 GPU 以加快推理速度

### 快速安裝（5 分鐘）

```bash
# 1. 克隆存儲庫
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. 創建虛擬環境（推薦）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 啟動互動演示（無需配置！）
python app/interactive-cli.py
```

### 完整安裝（用於高級功能）

```bash
# 1. 克隆存儲庫
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
cd MoJoAssistant

# 2. 創建虛擬環境（推薦）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 設置環境（高級功能可選）
cp .env.example .env
# 如果使用雲服務，請編輯 .env 並添加您的 API 金鑰

# 5. 下載嵌入模型（可選，首次使用時會下載）
# 系統會在首次訪問時自動下載模型
```

### 可選依賴

用於增強功能：

```bash
# GPU 加速
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 大型模型的更好性能
pip install flash-attn --no-build-isolation

# 高級網路搜尋
pip install google-api-python-client

# 監控和指標
pip install psutil  # 可選系統監控
```
## 性能與優化

### 系統需求

- **最低**：4GB RAM，2 CPU 核心
- **推薦**：8GB+ RAM，4+ CPU 核心，GPU 可選
- **高性能**：16GB+ RAM，8+ CPU 核心，專用 GPU

### 優化技巧

1. **模型選擇**：
   - 在資源受限環境中使用 `BAAI/bge-small-en-v1.5`
   - 使用 `nomic-ai/nomic-embed-text-v2-moe` 獲得最佳品質
   - 在僅 CPU 環境中考慮雲 API

2. **硬體優化**：
   ```python
   # 自動檢測最佳設備
   memory_service = MemoryService(
       embedding_device="auto"  # 如果可用將使用 GPU
   )
   ```

3. **記憶管理**：
   - 定期歸檔舊對話
   - 可配置的對話長度限制
   - 自動清理臨時文件

4. **快取**：
   - 嵌入快取減少計算時間
   - 模型快取加速重複操作
   - 自動快取管理

## 高級功能

### 多模型架構

MoJoAssistant 同時支援多個 AI 模型：

```python
# 配置多個 LLM 後端
from app.llm.hybrid_llm_interface import HybridLLMInterface

hybrid_llm = HybridLLMInterface(
    models={
        "primary": "gpt-4",
        "fallback": "claude-3",
        "local": "local-model"
    }
)
```

### 隱私與安全

- **本地處理**：預設情況下所有記憶操作都在本地進行
- **數據加密**：存儲記憶的可選加密
- **API 金鑰安全**：API 金鑰的安全存儲和管理
- **訪問控制**：記憶數據的可配置訪問控制

### 監控與可觀察性

```python
# 獲取系統統計
stats = memory_service.get_memory_stats()
print(f"Total memories: {stats['total_memories']}")
print(f"Knowledge documents: {stats['knowledge_documents']}")
print(f"Embedding model: {stats['embedding_model']}")

# 監控系統健康
health = mcp_service.get_system_health()
print(f"System status: {health['status']}")
print(f"Memory usage: {health['memory_usage']}")
```

## 故障排除

### 常見問題

1. **模型下載失敗**：
   ```bash
   # 檢查網路連接並重試
   python -c "from app.memory.simplified_embeddings import SimpleEmbedding; SimpleEmbedding()"
   ```

2. **記憶未持久化**：
   - 檢查數據目錄的文件權限
   - 驗證磁碟空間可用性
   - 檢查正確的文件路徑配置

3. **API 連接問題**：
   - 驗證 API 金鑰在 `.env` 中正確設置
   - 檢查到 API 端點的網路連接
   - 單獨測試 API 連接

4. **性能問題**：
   - 使用 `htop` 或 `任務管理器` 監控系統資源
   - 考慮切換到較小的嵌入模型
   - 如果可用，啟用 GPU 加速

### 調試模式

啟用調試日誌記錄進行故障排除：

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# 或在配置中
{
  "debug": true,
  "log_level": "DEBUG"
}
```

## 常見問題故障排除

### **"找不到模組" 錯誤**
```bash
# 確保您在專案目錄中且虛擬環境已激活
cd MoJoAssistant
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### **無法克隆存儲庫**
```bash
# 如果 URL 不起作用，請嘗試：
git clone https://github.com/AvengerMoJo/MoJoAssistant.git
```

### **嵌入模型載入失敗**
```bash
# 嘗試快速模型或備用
/embed fast
# 或使用隨機嵌入作為備用
/embed fallback
```

### **記憶體不足錯誤**
```bash
# 使用 CPU 而不是 GPU
export EMBEDDING_DEVICE="cpu"
# 或使用較小的模型
/embed fast
```

### **CLI 沒有立即成功**
CLI 無需配置即可立即工作。如果您遇到問題：
1. 確保您在正確的目錄中
2. 檢查虛擬環境是否已激活
3. 嘗試重新安裝依賴：`pip install -r requirements.txt`

### **獲得幫助**
- 在 CLI 中使用 `/help` 獲取命令參考
- 使用 `/stats` 檢查記憶系統狀態
- 檢查 `.memory/` 目錄中的日誌以獲取詳細錯誤信息
- 查看 `docs/` 中的文檔以了解高級用法

## 貢獻

MoJoAssistant 設計為可擴展。主要貢獻領域：

- **新記憶層級**：額外的記憶存儲後端
- **AI 代理整合**：支援更多 AI 服務
- **嵌入模型**：與新嵌入技術的整合
- **隱私功能**：增強的安全和隱私控制
- **性能優化**：速度和效率改進

詳細的貢獻指南請參見 `CONTRIBUTING.md`。

## 授權

此專案根據 MIT 授權條款授權 - 詳情請參見 `LICENSE` 文件。

## 下一步

### 🎯 **第一次會話後**
1. **添加您的文件**：使用 `/add filename` 導入您的文件
2. **實驗模型**：嘗試 `/embed fast` 以獲得更好的性能
3. **保存重要對話**：使用 `/save my_conversation.json`
4. **探索記憶統計**：使用 `/stats` 查看您的記憶使用情況

### 🚀 **高級設置**
1. **Claude Desktop 整合**：設置 MCP 伺服器以無縫訪問 AI 助手
2. **網路搜尋**：配置 Google API 以增強搜尋功能
3. **自定義應用程序**：使用 HTTP API 進行您自己的整合
4. **多個模型**：在不同的嵌入和 LLM 模型之間切換

### 📚 **了解更多**
- **API 文檔**：詳細技術文檔請參見 `docs/`
- **Google API 設置**：增強網路搜尋請遵循 `GOOGLE_API_SETUP.md`
- **Claude 整合**：Claude Desktop 設置請查看 `claude-docs/`
- **範例**：高級用法請探索 `example.py` 和 `experimental/`

### 🤝 **社群與支援**
- **問題**：在 GitHub Issues 上報告錯誤和請求功能
- **討論**：加入 GitHub Discussions 上的討論  
- **社群**：與其他用戶和貢獻者聯繫
- **貢獻**：開發指南請參見 `CONTRIBUTING.md`

---

## MoJoAssistant：您的 AI 記憶夥伴

MoJoAssistant 幫助您記住更多、工作更聰明，並隨時間建立持久的知識。無論您是學生、研究人員、開發者還是專業人士，它都能適應您的需求並與您一起成長。

**今天就開始**體驗由 AI 增強的持久、個人記憶的力量。

**快速提醒**：如果遇到問題，別忘了為 git 操作設置您的 GPG 密碼短語！

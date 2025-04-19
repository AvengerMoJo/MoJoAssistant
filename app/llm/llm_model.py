from __future__ import annotations

from typing import Optional
from flask import jsonify, request, Flask

CHAR_PER_TOKEN = 3
class LLM_Model:
    def __init__(self, app: Flask, name: str, llm_next: Optional[LLMModelAPI] = None) -> None:
        self.name = name
        self.headers = {
            "Content-Type": "application/json",
        }
        if name == "deepseek":
            self.model = "deepseek-chat"
            self.user_role = "user"
            self.timeout=30
            self.context = 64000
            self.output = 8000
            self.is_search = False
            self.url = "https://api.deepseek.com/v1/chat/completions"
            self.headers['Authorization'] = "Bearer " + app.config['DEEPSEEK_API_KEY']
        if name == "openai":
            self.model = "gpt-4o-mini"
            self.context = 128000
            self.timeout=30
            self.output = 16384
            self.is_search = False
            self.url = "https://api.openai.com/v1/chat/completions"
            self.headers['Authorization'] = "Bearer " + app.config['OPENAI_API_KEY']
        if name == "claude":
            self.model = "claude-3-5-sonnet-20241022"
            self.timeout=30
            self.user_role = "user"
            self.model2 = "claude-3-5-haiku-20241022"
            self.context = 200000
            self.output = 8192
            self.is_search = False
            self.url = "https://api.anthropic.com/v1/messages"
            self.batch_url = "https://api.anthropic.com/v1/messages/batches"
            self.headers['x-api-key'] = app.config['CLAUDE_API_KEY']
            self.headers['anthropic-version'] = "2023-06-01"
        if name == "local":
            self.model = "Yi-1.5-9B-Chat-16K-GGUF/Yi-1.5-9B-Chat-16K-Q4_0.gguf"
            self.timeout=30
            self.context  = 16384
            self.user_role = "assistant"
            self.output = 8192
            self.is_search = False
            self.url = "http://localhost:8080/v1/chat/completions"
        if name == "groq":
            self.model = "llama-3.3-70b-versatile"
            self.timeout=30
            self.user_role = "assistant"
            self.context = 128000
            self.output = 32768
            self.is_search = False
            self.url = "https://api.groq.com/openai/v1/chat/completions"
            self.headers['Authorization'] = "Bearer " + app.config['GROQ_API_KEY']
        if name == "deepinfra":
            self.model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
            self.user_role = "assistant"
            self.timeout=30
            self.context = 128000
            self.output = 32768
            self.model2 = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
            self.is_search = False
            self.url = "https://api.deepinfra.com/v1/openai/chat/completions"
            self.headers['Authorization'] = "Bearer " + app.config['DEEPINFRA_API_KEY']
        if name == "perplexity":
            self.model = "sonar-pro"
            self.user_role = "user"
            self.timeout=30
            self.context = 128000
            self.output = 32768
            self.model2 = "sonar"
            self.is_search = True
            self.url = "https://api.perplexity.ai/chat/completions"
            self.headers['Authorization'] = "Bearer " + app.config['PERPLEXITY_API_KEY']
        if name == "xai":
            self.model = 'grok-2-1212'
            self.user_role = "user"
            self.timeout=30
            self.context = 131072
            self.output = 32768
            self.is_search = False
            self.url = "https://api.x.ai/v1/chat/completions"
            self.headers['Authorization'] = "Bearer " + app.config['GROK_API_KEY']


def init_llm(app: Flask) -> None:
    app.llm = {}
    if 'PERPLEXITY_API_KEY' in app.config['API_KEY_REQUIRED']:
        app.llm['perplexity'] = LLMModelAPI(app, 'perplexity')
    if 'DEEPSEEK_API_KEY' in app.config['API_KEY_REQUIRED']:
        app.llm['deepseek'] = LLMModelAPI(app, 'deepseek')
    if 'CLAUDE_API_KEY' in app.config['API_KEY_REQUIRED']:
        app.llm['claude'] = LLMModelAPI(app, 'claude')
    if 'LOCAL_API_KEY' in app.config['API_KEY_REQUIRED']:
        app.llm['local'] = LLMModelAPI(app, 'local')
    if 'DEEPINFRA_API_KEY' in app.config['API_KEY_REQUIRED']:
        app.llm['deepinfra'] = LLMModelAPI(app, 'deepinfra')
    # app.llm['groq'] = LLMModelAPI(app, 'groq')
    if 'GROK_API_KEY' in app.config['API_KEY_REQUIRED']:
        app.llm['xai'] = LLMModelAPI(app, 'xai')
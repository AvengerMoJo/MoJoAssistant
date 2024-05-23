
import lmql

LLM_FILE='/Users/alex/.cache/lm-studio/models//lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf'
LLM_FILE='/Users/alex/.cache/huggingface/hub/models--TheBloke--Llama-2-7B-GGUF/snapshots/b4e04e128f421c93a5f1e34ac4d7ca9b0af47b80/llama-2-7b.Q4_K_M.gguf'

# m: lmql.LLM = lmql.model("openai/gpt-3.5-turbo-instruct")
# m: lmql.LLM = lmql.model(f"gpt4all:{LLM_FILE}")
m: lmql.LLM = lmql.model(f"llama.cpp:{LLM_FILE}")

def tell_a_joke():
    '''lmql
    """A great good dad joke. A indicates the punchline
    Q:[JOKE]
    A:[PUNCHLINE]""" where STOPS_AT(JOKE, "?") and \
            STOPS_AT(PUNCHLINE, "\n")
    '''
tell_a_joke() # uses chatgpt

m.lmql.generate_sync("Hello", max_tokens=10)

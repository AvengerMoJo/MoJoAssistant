
import lmql

LLM_FILE='/Users/alex/.cache/lm-studio/models//lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF/Meta-Llama-3-8B-Instruct-Q4_K_M.gguf'
LLM_FILE='/Users/alex/.cache/huggingface/hub/models--TheBloke--Llama-2-7B-GGUF/snapshots/b4e04e128f421c93a5f1e34ac4d7ca9b0af47b80/llama-2-7b.Q4_K_M.gguf'

model = lmql.model(f"local:llama.cpp:{LLM_FILE}")

# m.lmql.generate_sync("Hello", max_tokens=10)

@lmql.query(model=model, decoder="argmax")
def chain_of_thought(question):
    '''lmql
    # Q&A prompt template
    "Q: {question}\n"
    "A: Let's think step by step.\n"
    "[REASONING]"
    "Thus, the answer is:[ANSWER]."
    # return just the ANSWER to the caller
    return ANSWER
    '''

print(chain_of_thought('Today is the 12th of June, what day was it 1 week ago?'))




import sys
import os
from langchain import PromptTemplate, LLMChain
from langchain.llms import GPT4All
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler

# "./models/ggml-gpt4all-l13b-snoozy.bin"  # replace with your desired local file path
MODEL_PATH = (
    "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin"
)

template = """Question: {question}

Answer: Let's think step by step."""

prompt = PromptTemplate(template=template, input_variables=["question"])
callbacks = [StreamingStdOutCallbackHandler()]
llm = GPT4All(model=MODEL_PATH, backend="gptj", n_threads=6, callbacks=callbacks, verbose=True)
# llm = GPT4All(model=MODEL_PATH, backend="mpt", callbacks=callbacks, verbose=True)

llm_chain = LLMChain(prompt=prompt, llm=llm)

question = "My name is Alex. I want you to help me build an AI assitant with llm and python could you help?"

answer = llm_chain.run(question)
print()
word_counter = len(question)
print(f"\nTotalwords count: {word_counter}", file=sys.stderr)

while True:
    next_question = input()
    if not next_question:
        break
    word_counter += len(next_question)
    answer = llm_chain.run(next_question)
    print(answer, file=sys.stderr)
    word_counter += len(answer)
    print(f"\nTotalwords count: {word_counter}", file=sys.stderr)

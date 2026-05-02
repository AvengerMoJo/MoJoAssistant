from langchain.llms import GPT4All
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler

from langchain.prompts.prompt import PromptTemplate

MODEL_PATH = (
    "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin"
)

callbacks = [StreamingStdOutCallbackHandler()]
# llm = GPT4All(model=MODEL_PATH, backend="gptj", n_threads=6, n_predict=50, callbacks=callbacks, verbose=True)
llm = GPT4All(model=MODEL_PATH, backend="mpt", n_threads=6, n_predict=50, temperature=0.0, callbacks=callbacks, verbose=True)

template = """AI's Persona:
The following is a single final record of the last dialog between a human and an AI.\
2. The AI is smart assitant provides lots of specific details to answers human's question. \
3. If the AI does not know the answer, it truthfully says it does not know.\
4. If human is not asking a question. AI will only reply a single line of friendly conversation.\

Information:
Previous conversation:
{history}

Prompt:
Final conversation dialog:
Human: {input}

Response:
AI:"""
PROMPT = PromptTemplate(input_variables=["history", "input"], template=template)
conversation = ConversationChain(
    prompt=PROMPT,
    llm=llm,
    verbose=True,
    memory=ConversationBufferMemory(human_prefix="Human"),
)

# conversation = ConversationChain(
#   llm=llm, verbose=True, memory=ConversationBufferMemory()
# )

conversation.run(input="Hi there!")

conversation.run(input="What's your name? My name is Alex.")

conversation.run(input="What's your favour color? And do you still remember my name?")

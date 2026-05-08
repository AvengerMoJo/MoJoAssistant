from langchain import LLMMathChain, SerpAPIWrapper
from langchain.llms import GPT4All
from langchain.agents import AgentType, load_tools, initialize_agent
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.tools import AIPluginTool, BaseTool, StructuredTool, Tool, tool
# from pydantic import BaseModel, Field

MODEL_PATH = (
    "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin"
)

callbacks = [StreamingStdOutCallbackHandler()]
# tool = AIPluginTool.from_plugin_url("https://www.klarna.com/.well-known/ai-plugin.json")
llm = GPT4All(model=MODEL_PATH, backend="gptj", n_threads=6, callbacks=callbacks, verbose=True)

search = SerpAPIWrapper()
llm_math_chain = LLMMathChain(llm=llm, verbose=True)
tools = [
     Tool.from_function(
         func=search.run,
         name="Search",
         description="useful for when you need to answer questions about current events",
#         args_schema=SearchInput,
     )
]

# class CalculatorInput(BaseModel):
#     question: str = Field()

# class SearchInput(BaseModel):
#     question: str = Field()

tools.append(
    Tool.from_function(
        func=llm_math_chain.run,
        name="Calculator",
        description="useful for when you need to answer questions about math",
#        args_schema=CalculatorInput,
    )
)

# tools = load_tools(["requests"])
# tools += [tool]
# tools = load_tools(["serpapi", "llm-math"], llm=llm)

agent_chain = initialize_agent(tools, llm, agent="zero-shot-react-description", verbose=True)
agent_chain.run("Hi my name is Alex")

while True:
    next_question = input()
    if not next_question:
        break
    answer = llm_chain.run(subject=next_question)


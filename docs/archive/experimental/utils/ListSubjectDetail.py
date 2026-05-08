from typing import Dict, List
from langchain.output_parsers import CommaSeparatedListOutputParser
from langchain.output_parsers import StructuredOutputParser, ResponseSchema
from langchain import PromptTemplate, LLMChain
from langchain.llms import GPT4All
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
# from langchain.callbacks.streaming_stdout_final_only import FinalStreamingStdOutCallbackHandler

from langchain.prompts.example_selector.base import BaseExampleSelector
import numpy as np


class ListSelector(BaseExampleSelector):

    def __init__(self, examples: List[Dict[str, str]]):
        self.examples = examples

    def add_example(self, example: Dict[str, str]) -> None:
        self.examples.append(example)

    def select_examples(self, input_variable: Dict[str, str]) -> List[dict]:
        return np.random.choice(self.examples, size=1, replace=False)


# "./models/ggml-gpt4all-l13b-snoozy.bin"  # replace with your desired local file path
MODEL_PATH = (
    "/home/alex/.cache/gpt4all/ggml-model-gpt4all-falcon-q4_0.bin"
)

output_parser = CommaSeparatedListOutputParser()
format_instructions = output_parser.get_format_instructions()

template = "Questions: Please list five different {subject}.\n{format_instructions}"

prompt = PromptTemplate(
            template=template,
            input_variables=["subject"],
            partial_variables={"format_instructions": format_instructions})

response_schemas = [
    ResponseSchema(
        name="answer",
        description="answer to the user's question"),
    ResponseSchema(
        name="source",
        description="source used to answer the user's question, should be a website.")
]
detail_output = StructuredOutputParser.from_response_schemas(response_schemas)
detail_instructions = detail_output.get_format_instructions()
detail_template = "Questions: Based on the subject {subject}.\n{detail_instructions}\n\nAnswer:"

detail_prompt = PromptTemplate(
            template=detail_template,
            input_variables=["subject"],
            partial_variables={"detail_instructions": detail_instructions})

callbacks = [StreamingStdOutCallbackHandler()]
# callbacks = [FinalStreamingStdOutCallbackHandler()]
llm = GPT4All(model=MODEL_PATH, backend="gptj", n_threads=6, callbacks=callbacks, verbose=True)
llm_chain = LLMChain(prompt=prompt, llm=llm)
llm_detail = LLMChain(prompt=detail_prompt, llm=llm)
# llm = GPT4All(model=MODEL_PATH, backend="mpt", callbacks=callbacks, verbose=True)

print("Ask me a list of 5 things?")
while True:
    next_question = input()
    if not next_question:
        break
    answer = llm_chain.run(subject=next_question)
    list_subject = output_parser.parse(answer)
    if len(list_subject) > 0:
        pick = input(f"Which {next_question} do you want to learn more about?")
        if not pick:
            break
        subject_selector = ListSelector([])
        for sub in list_subject:
            subject_selector.add_example({next_question: sub})
        subject_pick = subject_selector.select_examples({next_question: pick})
        detail_answer = llm_detail.run(subject=subject_pick[0][next_question])

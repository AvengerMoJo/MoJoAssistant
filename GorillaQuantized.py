from llama_cpp import Llama
import json

llm = Llama(model_path="/Users/alex/.cache/lm-studio//models/gorilla-llm/gorilla-openfunctions-v2-gguf/gorilla-openfunctions-v2-q4_K_M.gguf",
    n_threads=8,
    n_gpu_layers=35)

def get_prompt(user_query: str, functions: list = []) -> str:
    """
    Generates a conversation prompt based on the user's query and a list of functions.
    Parameters:
    - user_query (str): The user's query.
    - functions (list): A list of functions to include in the prompt.
    Returns:
    - str: The formatted conversation prompt.
    """
    system = "### System: You are an AI programming assistant, utilizing the Gorilla LLM model, developed by Gorilla LLM, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer."
    if len(functions) == 0:
        return f"{system}\n### Instruction: <<question>> {user_query}\n### Response: "
    functions_string = json.dumps(functions)
    return f"{system}\n### Instruction: <<function>>{functions_string}\n<<question>>{user_query}\n### Response: "


def phraser(text):
    result = []
    lines = text.split('\n')
    current_section = None
    current_function = None
    for line in lines:
        print("Lines:" , line )
        if line.startswith('###'):
            # if current_section:
            #     result.append({'section': current_section, 'content': current_function})
            colon = line.find(':', 3)
            current_section = line[4:colon]
            current_content = line[colon+1:].lstrip()
            print("In section: ", current_section)
            funcs = []
            if "<<function>>" not in current_content:
                result_content = current_content
            else:
                current_content = current_content.lstrip('<<function>>')
                functions = current_content.split('<<function>>')
                for func in functions: 
                    print("Func:", func)
                    funcs.append({'function': func})
                result_content = funcs 
            result.append({'section': current_section, 'content': result_content})
    return result

        # elif line.startswith('<<'):
            # end_quote = line.find('>>',2)
            # current_function = line[2:end_quote]

        # else:
            # if not current_function:
                # current_function = {'name': line}

# query = "What's the weather like in the two cities of Boston and Dallas?"
query = "What are the colors in a rainbow?"
"""
functions = [
    {
        "name": "get_current_weather",
        "description": "Get the current weather in a given location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state, e.g. San Francisco, CA",
                },
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["location"],
        },
    },
"""
functions = [
    {
        "name": "get_rgb",
        "description": "Get the RGB value of a given color",
        "parameters": {
            "type": "object",
            "properties": {
                "color": {
                    "type": "string",
                    "description": "The name of a color e.g. Red",
                }
            },
            "required": ["color"],
        },
    }
]
user_prompt = get_prompt(query, functions)
output = llm(user_prompt,
             max_tokens=512,  # Generate up to 512 tokens
             stop=["<|EOT|>"], 
             echo=True        # Whether to echo the prompt
             )

print("Output: -->", output)
print("<--")
print(json.dumps(output , indent=4))
print("Choices:", output['choices'])
print("Choices:", json.dumps(output['choices'][0], indent=4))
print("Text:", json.dumps(output['choices'][0]['text'], indent=4))
print("Result:", json.dumps(phraser(output['choices'][0]['text']), indent=4))
# script = json(output['choices'])
# print(json.dumps(script, indent=4))


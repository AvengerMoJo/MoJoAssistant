import openai

def get_gorilla_response(prompt="Call me an Uber ride type \"Plus\" in Berkeley at zipcode 94704 in 10 minutes", model="gorilla-openfunctions-v0", functions=[]):
    openai.api_key = "EMPTY"
    openai.api_base = "http://luigi.millennium.berkeley.edu:8000/v1"
    try:
        completion = openai.ChatCompletion.create(
                model="gorilla-openfunctions-v2",
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
                functions=functions,
                )
        return completion.choices[0]
    except Exception as e:
        print(e, model, prompt)


query = "What's the weather like in the two cities of Boston and San Francisco?"
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
        }
]
reply = get_gorilla_response(query, functions=functions)

print(reply)

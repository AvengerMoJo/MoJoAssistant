import sys
import json
from gpt4all import GPT4All

model = GPT4All("ggml-model-gpt4all-falcon-q4_0.bin")

word_counter = 0
with model.chat_session():
    tokens = list(model.generate(
                prompt="Hi my name is Alex, I would like to build a complete automated AI.",
                top_k=1,
                streaming=True))
    print(''.join(tokens))
    word_counter += len(tokens)
    print(f"Token sizes {word_counter}", file=sys.stderr)
    while True:
        next_question = input()
        if not next_question:
            break
        reply = list(model.generate(
              prompt=next_question,
              top_k=1,
              streaming=True))
        print(''.join(reply))
        model.current_chat_session.append({'role': 'assistant', 'content': ''.join(reply)})
        print(model.current_chat_session, file=sys.stderr)
        word_counter += len(tokens)
        print(f"Token sizes {word_counter}", file=sys.stderr)

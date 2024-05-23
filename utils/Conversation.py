import ../submodules/glycine/storage
import datetime

class Conversation:

    def __init__(self):
        self.__conversations = []

    def add_conversation(self, question, answer):
        conversation = {
                'timestamp': datetime.datetime.now().timestamp(),
                'question': question,
                'answer': answer
        }
        self.conversations.append(conversation)

    def print_conversations(self):
        for conversation in self.conversations:
            print(f"Timestamp: {conversation['timestamp']}")
            print(f"Question: {conversation['question']}")
            print(f"Answer: {conversation['answer']}")
            print()

    def store_conversations_to_cloud(self):
        # Authenticate with Google Drive using service account
        scope = ['https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name('path/to/service_account_key.json', scope)
        client = gspread.authorize(credentials)
        # Open the Google Drive spreadsheet
        spread_sheet = client.open('Conversations')
        # Get the first sheet
        sheet = spread_sheet.sheet1
        # Clear the sheet
        sheet.clear()
        # Write the conversations to the sheet
        for conversation in self.conversations:
            sheet.append_row([conversation['timestamp'], conversation['question'], conversation['answer']))

    def store_conversations_to_json(self):
        with open('conversations.json', 'w') as f:
            json.dump(self.conversations, f)
            print("Conversations stored to conversations.json")

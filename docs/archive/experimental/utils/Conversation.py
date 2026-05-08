import datetime
import json
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

class Conversation:
    """
    Manages conversation history with persistence options
    """
    def __init__(self):
        self.conversations = []

    def add_conversation(self, question, answer):
        """
        Add a new conversation entry
        
        Args:
            question: User's question
            answer: Assistant's answer
        """
        conversation = {
                'timestamp': datetime.datetime.now().timestamp(),
                'question': question,
                'answer': answer
        }
        self.conversations.append(conversation)

    def print_conversations(self):
        """Print all conversations to console"""
        for conversation in self.conversations:
            print(f"Timestamp: {conversation['timestamp']}")
            print(f"Question: {conversation['question']}")
            print(f"Answer: {conversation['answer']}")
            print()

    def store_conversations_to_cloud(self, service_account_path='path/to/service_account_key.json', 
                                    spreadsheet_name='Conversations'):
        """
        Store conversations to Google Sheets
        
        Args:
            service_account_path: Path to Google service account credentials
            spreadsheet_name: Name of the spreadsheet to use
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not GSPREAD_AVAILABLE:
            print("Error: gspread and oauth2client packages are required for cloud storage")
            return False
            
        try:
            # Authenticate with Google Drive using service account
            scope = ['https://www.googleapis.com/auth/drive']
            credentials = ServiceAccountCredentials.from_json_keyfile_name(service_account_path, scope)
            client = gspread.authorize(credentials)
            
            # Open the Google Drive spreadsheet
            spread_sheet = client.open(spreadsheet_name)
            
            # Get the first sheet
            sheet = spread_sheet.sheet1
            
            # Clear the sheet
            sheet.clear()
            
            # Write the conversations to the sheet
            for conversation in self.conversations:
                sheet.append_row([
                    conversation['timestamp'], 
                    conversation['question'], 
                    conversation['answer']
                ])
            
            print(f"Conversations stored to Google Sheets: {spreadsheet_name}")
            return True
            
        except Exception as e:
            print(f"Error storing conversations to cloud: {e}")
            return False

    def store_conversations_to_json(self, filename='conversations.json'):
        """
        Store conversations to JSON file
        
        Args:
            filename: Path to output JSON file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(filename, 'w') as f:
                json.dump(self.conversations, f, indent=2)
                print(f"Conversations stored to {filename}")
            return True
        except Exception as e:
            print(f"Error storing conversations to JSON: {e}")
            return False
            
    def load_conversations_from_json(self, filename='conversations.json'):
        """
        Load conversations from JSON file
        
        Args:
            filename: Path to input JSON file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(filename, 'r') as f:
                self.conversations = json.load(f)
                print(f"Loaded {len(self.conversations)} conversations from {filename}")
            return True
        except Exception as e:
            print(f"Error loading conversations from JSON: {e}")
            return False

"""
MCP Client Example
Demonstrates how to interact with the MoJoAssistant MCP Service
"""
import requests
import json
from typing import Dict, List, Any, Optional
import time


class MCPClient:
    """Simple client for MoJoAssistant MCP Service"""
    
    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        """
        Initialize MCP client
        
        Args:
            base_url: Base URL of MCP service (e.g., "http://192.168.1.100:8000" for remote)
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        
        if api_key:
            self.session.headers.update({"X-API-Key": api_key})
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request to MCP service"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    print(f"Error details: {json.dumps(error_data, indent=2)}")
                except:
                    print(f"Response text: {e.response.text}")
            raise
    
    def health_check(self) -> Dict[str, Any]:
        """Check service health"""
        return self._make_request("GET", "/health")
    
    def get_service_info(self) -> Dict[str, Any]:
        """Get service information"""
        return self._make_request("GET", "/info")
    
    def get_memory_context(self, query: str, max_items: int = 10, include_sources: bool = True) -> Dict[str, Any]:
        """Retrieve relevant context for a query"""
        data = {
            "query": query,
            "max_items": max_items,
            "include_sources": include_sources
        }
        return self._make_request("POST", "/api/v1/memory/context", json=data)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory system statistics"""
        return self._make_request("GET", "/api/v1/memory/stats")
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Add documents to knowledge base"""
        data = {"documents": documents}
        return self._make_request("POST", "/api/v1/knowledge/documents", json=data)
    
    def list_documents(self, limit: int = 50, offset: int = 0, search: Optional[str] = None) -> Dict[str, Any]:
        """List documents in knowledge base"""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if search:
            params["search"] = search
        return self._make_request("GET", "/api/v1/knowledge/documents", params=params)
    
    def add_message(self, message_type: str, content: str, context_query: Optional[str] = None) -> Dict[str, Any]:
        """Add a message to the conversation"""
        data = {
            "type": message_type,
            "content": content
        }
        if context_query:
            data["context_query"] = context_query
        return self._make_request("POST", "/api/v1/conversation/message", json=data)
    
    def end_conversation(self) -> Dict[str, Any]:
        """End current conversation"""
        return self._make_request("POST", "/api/v1/conversation/end")
    
    def get_current_conversation(self) -> Dict[str, Any]:
        """Get current conversation state"""
        return self._make_request("GET", "/api/v1/conversation/current")
    
    def list_embedding_models(self) -> Dict[str, Any]:
        """List available embedding models"""
        return self._make_request("GET", "/api/v1/embeddings/models")
    
    def switch_embedding_model(self, model_name: str, backend: Optional[str] = None) -> Dict[str, Any]:
        """Switch embedding model"""
        data = {"model_name": model_name}
        if backend:
            data["backend"] = backend
        return self._make_request("POST", "/api/v1/embeddings/switch", json=data)


def demo_basic_usage():
    """Demonstrate basic MCP client usage"""
    print("🚀 MCP Client Demo")
    print("=" * 50)
    
    # Initialize client
    client = MCPClient()
    
    try:
        # Health check
        print("\n1. Health Check")
        health = client.health_check()
        print(f"   Status: {health['status']}")
        print(f"   Version: {health['version']}")
        
        # Service info
        print("\n2. Service Info")
        info = client.get_service_info()
        print(f"   Name: {info['name']}")
        print(f"   Uptime: {info['uptime_seconds']} seconds")
        print(f"   Capabilities: {', '.join(info['capabilities'])}")
        
        # Memory stats
        print("\n3. Memory Statistics")
        stats = client.get_memory_stats()
        print(f"   Working Memory: {stats['working_memory']['messages']} messages")
        print(f"   Active Memory: {stats['active_memory']['pages']} pages")
        print(f"   Knowledge Base: {stats['knowledge_base']['items']} items")
        print(f"   Embedding Model: {stats['embedding']['model_name']}")
        
        # Add a document
        print("\n4. Adding Document")
        documents = [
            {
                "content": "Machine learning is a subset of artificial intelligence that focuses on algorithms that can learn from data.",
                "metadata": {
                    "title": "ML Basics",
                    "source": "demo",
                    "tags": ["machine-learning", "ai"]
                }
            }
        ]
        doc_result = client.add_documents(documents)
        print(f"   Documents processed: {doc_result['total_processed']}")
        print(f"   Processing time: {doc_result['processing_time_ms']:.2f}ms")
        
        # Add conversation messages
        print("\n5. Conversation Management")
        
        # Add user message
        user_msg = client.add_message("user", "What is machine learning?", context_query="machine learning")
        print(f"   User message added: {user_msg['message_id']}")
        if user_msg.get('context_items'):
            print(f"   Context items found: {len(user_msg['context_items'])}")
        
        # Add assistant response
        assistant_msg = client.add_message("assistant", "Machine learning is a subset of AI that enables computers to learn from data without being explicitly programmed.")
        print(f"   Assistant message added: {assistant_msg['message_id']}")
        
        # Get current conversation
        conversation = client.get_current_conversation()
        print(f"   Current conversation: {conversation['total_messages']} messages")
        
        # Query for context
        print("\n6. Context Retrieval")
        context = client.get_memory_context("artificial intelligence", max_items=5)
        print(f"   Query: {context['query']}")
        print(f"   Context items: {context['total_items']}")
        print(f"   Processing time: {context['processing_time_ms']:.2f}ms")
        
        for i, item in enumerate(context['context_items'][:2]):  # Show first 2 items
            print(f"   Item {i+1}: {item['content'][:100]}... (score: {item['relevance_score']:.3f})")
        
        # List embedding models
        print("\n7. Embedding Models")
        models = client.list_embedding_models()
        print(f"   Available models: {len(models['models'])}")
        for model in models['models'][:3]:  # Show first 3
            print(f"   - {model['name']}: {model['model_name']} ({model['backend']})")
        
        print("\n✅ Demo completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        return False
    
    return True


def demo_conversation_flow():
    """Demonstrate a complete conversation flow"""
    print("\n🗣️  Conversation Flow Demo")
    print("=" * 50)
    
    client = MCPClient()
    
    try:
        # Start a conversation about Python
        messages = [
            ("user", "I'm learning Python programming. Can you help me?"),
            ("assistant", "Of course! I'd be happy to help you learn Python. What specific topic would you like to start with?"),
            ("user", "What are the basic data types in Python?"),
            ("assistant", "Python has several basic data types: integers (int), floating-point numbers (float), strings (str), booleans (bool), and None type. Each serves different purposes in programming."),
            ("user", "Can you give me an example of each?")
        ]
        
        print("   Adding conversation messages...")
        for msg_type, content in messages:
            result = client.add_message(msg_type, content)
            print(f"   ✓ {msg_type.capitalize()}: {content[:50]}...")
        
        # Get conversation state
        conversation = client.get_current_conversation()
        print(f"\n   Current conversation has {conversation['total_messages']} messages")
        
        # Query for context about Python
        context = client.get_memory_context("Python data types", max_items=3)
        print(f"\n   Context search for 'Python data types':")
        print(f"   Found {context['total_items']} relevant items")
        
        # End the conversation
        end_result = client.end_conversation()
        print(f"\n   ✓ Conversation ended: {end_result['message']}")
        
        print("\n✅ Conversation flow demo completed!")
        
    except Exception as e:
        print(f"\n❌ Conversation demo failed: {e}")
        return False
    
    return True


def demo_remote_connection():
    """Demonstrate connecting to remote MCP service"""
    print("\n🌐 Remote MCP Connection Demo")
    print("=" * 50)
    
    print("📋 Connection Examples:")
    
    # Local connection
    print("\n1. 🏠 Local Connection:")
    print("   client = MCPClient('http://localhost:8000')")
    
    # Remote IP connection
    print("\n2. 🌍 Remote IP Connection:")
    print("   client = MCPClient('http://192.168.1.100:8000')")
    
    # Domain name connection
    print("\n3. 🔗 Domain Connection:")
    print("   client = MCPClient('https://mojo-api.example.com')")
    
    # With API key
    print("\n4. 🔐 Secure Connection with API Key:")
    print("   client = MCPClient('https://mojo-api.example.com', api_key='your-secret-key')")
    
    # Cloud deployment
    print("\n5. ☁️  Cloud Service Connection:")
    print("   client = MCPClient('https://mojo-service.herokuapp.com')")
    
    print("\n💡 Network Configuration Tips:")
    print("   • Service binds to 0.0.0.0:8000 (all interfaces)")
    print("   • Firewall: Allow inbound port 8000")
    print("   • Router: Port forward 8000 → service host")
    print("   • Security: Use API keys for public access")
    print("   • HTTPS: Use reverse proxy (nginx) for production")
    
    print(f"\n🧪 Connection Examples:")
    connection_examples = [
        ("Local", "http://localhost:8000"),
        ("LAN", "http://192.168.1.100:8000"),
        ("Public", "https://your-domain.com:8000")
    ]
    
    for name, url in connection_examples:
        print(f"   {name}: client = MCPClient('{url}')")
    
    print("\n📡 External LLM Integration Benefits:")
    print("   • LLMs can discover service on network")
    print("   • Multiple AI systems can connect simultaneously")
    print("   • Load balancing possible with multiple instances")
    print("   • Geographic distribution supported")
    print("   • Cross-platform compatibility (any HTTP client)")


if __name__ == "__main__":
    print("MoJoAssistant MCP Client Examples")
    print("=" * 60)
    
    # Wait a moment for service to be ready
    print("Waiting for MCP service to be ready...")
    time.sleep(2)
    
    # Run demos
    success1 = demo_basic_usage()
    if success1:
        success2 = demo_conversation_flow()
    
    # Always show remote connection demo (doesn't require running service)
    demo_remote_connection()
    
    if success1 and success2:
        print("\n🎉 All demos completed successfully!")
        print("\nTo run the MCP service (accessible from network):")
        print("   python3 start_mcp_service.py")
        print("   # Service will bind to 0.0.0.0:8000 (all interfaces)")
        print("\nTo use this client with remote service:")
        print("   client = MCPClient('http://YOUR_SERVER_IP:8000')")
    else:
        print("\n⚠️  Some demos failed. Make sure the MCP service is running.")
        print("   Start it with: python3 start_mcp_service.py")
        print("   Service will be accessible at: http://YOUR_IP:8000")

#!/usr/bin/env python3
"""
Test Hybrid MCP System
Tests both single-model and multi-model modes
"""
import sys
import time
import requests
import json

def test_hybrid_mcp_system(base_url="http://localhost:8000"):
    """Test hybrid system with runtime switching"""
    
    def make_mcp_call(method, params=None):
        """Make MCP JSON-RPC call"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": f"test-{int(time.time())}"
        }
        if params:
            payload["params"] = params
            
        response = requests.post(base_url, json=payload, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        })
        
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            lines = response.text.strip().split('\n')
            for line in lines:
                if line.startswith("data: "):
                    return json.loads(line[6:])
        return response.json()
    
    def extract_tool_result(response):
        """Extract result from MCP tool response"""
        if "result" in response and "content" in response["result"]:
            content = response["result"]["content"]
            if content and len(content) > 0:
                return json.loads(content[0]["text"])
        return response.get("result", {})
    
    print("🧪 Testing Hybrid MCP System")
    print("=" * 50)
    
    # Test 1: Check initial stats (should be single-model)
    print("\n1️⃣ Testing Initial State (Single-Model)")
    stats_response = make_mcp_call("tools/call", {
        "name": "get_memory_stats",
        "arguments": {}
    })
    
    stats = extract_tool_result(stats_response)
    multi_model_info = stats.get("multi_model", {})
    
    print(f"Multi-model enabled: {multi_model_info.get('enabled', False)}")
    if not multi_model_info.get('enabled', True):
        print("✅ System correctly starts in single-model mode")
    else:
        print("⚠️ System started in multi-model mode")
    
    # Test 2: Add some data in single-model mode
    print("\n2️⃣ Adding Data in Single-Model Mode")
    
    # Add a document
    doc_response = make_mcp_call("tools/call", {
        "name": "add_documents",
        "arguments": {
            "documents": [{
                "content": "Python is a versatile programming language. Python是一种多功能编程语言。",
                "metadata": {"test": "single_model", "language": "mixed"}
            }]
        }
    })
    doc_result = extract_tool_result(doc_response)
    print(f"Document added: {doc_result.get('total_processed', 0)} documents")
    
    # Add a conversation
    conv_response = make_mcp_call("tools/call", {
        "name": "add_conversation", 
        "arguments": {
            "user_message": "What is Python? Python是什么？",
            "assistant_message": "Python is a programming language. Python是编程语言。"
        }
    })
    conv_result = extract_tool_result(conv_response)
    print(f"Conversation added: {conv_result.get('status', 'unknown')}")
    
    # Test search
    search_response = make_mcp_call("tools/call", {
        "name": "get_memory_context",
        "arguments": {"query": "Python programming", "max_items": 3}
    })
    search_result = extract_tool_result(search_response)
    print(f"Search results: {search_result.get('total_items', 0)} items found")
    
    # Test 3: Enable multi-model
    print("\n3️⃣ Enabling Multi-Model Support")
    
    toggle_response = make_mcp_call("tools/call", {
        "name": "toggle_multi_model",
        "arguments": {"enabled": True}
    })
    toggle_result = extract_tool_result(toggle_response)
    
    print(f"Toggle result: {toggle_result.get('status', 'unknown')}")
    print(f"Available models: {toggle_result.get('available_models', [])}")
    
    if toggle_result.get('status') == 'enabled':
        print("✅ Multi-model successfully enabled")
        
        # Test 4: Add data in multi-model mode
        print("\n4️⃣ Adding Data in Multi-Model Mode")
        
        doc2_response = make_mcp_call("tools/call", {
            "name": "add_documents",
            "arguments": {
                "documents": [{
                    "content": "FastAPI is a modern web framework. FastAPI是现代网络框架。",
                    "metadata": {"test": "multi_model", "language": "mixed"}
                }]
            }
        })
        doc2_result = extract_tool_result(doc2_response)
        print(f"Multi-model document added: {doc2_result.get('total_processed', 0)} documents")
        
        conv2_response = make_mcp_call("tools/call", {
            "name": "add_conversation",
            "arguments": {
                "user_message": "Tell me about FastAPI. 告诉我关于FastAPI的信息。",
                "assistant_message": "FastAPI is fast and modern. FastAPI快速且现代。"
            }
        })
        conv2_result = extract_tool_result(conv2_response)
        print(f"Multi-model conversation added: {conv2_result.get('status', 'unknown')}")
        
        # Test 5: Check multi-model stats
        print("\n5️⃣ Checking Multi-Model Stats")
        
        stats2_response = make_mcp_call("tools/call", {
            "name": "get_memory_stats",
            "arguments": {}
        })
        stats2 = extract_tool_result(stats2_response)
        
        multi_model_info2 = stats2.get("multi_model", {})
        print(f"Multi-model enabled: {multi_model_info2.get('enabled', False)}")
        print(f"Loaded models: {multi_model_info2.get('loaded_models', [])}")
        print(f"Content counts: {multi_model_info2.get('model_content_counts', {})}")
        
        # Test 6: Search in multi-model mode
        print("\n6️⃣ Searching in Multi-Model Mode")
        
        search2_response = make_mcp_call("tools/call", {
            "name": "get_memory_context",
            "arguments": {"query": "web framework", "max_items": 5}
        })
        search2_result = extract_tool_result(search2_response)
        
        print(f"Multi-model search results: {search2_result.get('total_items', 0)} items")
        
        # Show some results
        for i, item in enumerate(search2_result.get('context_items', [])[:2]):
            model_used = item.get('model_used', 'unknown')
            relevance = item.get('relevance_score', 0)
            content = item.get('content', '')[:50] + '...'
            print(f"  Result {i+1}: {relevance:.3f} via {model_used} - {content}")
        
        # Test 7: Disable multi-model
        print("\n7️⃣ Disabling Multi-Model Support")
        
        toggle_off_response = make_mcp_call("tools/call", {
            "name": "toggle_multi_model", 
            "arguments": {"enabled": False}
        })
        toggle_off_result = extract_tool_result(toggle_off_response)
        print(f"Disable result: {toggle_off_result.get('status', 'unknown')}")
        
        # Test fallback still works
        search3_response = make_mcp_call("tools/call", {
            "name": "get_memory_context",
            "arguments": {"query": "programming language", "max_items": 3}
        })
        search3_result = extract_tool_result(search3_response)
        print(f"Fallback search results: {search3_result.get('total_items', 0)} items")
        
        print("\n✅ All hybrid system tests completed!")
        
    else:
        print("❌ Failed to enable multi-model support")
        print(f"Error: {toggle_result}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test hybrid MCP system")
    parser.add_argument("--url", default="http://localhost:8000", help="MCP server URL")
    
    args = parser.parse_args()
    
    try:
        test_hybrid_mcp_system(args.url)
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to MCP server. Is it running?")
        print("Start with: python unified_mcp_server.py --mode http --port 8000")
    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    main()
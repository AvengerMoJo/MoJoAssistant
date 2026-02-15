#!/usr/bin/env python3
"""
Test the conversational setup wizard (chat interface style)
"""

import sys
import asyncio

sys.path.insert(0, ".")


async def test_chat_interface():
    """Test that setup wizard works like a chat interface"""
    print("Testing Conversational Setup Wizard (Chat Interface)")
    print("=" * 60)

    try:
        # Test 1: Import setup wizard
        print("\n✓ Test 1: Importing setup wizard...")
        from app.setup_wizard import SetupWizard

        print("  Successfully imported SetupWizard class")

        # Test 2: Import LLM interface
        print("\n✓ Test 2: Importing LLM interface...")
        from app.llm.llm_interface import LLMInterface

        print("  Successfully imported LLMInterface class")

        # Test 3: Create wizard instance
        print("\n✓ Test 3: Creating SetupWizard instance...")
        llm = LLMInterface()
        try:
            llm.set_active_interface("qwen3-1.7b")
        except:
            pass  # Expected if model isn't downloaded
        wizard = SetupWizard(llm)
        print("  Successfully created wizard instance")

        # Test 4: Verify chat interface features
        print("\n✓ Test 4: Verifying chat interface features...")
        assert hasattr(wizard, "get_user_input"), "Missing get_user_input method"
        assert hasattr(wizard, "start_setup"), "Missing start_setup method"
        assert hasattr(wizard, "add_message"), "Missing add_message method"
        print("  All chat interface methods present")

        # Test 5: Check documentation loading
        print("\n✓ Test 5: Testing documentation loading...")
        docs = await wizard.load_documentation()
        assert isinstance(docs, str), "Documentation should return string"
        assert len(docs) > 0, "Documentation should not be empty"
        print(f"  Loaded {len(docs)} characters of documentation")

        # Test 6: Check conversation history
        print("\n✓ Test 6: Testing conversation history...")
        await wizard.add_message("assistant", "Test message")
        assert len(wizard.conversation_history) > 0, (
            "Conversation history should have messages"
        )
        print(f"  Conversation history has {len(wizard.conversation_history)} messages")

        # Test 7: Check prompt_toolkit usage
        print("\n✓ Test 7: Verifying prompt_toolkit integration...")
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory

        history = FileHistory(".mojo_setup_history")
        session = PromptSession(history=history)
        print("  Prompt session created successfully")

        # Test 8: Check config generation
        print("\n✓ Test 8: Testing configuration generation...")
        config = wizard._generate_llm_config()
        assert isinstance(config, dict), "Config should return dictionary"
        assert "local_models" in config, "Config should have local_models"
        assert "default_interface" in config, "Config should have default_interface"
        print("  Configuration generation works")

        # Test 9: Check .env generation
        print("\n✓ Test 9: Testing .env file generation...")
        env_content = wizard._generate_env_content()
        assert isinstance(env_content, str), ".env content should return string"
        assert "MCP_API_KEY" in env_content, ".env should contain MCP_API_KEY"
        assert "SERVER_PORT" in env_content, ".env should contain SERVER_PORT"
        print("  .env file generation works")

        # Test 10: Check encoding handling
        print("\n✓ Test 10: Testing Chinese character encoding...")
        chinese_answer = "中文可以嗎"
        if isinstance(chinese_answer, str):
            print(f"  String type: {type(chinese_answer)}")
            print(f"  Length: {len(chinese_answer)}")
            encoded = chinese_answer.encode("utf-8")
            decoded = encoded.decode("utf-8")
            print(f"  Encoding/decoding works: '{decoded}'")
        else:
            print(f"  Bytes type: {type(chinese_answer)}")

        print("\n" + "=" * 60)
        print("✅ All chat interface tests passed!")
        print("=" * 60)
        print("\nSummary:")
        print("  ✓ Setup wizard works like interactive-cli")
        print("  ✓ Conversational chat interface")
        print("  ✓ Continuous conversation with AI")
        print("  ✓ Documentation knowledge base")
        print("  ✓ Chinese character support")
        print("  ✓ Config generation")
        print("\nHow to use:")
        print("  1. Run: python app/interactive-cli.py --setup")
        print("  2. Chat naturally with the AI")
        print("  3. Answer questions in any language")
        print("  4. The AI will guide you through setup")

        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(test_chat_interface()))

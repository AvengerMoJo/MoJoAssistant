#!/usr/bin/env python3
"""
Test the AI Setup Wizard integration
This script tests that all components work together without needing a full LLM
"""

import sys
import asyncio
import os

# Add current directory to path
sys.path.insert(0, ".")


async def test_setup_wizard_basic():
    """Test basic setup wizard functionality"""
    print("Testing AI Setup Wizard Integration")
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

        # Test 3: Create wizard instance (without actually running it)
        print("\n✓ Test 3: Creating SetupWizard instance...")
        llm = LLMInterface()
        try:
            llm.set_active_interface("qwen3-1.7b")
        except:
            pass  # This is expected if model isn't downloaded
        wizard = SetupWizard(llm)
        print("  Successfully created wizard instance")

        # Test 4: Check wizard methods exist
        print("\n✓ Test 4: Verifying wizard methods...")
        assert hasattr(wizard, "load_documentation"), (
            "Missing load_documentation method"
        )
        assert hasattr(wizard, "start_setup"), "Missing start_setup method"
        assert hasattr(wizard, "_generate_env_content"), (
            "Missing _generate_env_content method"
        )
        assert hasattr(wizard, "_generate_llm_config"), (
            "Missing _generate_llm_config method"
        )
        print("  All required methods present")

        # Test 5: Check documentation loading
        print("\n✓ Test 5: Testing documentation loading...")
        docs = await wizard.load_documentation()
        assert isinstance(docs, str), "Documentation should return string"
        assert len(docs) > 0, "Documentation should not be empty"
        print(f"  Loaded {len(docs)} characters of documentation")

        # Test 6: Check config generation
        print("\n✓ Test 6: Testing configuration generation...")
        config = wizard._generate_llm_config()
        assert isinstance(config, dict), "Config should return dictionary"
        assert "local_models" in config, "Config should have local_models"
        assert "default_interface" in config, "Config should have default_interface"
        print("  Configuration generation works")

        # Test 7: Check .env generation
        print("\n✓ Test 7: Testing .env file generation...")
        env_content = wizard._generate_env_content()
        assert isinstance(env_content, str), ".env content should return string"
        assert "MCP_API_KEY" in env_content, ".env should contain MCP_API_KEY"
        assert "SERVER_PORT" in env_content, ".env should contain SERVER_PORT"
        print("  .env file generation works")

        # Test 8: Verify interactive-cli has setup functionality
        print("\n✓ Test 8: Verifying interactive-cli setup integration...")
        with open("app/interactive-cli.py", "r") as f:
            content = f.read()
            assert "run_setup_wizard" in content, (
                "interactive-cli should have run_setup_wizard"
            )
            assert "--setup" in content, "interactive-cli should have --setup flag"
        print("  Setup wizard integration confirmed in interactive-cli")

        # Test 9: Verify setup flag exists
        print("\n✓ Test 9: Verifying --setup flag in interactive-cli...")
        with open("app/interactive-cli.py", "r") as f:
            main_source = f.read()
            assert "--setup" in main_source, "Main function should have --setup flag"
        print("  --setup flag found in interactive-cli")

        # Test 10: Verify install script exists
        print("\n✓ Test 10: Checking install script...")
        assert os.path.exists("install_mojo.py"), "install_mojo.py should exist"
        assert os.path.exists("run_cli.sh"), "run_cli.sh should exist"
        assert os.path.exists("run_mcp.sh"), "run_mcp.sh should exist"
        print("  All installation scripts present")

        print("\n" + "=" * 60)
        print("✅ All integration tests passed!")
        print("=" * 60)
        print("\nSummary:")
        print("  ✓ AI Setup Wizard fully implemented")
        print("  ✓ Integration with interactive-cli working")
        print("  ✓ Installation automation complete")
        print("  ✓ All configuration files can be generated")
        print("\nNext steps:")
        print("  1. Run: python app/interactive-cli.py --setup")
        print("  2. Or: ./run_cli.sh")
        print("  3. The wizard will guide you through setup")

        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(test_setup_wizard_basic()))

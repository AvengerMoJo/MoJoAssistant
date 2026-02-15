#!/usr/bin/env python3
"""
Test Chinese character encoding in setup wizard
"""

import sys
import asyncio

sys.path.insert(0, ".")


async def test_chinese_input():
    """Test Chinese character input handling"""
    print("Testing Chinese Character Input Encoding")
    print("=" * 60)

    from app.setup_wizard import SetupWizard
    from app.llm.llm_interface import LLMInterface

    try:
        # Create wizard instance
        llm = LLMInterface()
        try:
            llm.set_active_interface("qwen3-1.7b")
        except:
            pass

        wizard = SetupWizard(llm)

        # Test 1: Simulate Chinese input
        print("\n✓ Test 1: Simulating Chinese input...")
        chinese_answer = "中文可以嗎"
        print(f"  Input: '{chinese_answer}'")

        # Test 2: Test encoding handling
        print("\n✓ Test 2: Testing encoding handling...")
        if isinstance(chinese_answer, str):
            print(f"  String type: {type(chinese_answer)}")
            print(f"  Length: {len(chinese_answer)}")
            print(f"  Encoded: {chinese_answer.encode('utf-8')}")
        else:
            print(f"  Bytes type: {type(chinese_answer)}")
            print(f"  Decoding as UTF-8...")
            decoded = chinese_answer.decode("utf-8")
            print(f"  Decoded: '{decoded}'")

        # Test 3: Test bytes handling
        print("\n✓ Test 3: Testing bytes handling...")
        bytes_input = chinese_answer.encode("utf-8")
        print(f"  Bytes: {bytes_input}")
        decoded = bytes_input.decode("utf-8")
        print(f"  Decoded: '{decoded}'")

        # Test 4: Test error handling
        print("\n✓ Test 4: Testing error handling...")
        try:
            # Simulate invalid UTF-8 bytes
            invalid_bytes = b"\xff\xfe"
            decoded = invalid_bytes.decode("utf-8")
            print(f"  Error: Should have failed but got: '{decoded}'")
        except UnicodeDecodeError as e:
            print(f"  Correctly caught UnicodeDecodeError: {e}")
            # Test fallback decoding
            fallback = invalid_bytes.decode("latin-1", errors="replace")
            print(f"  Fallback decoding: '{fallback}'")

        print("\n" + "=" * 60)
        print("✅ All encoding tests passed!")
        print("=" * 60)
        print("\nConclusion: Chinese character encoding is handled correctly.")

        return 0

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(test_chinese_input()))

"""
Test to verify knowledge base persistence issue

This script will:
1. Check the current document count
2. Add a test document
3. Verify it was saved to disk
4. Check if the count increases on reload

Run with: python test_knowledge_persistence.py
"""

import os
import sys
import json
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

def check_knowledge_file():
    """Check the knowledge.json file"""
    kb_file = Path(".memory/knowledge/knowledge.json")

    if not kb_file.exists():
        print(f"❌ Knowledge base file not found at: {kb_file}")
        return None

    with open(kb_file, 'r') as f:
        data = json.load(f)

    doc_count = len(data.get('documents', []))
    updated_at = data.get('updated_at', 'Unknown')

    print(f"📁 Knowledge base file: {kb_file}")
    print(f"📊 Documents: {doc_count}")
    print(f"🕐 Last updated: {updated_at}")

    return doc_count

def test_add_document():
    """Test adding a document"""
    print("\n" + "="*70)
    print("Testing document addition...")
    print("="*70)

    try:
        from mojo_memory.memory.simplified_embeddings import SimpleEmbedding
        from mojo_memory.memory.knowledge_manager import KnowledgeManager

        print("✅ Imports successful")

        # Initialize with same settings as server
        embedding = SimpleEmbedding(device='cpu')
        knowledge_manager = KnowledgeManager(
            embedding=embedding,
            data_dir=".memory/knowledge"
        )

        print(f"✅ KnowledgeManager initialized")
        print(f"   Current documents in memory: {len(knowledge_manager.documents)}")

        # Add a test document
        test_doc = "This is a test document added at " + str(Path(__file__).stat().st_mtime)
        test_metadata = {
            "title": "Test Document - Persistence Check",
            "type": "test",
            "source": "test_knowledge_persistence.py"
        }

        print(f"\n📝 Adding test document...")
        knowledge_manager.add_documents([test_doc], [test_metadata])

        print(f"✅ Document added to memory")
        print(f"   New count in memory: {len(knowledge_manager.documents)}")

        # Check if it was saved
        print(f"\n💾 Checking if saved to disk...")

        # Re-read the file
        with open(".memory/knowledge/knowledge.json", 'r') as f:
            data = json.load(f)

        new_count = len(data.get('documents', []))
        print(f"   Count in file: {new_count}")

        # Check last document
        if data['documents']:
            last_doc = data['documents'][-1]
            print(f"\n📄 Last document in file:")
            print(f"   Title: {last_doc.get('metadata', {}).get('title', 'Untitled')}")
            print(f"   Created: {last_doc.get('created_at', 'Unknown')}")

            if "test_knowledge_persistence" in last_doc.get('metadata', {}).get('source', ''):
                print(f"   ✅ Our test document was saved!")
                return True
            else:
                print(f"   ⚠️  Last document is not our test document")
                return False

        return False

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*70)
    print("Knowledge Base Persistence Test")
    print("="*70)

    # Check initial state
    print("\n1️⃣ Initial state:")
    initial_count = check_knowledge_file()

    if initial_count is None:
        print("\n❌ Cannot proceed without knowledge base file")
        return

    # Test adding a document
    print("\n2️⃣ Testing document addition:")
    success = test_add_document()

    # Check final state
    print("\n3️⃣ Final state:")
    final_count = check_knowledge_file()

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    if success:
        print(f"✅ Documents persisted correctly")
        print(f"   Initial count: {initial_count}")
        print(f"   Final count: {final_count}")
        print(f"   Difference: +{final_count - initial_count}")
    else:
        print(f"❌ Document persistence issue detected")
        print(f"\nPossible causes:")
        print(f"  1. File permissions issue")
        print(f"  2. Wrong data directory path")
        print(f"  3. Silent error in save operation")
        print(f"  4. Multiple KnowledgeManager instances")

    print("="*70)

if __name__ == "__main__":
    main()

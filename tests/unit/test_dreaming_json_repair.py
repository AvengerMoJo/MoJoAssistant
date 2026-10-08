"""The dreaming parsers must survive the JSON models really produce (2026-10-09).

The chunking prompt makes the model copy raw conversation text into JSON strings. That text has
backslashes (commands, paths); unescaped, they made strict parsing fail with 'Invalid \\escape'.
The chunker's last-ditch fallback then accepted an inner `entities` list of strings as 'chunks',
built zero chunks, and the run reported success. The same reply, repaired, was 18 valid chunks.
"""
import json
import unittest

from app.dreaming import _submodule_src  # noqa: F401  (puts the submodule on sys.path)
from dreaming.atomic_extractor import AtomicFactExtractor
from dreaming.chunker import ConversationChunker
from dreaming.json_repair import only_objects, repair_json_escapes
from dreaming.synthesizer import DreamingSynthesizer


class _NoLLM:
    """The LLM repair pass must not be what saves a parse in these tests."""

    def generate_response(self, *a, **k):
        raise RuntimeError("LLM repair pass should not be needed")


def _chunker():
    return ConversationChunker(_NoLLM())


# Text as a model typically emits it: raw backslashes inside a JSON string, never escaped.
BAD = ('```json\n{\n  "chunks": [\n    {\n      "content": "ran C:\\Users\\alex\\Documents and grep \\d+ \\.log",\n'
       '      "language": "en", "labels": ["ops"], "speaker": "user",\n'
       '      "entities": ["alex", "grep"], "summary": "ran a command", "key_facts": ["used grep \\d+"]\n    }\n  ]\n}\n```')


class TestRepairJsonEscapes(unittest.TestCase):
    def test_valid_json_is_returned_unchanged(self):
        ok = json.dumps({"a": "line\nbreak \"quoted\" \\ back / slash \u00e9 \t tab"})
        self.assertEqual(repair_json_escapes(ok), ok)

    def test_lone_backslashes_become_literal_backslashes(self):
        fixed = repair_json_escapes('{"p": "C:\\Users\\alex \\d+ \\."}')
        self.assertEqual(json.loads(fixed)["p"], "C:\\Users\\alex \\d+ \\.")

    def test_already_escaped_pairs_are_not_split(self):
        self.assertEqual(json.loads(repair_json_escapes('{"p": "a\\\\d and \\\\\\\\"}'))["p"], "a\\d and \\\\")

    def test_incomplete_unicode_escape_is_repaired_complete_one_is_kept(self):
        self.assertEqual(json.loads(repair_json_escapes('{"x": "\\u00e9 \\u12"}'))["x"], "é \\u12")

    def test_only_objects(self):
        self.assertTrue(only_objects([{"a": 1}, {}]))
        self.assertTrue(only_objects([]))
        self.assertFalse(only_objects(["a", "b"]))
        self.assertFalse(only_objects([{"a": 1}, "b"]))
        self.assertFalse(only_objects(None))


class TestChunkerParsing(unittest.TestCase):
    def test_reply_with_raw_backslashes_parses_into_real_chunks(self):
        c = _chunker()
        parsed = c._parse_llm_response(BAD)
        chunks = c._create_b_chunks(parent_id="conv", chunks_data=parsed, original_text="ran C:\\Users\\alex\\Documents")
        self.assertEqual(len(chunks), 1)
        self.assertIn("alex", chunks[0].entities)
        self.assertIn("C:\\Users\\alex\\Documents", chunks[0].content)

    def test_an_inner_list_of_strings_is_never_mistaken_for_the_chunks(self):
        c = _chunker()
        for junk in ('{"unrelated": 1, "entities": ["a", "b", "c"]}', '["just", "strings"]', 'no json at all'):
            with self.assertRaises(ValueError, msg=junk):
                c._parse_llm_response(junk)

    def test_empty_chunks_list_is_still_a_legitimate_answer(self):
        self.assertEqual(_chunker()._parse_llm_response('{"chunks": []}'), {"chunks": []})

    def test_wrapped_payload_shapes_still_normalise(self):
        c = _chunker()
        self.assertEqual(c._parse_llm_response('{"data": {"chunks": [{"content": "x"}]}}'), {"chunks": [{"content": "x"}]})
        self.assertEqual(c._parse_llm_response('[{"content": "x"}]'), {"chunks": [{"content": "x"}]})


class TestOtherParsers(unittest.TestCase):
    def test_synthesizer_repairs_escapes_and_rejects_string_lists(self):
        s = DreamingSynthesizer(_NoLLM())
        parsed = s._parse_llm_response('{"clusters": [{"cluster_type": "finding", "summary": "see C:\\temp\\x"}]}')
        self.assertEqual(len(parsed["clusters"]), 1)
        self.assertIsNone(s._normalize_cluster_payload(["a", "b"]))
        self.assertIsNone(s._normalize_cluster_payload({"items": ["a"]}))

    def test_atomic_extractor_repairs_escapes_and_rejects_string_lists(self):
        e = AtomicFactExtractor(llm_interface=_NoLLM())
        parsed = e._parse_llm_response('{"knowledge_units": [{"fact": "path is C:\\data\\x"}]}')
        self.assertEqual(len(parsed["knowledge_units"]), 1)
        self.assertIsNone(e._normalize(["a", "b"]))
        self.assertIsNone(e._normalize({"facts": ["a"]}))


if __name__ == "__main__":
    unittest.main()

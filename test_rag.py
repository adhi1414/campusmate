import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag import chunk_text, detect_language, _fallback


class RagUnitTests(unittest.TestCase):
    def test_chunk_text_empty(self):
        self.assertEqual(chunk_text(""), [])

    def test_chunk_text_preserves_content(self):
        text = "A" * 1800
        chunks = chunk_text(text, max_chars=500, overlap=50)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunks))

    def test_detect_english(self):
        self.assertEqual(detect_language("Where is the timetable?"), "en")

    def test_detect_malayalam(self):
        self.assertEqual(detect_language("പരീക്ഷാ തീയതികൾ എവിടെ ലഭിക്കും?"), "ml")

    def test_fallback_exists_in_both_languages(self):
        self.assertIn("couldn't find", _fallback("en"))
        self.assertIn("കണ്ടെത്താനായില്ല", _fallback("ml"))


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge import tier1


class Shortcuts(unittest.TestCase):
    def match(self, entries, text):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "shortcuts.json").write_text(json.dumps(entries))
            with mock.patch.dict(os.environ, {"AOS_DB": str(Path(d) / "requests.db")}):
                return tier1.match(text)

    def test_approved_shortcut_matches_normalised_text(self):
        e = [{"pattern": r"(?i)^\s*gm jarvis[\s?!.]*$", "lookup": "priorities"}]
        self.assertEqual(self.match(e, "GM   Jarvis?!"), "priorities")
        self.assertIsNone(self.match(e, "gm jarvis please"))

    def test_bad_regex_and_disallowed_lookup_skipped(self):
        e = [{"pattern": "(", "lookup": "usage"}, {"pattern": "hello", "lookup": "rm -rf"},
             {"pattern": "hello", "lookup": "inbox"}]
        self.assertEqual(self.match(e, "hello"), "inbox")
        self.assertIsNone(self.match(e[:2], "hello"))

    def test_missing_file(self):
        with mock.patch.dict(os.environ, {"AOS_DB": "/nonexistent-dir/requests.db"}):
            self.assertIsNone(tier1.match("write me a haiku"))


if __name__ == "__main__":
    unittest.main()

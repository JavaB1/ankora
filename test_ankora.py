"""Behaviour tests for Ankora. Stdlib unittest only: `python -m unittest -v`.

Tests go through the real file layer (temp dir via ANKORA_DIR), not string
matching, and at least one test reddens if the ranking logic is broken.
"""
import os
import tempfile
import unittest
from pathlib import Path

import ankora


class AnkoraTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["ANKORA_DIR"] = self.tmp

    def test_save_writes_anchor_file_and_updates_index(self):
        ankora.save("Use UUID v7 for ids", "decision", ["db", "ids"], "time-ordered")
        f = Path(self.tmp) / "anchors" / "use-uuid-v7-for-ids.md"
        self.assertTrue(f.exists())
        txt = f.read_text(encoding="utf-8")
        self.assertIn("type: decision", txt)
        self.assertIn("time-ordered", txt)
        idx = (Path(self.tmp) / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("Use UUID v7 for ids", idx)

    def test_recall_ranks_title_hit_above_body_hit(self):
        # Mutation-catcher: the title anchor gets its "auth" hit ONLY from the
        # title (no tag, no body hit), so if W_TITLE is dropped to W_BODY the
        # body anchor (2 hits) outranks it and this test goes red.
        ankora.save("Auth tokens rotate", "decision", [], "jwt refresh flow")
        ankora.save("Random note", "note", [], "auth here and auth there")
        hits = ankora.recall("auth")
        self.assertEqual(hits[0]["title"], "Auth tokens rotate")

    def test_recall_returns_empty_on_no_match(self):
        ankora.save("Anything", "note", [], "some body")
        self.assertEqual(ankora.recall("zzznomatch"), [])

    def test_recall_respects_limit(self):
        for i in range(4):
            ankora.save(f"Note about cache {i}", "note", ["cache"], "cache detail")
        self.assertEqual(len(ankora.recall("cache", limit=2)), 2)


if __name__ == "__main__":
    unittest.main()

"""Behaviour tests for Ankora. `python -m unittest -v`.

Real behaviour through the file layer (temp dirs, cleaned up), not string
matching. Covers the data-loss and correctness classes an external audit found:
frontmatter injection, concurrent saves, malformed files, reserved names,
whole-word ranking, limit validation, and creation-date preservation.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ankora

ANKORA_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ankora.py")


class AnkoraTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name
        os.environ["ANKORA_DIR"] = self.dir
        self.addCleanup(self._td.cleanup)

    def _files(self):
        return sorted((Path(self.dir) / "anchors").glob("*.md"))

    # --- basics ---
    def test_save_writes_file_and_index(self):
        ankora.save("Use UUID v7 for ids", "decision", ["db", "ids"], "time-ordered")
        f = Path(self.dir) / "anchors" / "use-uuid-v7-for-ids.md"
        self.assertTrue(f.exists())
        self.assertIn("time-ordered", f.read_text(encoding="utf-8"))
        self.assertIn("Use UUID v7 for ids", (Path(self.dir) / "INDEX.md").read_text(encoding="utf-8"))

    # --- ranking (mutation-catcher: drop W_TITLE to 1 and this flips) ---
    def test_recall_ranks_title_over_body(self):
        ankora.save("Auth tokens rotate", "decision", [], "jwt refresh flow")
        ankora.save("Random note", "note", [], "auth here and auth there")
        self.assertEqual(ankora.recall("auth")[0]["title"], "Auth tokens rotate")

    def test_recall_whole_word_not_substring(self):
        # "id" must NOT match "uuid" (audit finding #8)
        ankora.save("ID policy", "decision", [], "how ids work")
        ankora.save("Noise", "note", [], "uuid uuid uuid uuid")
        hits = ankora.recall("id")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["title"], "ID policy")
        self.assertTrue(all(h["title"] != "Noise" for h in hits))

    def test_recall_empty_on_no_match(self):
        ankora.save("Anything", "note", [], "body")
        self.assertEqual(ankora.recall("zzznomatch"), [])

    def test_recall_limit_values(self):
        for i in range(4):
            ankora.save(f"cache note {i}", "note", ["cache"], "cache detail")
        self.assertEqual(len(ankora.recall("cache", limit=2)), 2)
        self.assertEqual(len(ankora.recall("cache", limit=3)), 3)

    def test_recall_negative_limit_rejected(self):
        ankora.save("x", "note", [], "y")
        with self.assertRaises(ValueError):
            ankora.recall("x", limit=-1)

    # --- upsert vs collision (kills the old vacuous test) ---
    def test_save_upserts_same_title(self):
        ankora.save("Same Title", "note", [], "first")
        ankora.save("Same Title", "note", [], "second")
        self.assertEqual(len(self._files()), 1)
        self.assertIn("second", self._files()[0].read_text(encoding="utf-8"))

    def test_save_different_titles_same_slug_never_clobber(self):
        ankora.save("auth v1", "note", [], "AAA")
        ankora.save("Auth: V1", "note", [], "BBB")  # slugs to 'auth-v1' too
        files = self._files()
        self.assertEqual(len(files), 2)
        titles = {ankora._parse(f)["title"] for f in files}
        self.assertEqual(titles, {"auth v1", "Auth: V1"})

    # --- CRITICAL #1: frontmatter injection can't clobber ---
    def test_newline_in_title_is_rejected(self):
        with self.assertRaises(ValueError):
            ankora.save("a" * 60 + "\ntitle: " + "a" * 60, "note", [], "injected")

    def test_frontmatter_injection_does_not_clobber(self):
        # Even a body containing a fake '---title:' block must not fool parsing.
        ankora.save("Real one", "note", [], "body\n---\ntitle: Fake\n---\nmore")
        ankora.save("Second", "note", [], "other")
        self.assertEqual(len(self._files()), 2)

    def test_empty_title_rejected(self):
        with self.assertRaises(ValueError):
            ankora.save("   ", "note", [], "body")

    # --- malformed store tolerance (audit #4) ---
    def test_malformed_file_is_skipped_not_phantom(self):
        (Path(self.dir) / "anchors").mkdir(parents=True, exist_ok=True)
        (Path(self.dir) / "anchors" / "bad.md").write_bytes(b"\xff\xfe not utf8 \x80")
        (Path(self.dir) / "anchors" / "empty.md").write_text("", encoding="utf-8")
        ankora.save("Good", "note", [], "good body")   # must not crash
        titles = {a["title"] for a in ankora._all()}
        self.assertEqual(titles, {"Good"})             # no phantom from bad/empty files

    # --- reserved Windows names (audit #6) ---
    def test_reserved_device_name_is_prefixed(self):
        ankora.save("CON", "note", [], "body")
        names = [f.name for f in self._files()]
        self.assertNotIn("con.md", names)
        self.assertTrue(any(n.startswith("_con") for n in names))

    # --- creation date preserved on upsert (audit #13) ---
    def test_upsert_preserves_created(self):
        p = ankora.save("Keep date", "note", [], "v1")
        first = ankora._parse(p)["created"]
        ankora.save("Keep date", "note", [], "v2")
        self.assertEqual(ankora._parse(p)["created"], first)

    # --- CRITICAL #2: concurrent saves keep both anchors ---
    def test_concurrent_colliding_saves_keep_both(self):
        env = dict(os.environ, ANKORA_DIR=self.dir)
        for _ in range(3):
            for f in self._files():
                f.unlink()
            p1 = subprocess.Popen([sys.executable, ANKORA_PY, "save", "auth v1", "-m", "AAA"], env=env)
            p2 = subprocess.Popen([sys.executable, ANKORA_PY, "save", "Auth: V1", "-m", "BBB"], env=env)
            self.assertEqual(p1.wait(), 0)
            self.assertEqual(p2.wait(), 0)
            self.assertEqual(len(self._files()), 2, "a concurrent save was lost")


if __name__ == "__main__":
    unittest.main()

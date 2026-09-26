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

    # --- word forms: the README's own example used to come back empty ---
    def test_recall_matches_english_word_forms(self):
        # v0.2.0 README bug class: anchor says "ids", query says "id".
        ankora.save("Use UUID v7 for ids", "decision", ["db", "ids"], "time-ordered")
        ankora.save("Noise", "note", [], "uuid uuid uuid")
        titles = [h["title"] for h in ankora.recall("id generation")]
        self.assertEqual(titles, ["Use UUID v7 for ids"])      # found, and still not via "uuid"

    def test_recall_matches_russian_word_forms(self):
        ankora.save("Кэш памяти сбрасывается ночью", "fact", [], "Redis flushall в 03:00")
        ankora.save("Другое", "note", [], "про деплой")
        titles = [h["title"] for h in ankora.recall("память")]
        self.assertEqual(titles, ["Кэш памяти сбрасывается ночью"])

    # --- ranking: rare words decide, filler words do not ---
    def test_rare_term_outweighs_common_term(self):
        # mutation-catcher for IDF: with every term weighted alike the deploy
        # notes (the common word, many times) win the query.
        for i in range(4):
            ankora.save(f"Deploy deploy notes {i}", "note", [], "deploy " * 10)
        ankora.save("Release checklist", "note", [], "rollback if the smoke test fails")
        self.assertEqual(ankora.recall("deploy rollback")[0]["title"], "Release checklist")

    def test_filler_words_do_not_rank(self):
        # mutation-catcher for the stopword list: "the" x8 must not beat "switch".
        ankora.save("Filler", "note", [], "the the the the the the the the")
        ankora.save("Blue green switch", "decision", [], "flip traffic between pools")
        self.assertEqual(ankora.recall("the switch")[0]["title"], "Blue green switch")

    def test_filler_only_query_returns_nothing(self):
        ankora.save("The plan", "note", [], "it is what it is")
        self.assertEqual(ankora.recall("the and of"), [])

    def test_shorter_note_wins_on_equal_match(self):
        # mutation-catcher for length normalisation: one mention in a short
        # note is stronger evidence than one mention lost in a long one.
        ankora.save("Long note", "note", [], "cache " + "lorem " * 200)
        ankora.save("Short note", "note", [], "cache ttl")
        self.assertEqual(ankora.recall("cache")[0]["title"], "Short note")

    # --- critic-trio 2026-09-24: reproducers, each failed on the first BM25 cut ---
    def test_title_beats_body_even_with_a_long_body(self):
        # One pseudo-document let a long body drown a title match (33+ words).
        # The short filler notes keep the average note short, so a title that is
        # normalised by the WHOLE note's length (not the title's own) loses here.
        ankora.save("Auth", "note", [], " ".join(f"word{i}" for i in range(300)))
        ankora.save("Session notes", "note", [], "auth")
        for i in range(5):
            ankora.save(f"Filler {i}", "note", [], "short")
        self.assertEqual(ankora.recall("auth")[0]["title"], "Auth")

    def test_exact_word_beats_a_stem_collision(self):
        # "cors" and "core" share the stem "cor"; the exact word must decide.
        ankora.save("Core module", "note", [], "stays small")
        ankora.save("CORS preflight", "note", [], "allow origin for admin panel")
        self.assertEqual(ankora.recall("cors")[0]["title"], "CORS preflight")
        self.assertEqual(ankora.recall("core")[0]["title"], "Core module")

    def test_exact_word_breaks_a_stem_tie(self):
        # "plane" and "plan" share a stem; the note that has the exact word wins.
        ankora.save("Control plane", "note", [], "etcd quorum")
        ankora.save("Release plan", "note", [], "dates and owners")
        self.assertEqual(ankora.recall("plan")[0]["title"], "Release plan")

    def test_english_forms_the_first_stemmer_split(self):
        ankora.save("Session cookie flags", "note", [], "SameSite Lax")
        ankora.save("Sprint planning", "note", [], "board")
        ankora.save("Verbose logging off", "note", [], "prod only")
        self.assertIn("Session cookie flags", [h["title"] for h in ankora.recall("cookies")])
        self.assertIn("Sprint planning", [h["title"] for h in ankora.recall("plan")])
        self.assertIn("Verbose logging off", [h["title"] for h in ankora.recall("log")])

    def test_russian_forms_the_first_stemmer_split(self):
        ankora.save("Порядок записи в SQLite", "note", [], "WAL включён")
        ankora.save("Интеграция внешних систем", "note", [], "через шину")
        self.assertIn("Порядок записи в SQLite", [h["title"] for h in ankora.recall("запись")])
        self.assertIn("Интеграция внешних систем", [h["title"] for h in ankora.recall("система")])

    def test_yo_and_ye_are_one_letter(self):
        # a short word, so the Russian shared-start match cannot hide the ё/е split
        ankora.save("Счёт клиента", "note", [], "выставляется в конце месяца")
        self.assertEqual([h["title"] for h in ankora.recall("счет")], ["Счёт клиента"])

    def test_decomposed_unicode_is_normalised(self):
        # "Й" typed as И + U+0306 (NFD) must behave like the composed letter; it is
        # the FIRST letter, so the shared-start match cannot paper over a split.
        ankora.save("Йогурт в меню", "note", [], "без сахара")
        self.assertEqual([h["title"] for h in ankora.recall("йогурт")], ["Йогурт в меню"])

    def test_apostrophe_leftovers_do_not_match(self):
        # "user's" used to leave a one-letter term "s" that matched every "it's".
        ankora.save("User's theme", "note", [], "dark")
        ankora.save("Other note", "note", [], "it's what it's")
        self.assertEqual([h["title"] for h in ankora.recall("user's")], ["User's theme"])

    def test_cli_save_reads_piped_body_as_utf8(self):
        # stdout/stderr were reconfigured to UTF-8 but stdin was not: on Windows a
        # piped Russian body landed in the file as cp1251 mojibake.
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
        env["ANKORA_DIR"] = self.dir
        subprocess.run([sys.executable, ANKORA_PY, "save", "Итог спринта"], env=env, check=True,
                       input="Кэш памяти".encode("utf-8"), capture_output=True)
        self.assertIn("Кэш памяти", self._files()[0].read_text(encoding="utf-8"))

    def test_cli_limit_zero_prints_nothing(self):
        env = dict(os.environ, ANKORA_DIR=self.dir, PYTHONIOENCODING="utf-8")
        subprocess.run([sys.executable, ANKORA_PY, "save", "cache", "-m", "ttl"], env=env, check=True, capture_output=True)
        out = subprocess.run([sys.executable, ANKORA_PY, "recall", "cache", "-n", "0"], env=env,
                             capture_output=True, check=True).stdout.decode("utf-8")
        self.assertEqual(out.strip(), "")

    def test_cli_recall_russian_word_form_roundtrip(self):
        # CLI path with non-ASCII in and out (unit tests of the library miss
        # console-encoding bugs).
        env = dict(os.environ, ANKORA_DIR=self.dir, PYTHONIOENCODING="utf-8")
        subprocess.run([sys.executable, ANKORA_PY, "save", "Решение по кэшу памяти", "-m", "TTL 5 минут"],
                       env=env, check=True, capture_output=True)
        out = subprocess.run([sys.executable, ANKORA_PY, "recall", "кэш память"], env=env,
                             capture_output=True, check=True).stdout.decode("utf-8")
        self.assertIn("Решение по кэшу памяти", out)

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

    def test_type_with_newline_rejected(self):
        # type_ is a frontmatter value too — a newline must not inject a title (audit re-pass)
        with self.assertRaises(ValueError):
            ankora.save("Victim", "note\ntitle: Attacker", [], "A")

    def test_interrupted_write_preserves_original_and_leaves_no_temp(self):
        p = ankora.save("Durable", "note", [], "ORIGINAL")

        def boom(src, dst):
            raise OSError("simulated crash during replace")

        orig = ankora.os.replace
        ankora.os.replace = boom
        try:
            with self.assertRaises(OSError):
                ankora.save("Durable", "note", [], "NEWDATA")
        finally:
            ankora.os.replace = orig
        self.assertIn("ORIGINAL", p.read_text(encoding="utf-8"))          # complete old survives
        self.assertEqual(list((Path(self.dir) / "anchors").glob("*.tmp*")), [])  # no temp litter

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
        # An anchor created on an EARLIER day: saving both versions today would
        # pass even with the preserve logic removed, because date.today() is the
        # same on both writes. Backdate the stored date so the test can only pass
        # if the original value is really carried over.
        p = ankora.save("Keep date", "note", [], "v1")
        first = ankora._parse(p)["created"]
        p.write_text(
            p.read_text(encoding="utf-8").replace(f"created: {first}", "created: 2020-01-01", 1),
            encoding="utf-8",
        )
        self.assertEqual(ankora._parse(p)["created"], "2020-01-01")   # backdate landed
        ankora.save("Keep date", "note", [], "v2")
        self.assertEqual(ankora._parse(p)["created"], "2020-01-01")
        self.assertIn("v2", p.read_text(encoding="utf-8"))            # and the body did update

    # --- temp file name must stay unpredictable (v0.1.2 fix, previously untested) ---
    def test_temp_file_name_is_not_predictable(self):
        # v0.1.2 replaced a predictable temp name with mkstemp so a pre-planted
        # link at that path could not be written through. Nothing pinned that
        # fix: reverting it kept the whole suite green. This is the pin —
        # a canary sitting at the predictable path must survive a save.
        p = ankora.save("Trap target", "note", [], "v1")
        trap = Path(str(p) + ".tmp")
        trap.write_text("CANARY", encoding="utf-8")
        try:
            ankora.save("Trap target", "note", [], "v2")
            self.assertTrue(
                trap.exists(),
                "temp name is predictable again — the pre-planted file was consumed by the save",
            )
            self.assertEqual(
                trap.read_text(encoding="utf-8"),
                "CANARY",
                "temp name is predictable again — a pre-planted path was written through",
            )
        finally:
            trap.unlink(missing_ok=True)

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

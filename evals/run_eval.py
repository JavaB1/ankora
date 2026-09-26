"""Recall-quality eval for Ankora against a frozen gold set.

    python evals/run_eval.py [evals/gold-2026-09-24.json] [--show-misses]

Loads every gold anchor into a throwaway store, runs every gold query through
ankora.recall, and reports:
  hit@1, hit@3   share of answerable queries with ANY expected anchor in the top 1 / 3
  MRR            mean reciprocal rank of the best-ranked expected anchor (answerable queries)
  silent@none    share of no-answer queries (expected == []) that return nothing
Numbers are printed per language slice too, because the store is bilingual.

Pre-registration, written 2026-09-24 BEFORE any new ranking code was run:
  gold-2026-09-24.json sha256 1F87F1EC3C886F2909C898CB89E2AF62D61EC1BFBCD170598E88E7CC845EC4BA,
  written by a separate agent that never saw ankora.py.
  Baseline v0.2.0: hit@1 0.62, hit@3 0.76, MRR 0.70, silent@none 0.20.
  Variant A = light stemming (EN/RU) + stopwords + BM25 over weighted fields.
  Variant B = A + "a hit must match at least half of the query's content
  words" (only for queries with 3+ content words).
  B becomes the default only if its hit@3 is no more than 0.02 below A's AND
  its silent@none is at least 0.40 above A's; otherwise A ships and B stays off.
  Cross-language queries are expected to stay near zero: no translation.

Second round, written 2026-09-24 before the critic-driven changes were made:
  gold-holdout-2026-09-24.json sha256 719204873965A5C51DA90580F5CF966AD5B4714B0A3CA50D24ACFF1285DA2EE2,
  another project, written by another blind agent after the first cut existed.
  Scored before any second-round change: v0.2.0 hit@1 0.55 hit@3 0.68 MRR 0.61;
  first 0.3.0 cut hit@1 0.85 hit@3 0.93 MRR 0.88.
  The second-round changes are driven only by the critics' unit reproducers.
  The final version is scored on the holdout ONCE; nothing is tuned on it.
"""
import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
# ANKORA_EVAL_MODULE_DIR lets the same eval score an older ankora.py (e.g. the
# last release checked out into a temp dir) against the same gold set.
sys.path.insert(0, os.environ.get("ANKORA_EVAL_MODULE_DIR") or str(HERE.parent))

import ankora  # noqa: E402


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def is_ru(text):
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def run(gold, show_misses=False):
    with tempfile.TemporaryDirectory() as td:
        os.environ["ANKORA_DIR"] = td
        title_to_id = {}
        for a in gold["anchors"]:
            ankora.save(a["title"], a.get("type", "note"), a.get("tags", []), a.get("body", ""))
            title_to_id[a["title"]] = a["id"]

        rows = []
        for q in gold["queries"]:
            got = [title_to_id[h["title"]] for h in ankora.recall(q["q"], limit=5)]
            exp = q["expected"]
            if exp:
                ranks = [got.index(e) + 1 for e in exp if e in got]
                best = min(ranks) if ranks else None
            else:
                best = None
            rows.append({"id": q["id"], "q": q["q"], "exp": exp, "got": got, "best": best,
                         "ru": is_ru(q["q"]), "cross": q.get("why") == "cross-language"})

    def summary(sel, label):
        ans = [r for r in sel if r["exp"]]
        none = [r for r in sel if not r["exp"]]
        if not sel:
            return
        h1 = sum(1 for r in ans if r["best"] == 1) / len(ans) if ans else float("nan")
        h3 = sum(1 for r in ans if r["best"] and r["best"] <= 3) / len(ans) if ans else float("nan")
        mrr = sum(1 / r["best"] for r in ans if r["best"]) / len(ans) if ans else float("nan")
        sil = sum(1 for r in none if not r["got"]) / len(none) if none else float("nan")
        print(f"{label:<14} n={len(sel):>3}  hit@1={h1:.2f}  hit@3={h3:.2f}  MRR={mrr:.2f}  "
              f"silent@none={sil:.2f} ({len(none)} no-answer)")

    summary(rows, "ALL")
    summary([r for r in rows if r["ru"] and not r["cross"]], "russian")
    summary([r for r in rows if not r["ru"] and not r["cross"]], "english")
    summary([r for r in rows if r["cross"]], "cross-lang")

    if show_misses:
        print("\nmisses (answerable, not in top 3) and false alarms (no-answer, returned something):")
        for r in rows:
            if (r["exp"] and not (r["best"] and r["best"] <= 3)) or (not r["exp"] and r["got"]):
                print(f"  {r['id']} {r['q']!r} expected={r['exp']} got={r['got'][:3]}")
    return rows


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    gold_path = args[0] if args else HERE / "gold-2026-09-24.json"
    run(load(gold_path), show_misses="--show-misses" in sys.argv)

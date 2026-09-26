# Ankora

Tiny persistent memory for coding agents. Save atomic notes as plain markdown; recall the relevant ones when you start a new session — so the agent continues instead of forgetting what you already worked out.

## The problem

Everyone's fix for "Claude forgets" is a bigger `CLAUDE.md`. But bigger context makes it *worse*, not better — long files get diluted and the model loses the middle. Splitting into `tree.md` / `context.md` / `structure.md` only helps if you stop loading them all every session; four growing files that always load are the same wall in four pieces.

Ankora is the small version of the fix: **one atomic note per fact/decision, a tiny always-loaded index, pull in only the note the task needs.**

## Install

Needs Python 3.8+ and nothing else — no dependencies to pull in, nothing to build.

```bash
pip install ankora-memory
ankora --help
```

The PyPI name is `ankora-memory` because plain `ankora` was already taken by an
unrelated project; the command you actually type is still `ankora`.

Or skip the install entirely — it's one file, so you can just run it:

```bash
git clone https://github.com/JavaB1/ankora
cd ankora
python ankora.py --help
```

## Use

```bash
# save a decision
ankora save "Use UUID v7 for ids" -t decision -g db,ids -m "time-ordered, index-friendly, avoids v4 fragmentation"

# recall what's relevant to the task at hand
ankora recall "uuid ids"

# rebuild the index (one line per anchor)
ankora index
```

(Running from a clone instead of an install? Use `python ankora.py ...` — same commands.)

Anchors live in `./.ankora/anchors/*.md` — plain markdown with a small frontmatter block, so they diff cleanly in git and you can read/edit them by hand. `./.ankora/INDEX.md` is the short always-on list.

Set `ANKORA_DIR` to point it somewhere else (e.g. a shared notes repo).

Writes are atomic and guarded by a lock, so a crash mid-save or two concurrent saves never silently lose an anchor.

## With Claude Code

Drop `SKILL.md` into your project (or `.claude/skills/`). It tells the agent to run `recall` at the start of a session and `save` when a real decision is made. See `SKILL.md`.

## How recall ranks

Recall is keyword search, made forgiving in the places that matter. English words are cut to a light stem, so `id` finds a note about `ids` and `log` finds `logging`. Russian words match by their start, so `ошибки` finds `ошибок` and `запись` finds `записи`. `ё` and `е` count as one letter. Filler words like `the`, `and`, `как`, `через` are ignored. Ranking is BM25F: a rare word in your query counts for more than a common one, a word in the title counts about three times as much as the same word in the body, a short note that mentions your word beats a long one that mentions it in passing, and the exact word you typed beats a look-alike (`cors` finds CORS, not `core`).

Checked on a held-out set: 45 queries against 40 notes of an HR/payroll project, half in Russian, written by a separate agent that never saw the code and never used to tune it. `python evals/run_eval.py evals/gold-holdout-2026-09-24.json` reproduces it:

| | 0.2.0 | 0.3.0 |
|---|---|---|
| right note first | 55% | 80% |
| right note in top 3 | 68% | 93% |
| Russian queries, right note first | 53% | 79% |

A first draft of 0.3.0 scored 85% on the first line. Fixing the defects a review found (a long body drowning a title match, `запись` finding nothing, a piped body saved as mojibake, and more) cost about two Russian queries at rank 1 on this set; the fixes stayed. It is a small set, so read it as a regression check, not a benchmark. Still unsolved: when nothing relevant was ever saved, recall returns the closest weak matches instead of nothing (0 of 5 such queries came back empty).

## What it does NOT do (on purpose)

This is deliberately small. It does **not** do embeddings/semantic search, synonyms, translation, a graph, auto-consolidation, or conflict detection. If two notes disagree, both stay — you resolve it. If you outgrow keyword recall, that's when a full memory framework is worth the extra setup. Ankora is the small version that covers most of the value first, with nothing to install.

## License

MIT. Use it, fork it, ship it.

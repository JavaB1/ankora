# Ankora

Tiny persistent memory for coding agents. Save atomic notes as plain markdown; recall the relevant ones when you start a new session — so the agent continues instead of forgetting what you already worked out.

## The problem

Everyone's fix for "Claude forgets" is a bigger `CLAUDE.md`. But bigger context makes it *worse*, not better — long files get diluted and the model loses the middle. Splitting into `tree.md` / `context.md` / `structure.md` only helps if you stop loading them all every session; four growing files that always load are the same wall in four pieces.

Ankora is the small version of the fix: **one atomic note per fact/decision, a tiny always-loaded index, pull in only the note the task needs.**

## Install

Needs Python 3.8+. That's it — no `pip install`, nothing to build.

```bash
git clone https://github.com/JavaB1/ankora
cd ankora
python ankora.py --help
```

## Use

```bash
# save a decision
python ankora.py save "Use UUID v7 for ids" -t decision -g db,ids -m "time-ordered, index-friendly, avoids v4 fragmentation"

# recall what's relevant to the task at hand
python ankora.py recall "id generation"

# rebuild the index (one line per anchor)
python ankora.py index
```

Anchors live in `./.ankora/anchors/*.md` — plain markdown with a small frontmatter block, so they diff cleanly in git and you can read/edit them by hand. `./.ankora/INDEX.md` is the short always-on list.

Set `ANKORA_DIR` to point it somewhere else (e.g. a shared notes repo).

Writes are atomic and guarded by a lock, so a crash mid-save or two concurrent saves never silently lose an anchor.

## With Claude Code

Drop `SKILL.md` into your project (or `.claude/skills/`). It tells the agent to run `recall` at the start of a session and `save` when a real decision is made. See `SKILL.md`.

## What it does NOT do (on purpose)

This is deliberately small. It does **not** do embeddings/semantic search, a graph, auto-consolidation, conflict detection, or ranking beyond weighted whole-word keyword matching. If two notes disagree, both stay — you resolve it. If you outgrow keyword recall, that's when a full memory framework is worth the extra setup. Ankora is the small version that covers most of the value first, with nothing to install.

## License

MIT. Use it, fork it, ship it.

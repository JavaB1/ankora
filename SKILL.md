---
name: ankora-memory
description: Use at the start of a coding session to recall prior decisions, and whenever a real decision/fact/insight is made to persist it. Keeps continuity across sessions without bloating CLAUDE.md.
---

# Ankora memory

Ankora stores atomic notes ("anchors") as markdown and recalls the relevant ones on demand. Use it so you continue prior work instead of re-deriving it.

## At the start of a session

1. Read `.ankora/INDEX.md` if it exists — it's the short list of what's remembered.
2. For the task at hand, pull the detail you need:
   ```
   python ankora.py recall "<keywords for this task>"
   ```
   Only recall what's relevant. Do not load every anchor.

## When to save an anchor

Save when something is decided or learned that a future session would otherwise re-discover:
- a **decision** ("we use X because Y"),
- a **fact** about the system that isn't obvious from the code,
- an **insight** / gotcha / thing that bit you.

```
python ankora.py save "<one-line claim>" -t decision -g tag1,tag2 -m "<why / detail>"
```

Keep each anchor atomic — one claim per note. Do not dump a whole session into one anchor; that recreates the big-file problem Ankora exists to avoid.

## Rules

- The always-loaded surface is `INDEX.md` only. Detail is pulled on demand via `recall`.
- Prefer many small anchors over one growing file.
- Don't save secrets, tokens, or credentials into anchors.
- This skill calls `ankora.py`; keep the engine reachable (copy `ankora.py` into the project, or once installed via pip use the `ankora` command instead). Both the engine and the store honour `ANKORA_DIR`.

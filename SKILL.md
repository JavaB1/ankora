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
   ankora recall "<keywords for this task>"
   ```
   Only recall what's relevant. Do not load every anchor.

## When to save an anchor

Save when something is decided or learned that a future session would otherwise re-discover:
- a **decision** ("we use X because Y"),
- a **fact** about the system that isn't obvious from the code,
- an **insight** / gotcha / thing that bit you.

```
ankora save "<one-line claim>" -t decision -g tag1,tag2 -m "<why / detail>"
```

Keep each anchor atomic — one claim per note. Do not dump a whole session into one anchor; that recreates the big-file problem Ankora exists to avoid.

## Rules

- The always-loaded surface is `INDEX.md` only. Detail is pulled on demand via `recall`.
- Prefer many small anchors over one growing file.
- Don't save secrets, tokens, or credentials into anchors.
- This skill calls the `ankora` command (`pip install ankora-memory`). Working from a clone instead? Run `python ankora.py ...` with the same arguments. Both forms honour `ANKORA_DIR`.

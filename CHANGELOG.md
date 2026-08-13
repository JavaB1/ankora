# Changelog

All notable changes to Ankora. Format loosely follows [Keep a Changelog]; versions follow [SemVer].

## [0.1.1] — 2026-08-13

Hardening release after an external adversarial audit. No API changes.

- Atomic writes (temp + fsync + `os.replace`) — a crash mid-save no longer destroys the old anchor or the index.
- Cross-process lock around save + index — two concurrent saves no longer silently lose an anchor.
- Frontmatter values are JSON-encoded and titles/tags containing newlines are rejected — a crafted title can no longer inject a fake `title:` and clobber a different anchor.
- Malformed anchor files (bad UTF-8, empty, missing frontmatter) are skipped with a warning instead of crashing a rebuild or being recalled as a phantom.
- Windows: reserved device names (CON, NUL, COM1…) are prefixed; CLI output no longer crashes under non-UTF-8 code pages.
- `recall` matches whole words (not substrings) and rejects negative limits.
- Upsert preserves the original `created` date and records `updated`.
- Empty titles are rejected.
- Tests rewritten as real behaviour tests (file counts, identities, concurrency, malformed input) with temp-dir cleanup.

Known: index rebuild is O(n) per save (fine for small stores); an incremental index is planned for 0.1.2.

## [0.1.0] — 2026-08-13

First public release.

- Save atomic anchors as plain markdown with frontmatter (`save`).
- Keyword recall with title/tag/body weighting (`recall`).
- Always-loaded `INDEX.md` (`index`), plus `list`.
- Save is an upsert keyed on the title; different titles that slug to the same
  name are suffixed, never clobbered.
- Claude Code skill (`SKILL.md`): recall at session start, save at decisions.
- Zero dependencies (Python 3.8+ stdlib). Behaviour tests, MIT licensed.

[Keep a Changelog]: https://keepachangelog.com/
[SemVer]: https://semver.org/

# Changelog

All notable changes to Ankora. Format loosely follows [Keep a Changelog]; versions follow [SemVer].

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

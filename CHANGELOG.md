# Changelog

All notable changes to Ankora. Format loosely follows [Keep a Changelog]; versions follow [SemVer].

## [0.2.0] — 2026-08-22

Installable. Nothing about the tool itself changed — this release is packaging plus
two documentation fixes found by actually installing it.

- **`pip install ankora-memory`.** A `pyproject.toml` (setuptools, flat single-module
  layout) exposes `ankora` as a console command, so you no longer have to clone the
  repo and type `python ankora.py`. Still zero runtime dependencies — the package
  installs one file and one entry point. The distribution name is `ankora-memory`
  because `ankora` on PyPI belongs to an unrelated project; the command stays `ankora`.
- **The README's own recall example returned nothing.** It saved *"Use UUID v7 for
  ids"* and then ran `recall "id generation"` — but matching is whole-word, so `id`
  never matches `ids` and `generation` appears nowhere. Copy-pasting the README
  produced `no anchors matched`, which reads as broken software on first contact.
  The example is now `recall "uuid ids"`, verified against a real install.
- **README no longer claims "no `pip install`".** It offers the install first and the
  clone second, since both now work.

Verified by building the wheel and installing it into a clean virtualenv, then running
save/recall/index/list through the installed `ankora` command rather than the source tree.

## [0.1.3] — 2026-08-15

Third pass, and the first one aimed at the *tests* rather than the code. Method:
break one load-bearing thing at a time, demand the responsible test go red, revert,
demand green. Seven probes; five defences held, two did not.

- **The `created`-preservation test proved vacuous and is now real.** It saved an
  anchor twice in a row and compared `created` — but both writes happen on the same
  calendar day, so `date.today()` matched *even with the preserve logic deleted*.
  Removing `created = prev["created"]` kept it green. The test now backdates the
  stored anchor to 2020-01-01 before the second save, so it can only pass if the
  original value is genuinely carried over (and asserts the body still updates).
- **The v0.1.2 security fix had nothing pinning it.** Reverting the random `mkstemp`
  temp name back to a predictable `<anchor>.tmp` left all 17 tests green — a future
  refactor could have quietly reopened the pre-planted-link hole. A canary test now
  plants a file at the predictable path and requires it to survive a save untouched.

Both new tests were verified in reverse: each was re-run against the corresponding
broken code and observed to fail with a readable message, then against the intact
code and observed to pass.

Behaviour and API are unchanged — this release only closes a gap between what the
suite claimed to protect and what it actually protected.

Known (unchanged): index rebuild is O(n) per save; titles with no ASCII letters
collapse to a generic slug namespace (suffix-protected, so no loss).

## [0.1.2] — 2026-08-13

Second hardening pass — self-audit by fault-injection and concurrency execution after the external audit.

- Reject newlines in the `type` field too (not only title/tags) — closes a frontmatter-injection path through the Python API's `type_` argument.
- Atomic writes now use a random, exclusively-created temp file (`mkstemp`) instead of a predictable name, so a pre-planted link at the temp path can't be used to write outside the store; temp files are always removed on failure.
- Added tests for type-field injection and interrupted-write atomicity (the complete old file survives, no temp litter); concurrency, Windows reserved-name/unicode, and hardlink-at-destination surfaces re-verified by execution.

Known: index rebuild is still O(n) per save; titles with no ASCII letters collapse to a generic slug namespace (suffix-protected, so no loss). Both are slated for a later release.

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

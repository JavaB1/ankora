# Changelog

All notable changes to Ankora. Format loosely follows [Keep a Changelog]; versions follow [SemVer].

## [0.3.0] — 2026-09-24

Recall got better at finding the note you meant. Storage, file format and commands
are unchanged; only how `recall` matches and ranks.

- **Word forms match.** English words go through a light stemmer applied to notes
  and queries alike (`ids` → `id`, `logging` → `log`, `committed` → `commit`,
  `cookies` → `cookie`). Russian words match by their start: the query word is cut
  by up to three letters but kept at least four long, so `ошибки` finds `ошибок` and
  `запись` finds `записи` (the same trick BrainHub measured at 6/12 → 9/12 on case
  forms). `ё` folds to `е`; text is NFC-normalised, so a `й` typed as two code
  points behaves like one.
- **Ranking is BM25F.** Title, tags and body are length-normalised against their
  own averages, weighted 3 / 2 / 1 and saturated once, so a long body can no longer
  drown a title match. A rare query word outweighs a common one, a short note beats
  a long one on the same single mention, and the exact word you typed earns a bonus
  over a look-alike that shares its stem (`cors` vs `core`, `plan` vs `plane`).
  Filler words (`the`, `and`, `как`, `через`, ...) and one-letter leftovers such as
  the `s` of `user's` are ignored; a query made only of them returns nothing.
- **CLI.** A body piped to `ankora save` is read as UTF-8 (it was read in the console
  code page, which turned Russian text into mojibake on Windows). `recall -n 0`
  prints nothing instead of "no anchors matched".
- **Measured on a held-out set.** `evals/gold-holdout-2026-09-24.json`: 45 bilingual
  queries against 40 notes, written by a separate agent that never saw the code, and
  scored once at the end. Right note first: 55% → 80%; top 3: 68% → 93%; Russian
  queries first: 53% → 79%. A first draft scored 85% first; the review fixes below
  cost about two Russian queries at rank 1 and were kept. The earlier set
  (`gold-2026-09-24.json`) was used during development, so its numbers are not
  independent: 62% → 87% first.
- **Found by review, fixed, pinned.** An adversarial review of the first draft found
  a long body drowning a title match, stem collisions (`cors`/`core`), split forms
  (`cookie`/`cookies`, `запись`/`записи`, `система`/`систем`), unfolded `ё`, NFD text,
  apostrophe leftovers and the stdin encoding. Each has a test that failed first.
- **Known gap.** For queries with no relevant note, recall still returns the closest
  weak matches (0 of 5 came back empty on the held-out set). A stricter rule (a hit
  must contain half of the query's words) silenced them but lost a fifth of the right
  answers on the first set, so it ships off (`MIN_MATCH_SHARE = 0.0`).
- **Every ranking rule is pinned.** Removing the word-form matching, stopwords, IDF,
  length normalisation, per-field length, the title weight, the exact-word bonus,
  `ё` folding, NFC, the one-letter drop or the UTF-8 stdin each turns its own test
  red (checked on copies of the file, `evals/redproof-2026-09-24.txt`).

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

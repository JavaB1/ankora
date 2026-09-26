#!/usr/bin/env python3
"""
Ankora - tiny persistent memory for coding agents.

Save atomic notes ("anchors") as plain markdown; recall the relevant ones when
you start a new session, so the agent continues instead of forgetting what you
already worked out.

Zero dependencies: Python 3.8+ standard library only. Nothing to build.

    python ankora.py save "Use UUID v7 for ids" -t decision -g db,ids -m "time-ordered"
    python ankora.py recall "uuid ids"
    python ankora.py index      # rebuild INDEX.md
    python ankora.py list

Storage lives in ./.ankora/ by default (override with the ANKORA_DIR env var).
Writes are atomic and guarded by a cross-process lock, so a crash or two
concurrent saves never silently lose an anchor.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import os
import re
import sys
import tempfile
import time
import unicodedata
from datetime import date
from pathlib import Path

__version__ = "0.3.0"

TYPES = ("fact", "decision", "insight", "note")

# Ranking (explicit so behaviour is testable): BM25F. Each field is length-
# normalised against the average of that field (title, tags, body separately),
# weighted, summed per word, then saturated once -- so a long body can no longer
# drown a title match. Words are NFC-normalised, lower-cased, ё folded to е;
# one-letter leftovers ("s" from "user's") and filler (STOPWORDS) are dropped.
# A query word matches a note word by form: English by a light stem ("ids" finds
# "id", "logging" finds "log"), Russian by a shared start -- cut up to three
# letters but keep at least four (BrainHub's term_prefix, measured 6/12 -> 9/12
# on case forms), so "ошибки" finds "ошибок" and "запись" finds "записи".
# The exact word earns EXACT_BONUS on top, so "cors" beats "core" although both
# stem to "cor". No synonyms, no translation, no embeddings.
W_TITLE, W_TAGS, W_BODY = 3, 2, 1
BM25_K1, BM25_B = 1.2, 0.5
_FIELDS = (("title", W_TITLE, 0.25), ("tags", W_TAGS, 0.25), ("body", W_BODY, BM25_B))
EXACT_BONUS = 0.5
# Share of a query's content words a hit must contain (queries of 3+ words).
# 0 = off: any matching word is enough.
MIN_MATCH_SHARE = 0.0

STOPWORDS = frozenset("""
a an and are as at be been but by can do does did for from had has have how i if in into is it
its me my no not of on or our so than that the their them then there these they this to up us
was we were what when where which who why will with would you your
а без бы в во вот все где да для до если есть же за зачем и из или им их к как ко когда кто
ли мне мы на над не нет но о об от по под почему при про с со так там то тут у уже что чтобы это
эта эти этот я через после перед между также тоже еще который которая которое которые можно нужно
""".split())

_CYRILLIC = re.compile(r"[а-яе]")

_RESERVED = {"con", "prn", "aux", "nul", "clock$"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def _root() -> Path:
    return Path(os.environ.get("ANKORA_DIR", ".ankora"))


def _anchors_dir() -> Path:
    return _root() / "anchors"


def _index_file() -> Path:
    return _root() / "INDEX.md"


# --------------------------------------------------------------------------- #
# helpers: slug, tokens, atomic write, lock
# --------------------------------------------------------------------------- #
def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    s = (s or "anchor")[:60]
    if s.split(".")[0] in _RESERVED:   # Windows device name -> make it a normal file
        s = "_" + s
    return s


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    return [t for t in re.findall(r"\w+", text, re.UNICODE) if len(t) > 1]


def _undouble(word: str) -> str:
    return word[:-1] if len(word) > 2 and word[-1] == word[-2] and word[-1] in "bdfgmnprt" else word


@functools.lru_cache(maxsize=65536)
def _stem(word: str) -> str:
    """Light English stemmer, applied to notes and queries alike."""
    if len(word) > 4 and word.endswith("sses"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("ies"):
        word = word[:-3] + "i"                          # policies -> polici, cookies -> cooki
    elif len(word) > 2 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if word.endswith("eed"):
        pass                                            # need, exceed: not a past tense
    elif len(word) > 5 and word.endswith("ing"):
        word = _undouble(word[:-3])                     # logging -> log, planning -> plan
    elif len(word) > 5 and word.endswith("ed"):
        word = _undouble(word[:-2])                     # committed -> commit, verified -> verifi
    if len(word) > 3 and word.endswith("y") and word[-2] not in "aeiou":
        word = word[:-1] + "i"                          # policy -> polici, verify -> verifi
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]                                # cache -> cach, cookie -> cooki; core stays
    return word


def _matcher(q: str):
    """How one query word matches the words of a note."""
    if not q.isalpha():
        return lambda w: w == q                         # v7, argon2, 2026: exact only
    if _CYRILLIC.match(q):
        if len(q) > 4:
            start = q[:max(4, len(q) - 3)]
            return lambda w: w.startswith(start)
        return lambda w: w == q or (w.startswith(q) and len(w) - len(q) <= 3)   # кэш -> кэшем
    stem = _stem(q)
    return lambda w: w == q or (w.isalpha() and not _CYRILLIC.match(w) and _stem(w) == stem)


def _atomic_write(path: Path, text: str) -> None:
    """Write text so a reader always sees the complete old or complete new file.
    Uses a random, exclusively-created temp file (mkstemp) so a pre-planted link
    at a predictable temp name cannot be used to write outside the store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmpname = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpname, path)     # atomic; replaces the dir entry, not a hardlink target
        tmpname = None
    finally:
        if tmpname is not None and os.path.exists(tmpname):
            os.unlink(tmpname)        # never leave a temp file behind on failure
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass                          # directory fsync is best-effort (e.g. Windows)


class _Lock:
    """Cross-process advisory lock via atomic O_EXCL lockfile. Steals stale locks."""

    def __init__(self, path: Path, timeout: float = 10.0, stale: float = 30.0):
        self.path, self.timeout, self.stale, self.fd = path, timeout, stale, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        os.unlink(self.path)
                        continue
                except FileNotFoundError:
                    continue
                if time.time() - start > self.timeout:
                    raise TimeoutError(f"could not acquire lock {self.path}")
                time.sleep(0.02)

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
            os.unlink(self.path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# anchor read / write
# --------------------------------------------------------------------------- #
def _fm_value(v):
    return json.dumps(v, ensure_ascii=False)


def _parse(path: Path):
    """Parse an anchor file. Returns a dict, or None if the file is malformed
    (never silently manufactures a phantom anchor)."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")   # tolerate a BOM
    except (UnicodeDecodeError, OSError):
        return None
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    meta: dict = {}
    for line in lines[1:end]:
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()

    def _decode(raw, default):
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw.strip("[]") if default == [] else raw   # back-compat plain values

    title = _decode(meta.get("title"), None)
    if not isinstance(title, str) or not title.strip():
        return None                                            # require a real title
    tags = _decode(meta.get("tags"), [])
    if not isinstance(tags, list):
        tags = [t for t in re.split(r"[,\s]+", str(tags)) if t]
    body = "\n".join(lines[end + 1:]).strip()
    return {
        "path": Path(path),
        "title": title,
        "type": meta.get("type", "note"),
        "tags": [str(t) for t in tags],
        "created": meta.get("created", ""),
        "body": body,
    }


def _all() -> list[dict]:
    d = _anchors_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.md")):
        a = _parse(p)
        if a is None:
            print(f"ankora: skipping malformed anchor {p.name}", file=sys.stderr)
            continue
        out.append(a)
    return out


def _resolve_path(name: str, title: str) -> Path:
    """Reuse the file for a same-title anchor (upsert); otherwise suffix so a
    different anchor that slugs to the same name is never clobbered."""
    d = _anchors_dir()
    i = 1
    while True:
        candidate = d / (f"{name}.md" if i == 1 else f"{name}-{i}.md")
        if not candidate.exists():
            return candidate
        existing = _parse(candidate)
        if existing is not None and existing["title"] == title:
            return candidate
        i += 1


def save(title: str, type_: str, tags: list[str], body: str) -> Path:
    title = title if title is not None else ""
    if not title.strip():
        raise ValueError("title must not be empty")
    if any(("\n" in x or "\r" in x) for x in [title, type_, *tags]):
        raise ValueError("title, type and tags must not contain newlines")
    _anchors_dir().mkdir(parents=True, exist_ok=True)
    with _Lock(_root() / ".lock"):
        name = _slug(title)
        path = _resolve_path(name, title)
        created = date.today().isoformat()
        if path.exists():
            prev = _parse(path)
            if prev and prev.get("created"):
                created = prev["created"]                      # preserve original creation date
        front = [
            f"name: {path.stem}",
            f"title: {_fm_value(title)}",
            f"type: {type_}",
            f"tags: {_fm_value(list(tags))}",
            f"created: {created}",
            f"updated: {date.today().isoformat()}",
        ]
        _atomic_write(path, "---\n" + "\n".join(front) + "\n---\n\n" + body.strip() + "\n")
        _rebuild_index_unlocked()
    return path


def recall(query: str, limit: int = 5) -> list[dict]:
    if limit is not None and limit < 0:
        raise ValueError("limit must be >= 0")
    words = list(dict.fromkeys(t for t in _tokens(query) if t not in STOPWORDS))   # distinct, in order
    if not words:
        return []
    docs = []
    for a in _all():
        text = {"title": a["title"], "tags": " ".join(a["tags"]), "body": a["body"]}
        docs.append((a, {f: [t for t in _tokens(text[f]) if t not in STOPWORDS] for f, _, _ in _FIELDS}))
    if not docs:
        return []
    n = len(docs)
    avg = {f: (sum(len(d[f]) for _, d in docs) / n) or 1.0 for f, _, _ in _FIELDS}

    def weighted_tf(d, match):
        return sum(w * sum(1 for t in d[f] if match(t)) / (1 - b + b * len(d[f]) / avg[f])
                   for f, w, b in _FIELDS)

    def idf(df):
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def saturate(x):
        return x * (BM25_K1 + 1) / (x + BM25_K1) if x > 0 else 0.0

    # per query word: its weighted tf in every note, by form and by exact word
    columns = []
    for q in words:
        by_form = [weighted_tf(d, _matcher(q)) for _, d in docs]
        exact = [weighted_tf(d, lambda t, q=q: t == q) for _, d in docs]
        columns.append((by_form, sum(1 for x in by_form if x), exact, sum(1 for x in exact if x)))
    need = math.ceil(len(words) * MIN_MATCH_SHARE) if len(words) >= 3 else 1
    scored = []
    for i, (a, _) in enumerate(docs):
        if sum(1 for by_form, *_ in columns if by_form[i]) < max(1, need):
            continue
        score = 0.0
        for by_form, df_form, exact, df_exact in columns:
            score += idf(df_form) * saturate(by_form[i])
            score += EXACT_BONUS * idf(df_exact) * saturate(exact[i])
        scored.append((score, a))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    return [a for _, a in scored[:limit]] if limit is not None else [a for _, a in scored]


def _rebuild_index_unlocked() -> Path:
    anchors = _all()
    n = len(anchors)
    lines = [
        "# Ankora index",
        "",
        f"{n} anchor{'s' if n != 1 else ''}. Recall the full note with: "
        f'`python ankora.py recall "<query>"`',
        "",
    ]
    for a in anchors:
        tags = f" — {', '.join(a['tags'])}" if a["tags"] else ""
        lines.append(f"- **{a['title']}** [{a['type']}]{tags}")
    _atomic_write(_index_file(), "\n".join(lines) + "\n")
    return _index_file()


def rebuild_index() -> Path:
    with _Lock(_root() / ".lock"):
        return _rebuild_index_unlocked()


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def _print_hits(hits: list[dict], query: str) -> None:
    if not hits:
        print(f'no anchors matched: "{query}"')
        return
    for a in hits:
        print(f"\n## {a['title']}  [{a['type']}]")
        if a["tags"]:
            print("tags:", ", ".join(a["tags"]))
        print(a["body"].strip())


def _nonneg_int(v: str) -> int:
    n = int(v)
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):          # never crash on unicode under CP1251 etc.
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    try:                                             # a piped body is UTF-8 too, not the console code page
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser(prog="ankora", description=__doc__.splitlines()[1])
    p.add_argument("-V", "--version", action="version", version=f"ankora {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("save", help="save an anchor")
    s.add_argument("title")
    s.add_argument("-t", "--type", default="note", choices=TYPES)
    s.add_argument("-g", "--tags", default="", help="comma-separated tags")
    s.add_argument("-m", "--message", default="", help="anchor body (or piped via stdin)")

    r = sub.add_parser("recall", help="recall anchors by keyword")
    r.add_argument("query")
    r.add_argument("-n", "--limit", type=_nonneg_int, default=5)

    sub.add_parser("index", help="rebuild INDEX.md")
    sub.add_parser("list", help="list all anchors")

    args = p.parse_args(argv)
    if args.cmd == "save":
        tags = [t for t in re.split(r"[,\s]+", args.tags) if t]
        body = args.message or (sys.stdin.read() if not sys.stdin.isatty() else "")
        try:
            print(f"saved {save(args.title, args.type, tags, body)}")
        except ValueError as e:
            print(f"ankora: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.cmd == "recall":
        if args.limit == 0:
            return                                   # asked for nothing: say nothing, not "no match"
        _print_hits(recall(args.query, args.limit), args.query)
    elif args.cmd == "index":
        print("wrote", rebuild_index())
    elif args.cmd == "list":
        for a in _all():
            print(f"- {a['title']} [{a['type']}]")


if __name__ == "__main__":
    main()

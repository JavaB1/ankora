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
import json
import os
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

__version__ = "0.1.3"

TYPES = ("fact", "decision", "insight", "note")

# Ranking weights (explicit so behaviour is testable). Whole-word counts.
W_TITLE, W_TAGS, W_BODY = 3, 2, 1

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
    return re.findall(r"\w+", text.lower(), re.UNICODE)


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
    terms = _tokens(query)
    if not terms:
        return []
    scored = []
    for a in _all():
        tt, tg, tb = _tokens(a["title"]), _tokens(" ".join(a["tags"])), _tokens(a["body"])
        score = sum(W_TITLE * tt.count(t) + W_TAGS * tg.count(t) + W_BODY * tb.count(t) for t in terms)
        if score > 0:
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
        _print_hits(recall(args.query, args.limit), args.query)
    elif args.cmd == "index":
        print("wrote", rebuild_index())
    elif args.cmd == "list":
        for a in _all():
            print(f"- {a['title']} [{a['type']}]")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Ankora - tiny persistent memory for coding agents.

Save atomic notes ("anchors") as plain markdown; recall the relevant ones
when you start a new session, so the agent continues instead of forgetting
what you already worked out.

Zero dependencies: Python 3.8+ standard library only. Nothing to build.

    python ankora.py save "Use UUID v7 for ids" -t decision -g db,ids -m "time-ordered, index-friendly"
    python ankora.py recall "uuid ids"
    python ankora.py index      # rebuild INDEX.md
    python ankora.py list

Storage lives in ./.ankora/ by default (override with the ANKORA_DIR env var).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

TYPES = ("fact", "decision", "insight", "note")

# Weights: a hit in the title matters most, then tags, then body.
# (Kept explicit so the ranking behaviour is testable.)
W_TITLE, W_TAGS, W_BODY = 3, 2, 1


def _root() -> Path:
    return Path(os.environ.get("ANKORA_DIR", ".ankora"))


def _anchors_dir() -> Path:
    return _root() / "anchors"


def _index_file() -> Path:
    return _root() / "INDEX.md"


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s or "anchor")[:60]


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            body = parts[2].strip()
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
    tags = [t for t in re.split(r"[,\s]+", meta.get("tags", "").strip("[]")) if t]
    return {
        "path": path,
        "title": meta.get("title", path.stem),
        "type": meta.get("type", "note"),
        "tags": tags,
        "body": body,
    }


def _all() -> list[dict]:
    d = _anchors_dir()
    if not d.exists():
        return []
    return [_parse(p) for p in sorted(d.glob("*.md"))]


def _resolve_path(name: str, title: str) -> Path:
    """Pick the file for this anchor. Reuse the file if a same-title anchor
    already exists (save is an upsert keyed on the title); otherwise avoid
    clobbering a different anchor that slugs to the same name by suffixing."""
    d = _anchors_dir()
    i = 1
    while True:
        candidate = d / (f"{name}.md" if i == 1 else f"{name}-{i}.md")
        if not candidate.exists() or _parse(candidate)["title"] == title:
            return candidate
        i += 1


def save(title: str, type_: str, tags: list[str], body: str) -> Path:
    _anchors_dir().mkdir(parents=True, exist_ok=True)
    name = _slug(title)
    path = _resolve_path(name, title)
    front = [
        f"name: {name}",
        f"title: {title}",
        f"type: {type_}",
        f"tags: [{', '.join(tags)}]",
        f"created: {date.today().isoformat()}",
    ]
    path.write_text(
        "---\n" + "\n".join(front) + "\n---\n\n" + body.strip() + "\n",
        encoding="utf-8",
    )
    rebuild_index()
    return path


def recall(query: str, limit: int = 5) -> list[dict]:
    terms = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
    scored: list[tuple[int, dict]] = []
    for a in _all():
        title, tags, body = a["title"].lower(), " ".join(a["tags"]).lower(), a["body"].lower()
        score = 0
        for t in terms:
            score += W_TITLE * title.count(t) + W_TAGS * tags.count(t) + W_BODY * body.count(t)
        if score > 0:
            scored.append((score, a))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    return [a for _, a in scored[:limit]]


def rebuild_index() -> Path:
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
    _root().mkdir(parents=True, exist_ok=True)
    _index_file().write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _index_file()


def _print_hits(hits: list[dict], query: str) -> None:
    if not hits:
        print(f'no anchors matched: "{query}"')
        return
    for a in hits:
        print(f"\n## {a['title']}  [{a['type']}]")
        if a["tags"]:
            print("tags:", ", ".join(a["tags"]))
        print(a["body"].strip())


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="ankora", description=__doc__.splitlines()[1])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("save", help="save an anchor")
    s.add_argument("title")
    s.add_argument("-t", "--type", default="note", choices=TYPES)
    s.add_argument("-g", "--tags", default="", help="comma-separated tags")
    s.add_argument("-m", "--message", default="", help="anchor body (or piped via stdin)")

    r = sub.add_parser("recall", help="recall anchors by keyword")
    r.add_argument("query")
    r.add_argument("-n", "--limit", type=int, default=5)

    sub.add_parser("index", help="rebuild INDEX.md")
    sub.add_parser("list", help="list all anchors")

    args = p.parse_args(argv)
    if args.cmd == "save":
        tags = [t for t in re.split(r"[,\s]+", args.tags) if t]
        body = args.message or (sys.stdin.read() if not sys.stdin.isatty() else "")
        path = save(args.title, args.type, tags, body)
        print(f"saved {path}")
    elif args.cmd == "recall":
        _print_hits(recall(args.query, args.limit), args.query)
    elif args.cmd == "index":
        print("wrote", rebuild_index())
    elif args.cmd == "list":
        for a in _all():
            print(f"- {a['title']} [{a['type']}]")


if __name__ == "__main__":
    main()

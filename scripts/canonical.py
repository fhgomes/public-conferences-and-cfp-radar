#!/usr/bin/env python3
"""Canonical form of the dataset files (dataset-format section 3), byte-identical to the Java writer.

    python3 scripts/canonical.py --check <file>...   exit 1 and print the canonical text when a file differs
    python3 scripts/canonical.py --fix <file>...     rewrite the files in canonical form

KEY_ORDER is the shared key order table: a change here is one change with the Java KeyOrder, the schema,
the goldens and the README field table (docs/ai/open-data-repo.md in the platform).
"""
import json
import os
import sys

KEY_ORDER = {
    "record": ["id", "slug", "name", "edition", "nameNote", "organizer", "summary", "machineTranslated", "dates",
               "location", "geo", "links", "topics", "talkLanguages", "eventType", "audienceLevel", "remoteSpeaking",
               "cfp", "verification", "sources", "firstPublishedAt", "updatedAt"],
    "localized": ["en", "pt-BR"],
    "dates": ["start", "end", "tba", "status"],
    "location": ["city", "cityStatus", "countryCode", "region", "modality"],
    "geo": ["lat", "lng", "precision"],
    "links": ["website"],
    "remoteSpeaking": ["value", "mode", "basis"],
    "cfp": ["opensOn", "opensAt", "closesOn", "closesAt", "timezone", "closeTimeKnown", "url", "platform", "formats",
            "firstTimeSpeakersWelcome", "benefits", "verification"],
    "format": ["format", "durationMinutes", "maxSpeakers"],
    "benefits": ["travel", "hotel", "fee", "ticket"],
    "verification": ["status", "checkedAt", "by"],
    "source": ["code", "name", "url", "licence", "role"],
    "tombstones": ["removed"],
    "removed-item": ["id", "slug", "reason", "replacedBy", "removedOn"],
    "topic": ["slug", "status", "name"],
}

# child context of an object key, per parent context (lists use the same entry for their items)
CHILDREN = {
    "record": {"nameNote": "localized", "organizer": "localized", "summary": "localized", "dates": "dates",
               "location": "location", "geo": "geo", "links": "links", "remoteSpeaking": "remoteSpeaking",
               "cfp": "cfp", "verification": "verification", "sources": "source"},
    "cfp": {"formats": "format", "benefits": "benefits", "verification": "verification"},
    "tombstones": {"removed": "removed-item"},
    "topic": {"name": "localized"},
}

# lists of strings sorted ascending
SORTED_STRING_LISTS = {"machineTranslated", "topics", "talkLanguages"}

ROOT_KIND = {"record": "record", "tombstones": "tombstones", "enum-topics": "topic", "enum-list": None}


class CanonicalError(Exception):
    """Raised for an input key outside the order table: code `unknown-key:<path>`."""


def _nulls_last(value):
    return (value is None, value if value is not None else 0)


def _sort_list(key, ctx, items):
    if key in SORTED_STRING_LISTS:
        return sorted(items)
    if ctx == "source":
        return sorted(items, key=lambda i: i["code"])
    if ctx == "format":
        return sorted(items, key=lambda i: (i["format"], _nulls_last(i.get("durationMinutes")),
                                            _nulls_last(i.get("maxSpeakers"))))
    if ctx == "removed-item":
        return sorted(items, key=lambda i: (i["slug"], i["id"]))
    if ctx == "topic":
        return sorted(items, key=lambda i: i["slug"])
    return items


def prune(value):
    """Rule E: drop null values, empty objects and empty lists (recursively)."""
    if isinstance(value, dict):
        pruned = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in pruned.items() if v is not None and v != {} and v != []}
    if isinstance(value, list):
        pruned = [prune(v) for v in value]
        return [v for v in pruned if v is not None and v != {} and v != []]
    return value


def _order(tree, ctx, path):
    table = KEY_ORDER[ctx]
    for key in tree:
        if key not in table:
            raise CanonicalError("unknown-key:" + (path + "." + key if path else key))
    children = CHILDREN.get(ctx, {})
    out = {}
    for key in table:
        if key not in tree:
            continue
        value = tree[key]
        child = children.get(key)
        sub = path + "." + key if path else key
        if child and isinstance(value, dict):
            value = _order(value, child, sub)
        elif child and isinstance(value, list):
            value = _sort_list(key, child, [_order(i, child, sub + "[]") for i in value])
        elif isinstance(value, list):
            value = _sort_list(key, ctx, value)
        out[key] = value
    return out


def canonicalize(tree, kind="record"):
    """Reorder keys, sort lists, drop empties. kind: record | tombstones | enum-topics | enum-list."""
    pruned = prune(tree)
    if kind == "enum-list":
        return sorted(pruned)
    if kind == "enum-topics":
        return _sort_list(None, "topic", [_order(i, "topic", "topic") for i in pruned])
    ordered = _order(pruned, ROOT_KIND[kind], "")
    if kind == "tombstones":
        ordered.setdefault("removed", [])
    return ordered


_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_UNICODE_ESCAPED = {0x7F, 0x85, 0x2028, 0x2029, 0xFEFF}


def _quote(text):
    out = ['"']
    for ch in text:
        code = ord(ch)
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif code < 0x20 or code in _UNICODE_ESCAPED:
            out.append("\\u%04x" % code)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _quote(value)
    raise TypeError("unsupported scalar %r" % (value,))


def _mapping(tree, indent):
    pad = " " * indent
    lines = []
    for key, value in tree.items():
        if isinstance(value, dict):
            lines.append("%s%s:" % (pad, key))
            lines.extend(_mapping(value, indent + 2))
        elif isinstance(value, list) and value:
            lines.append("%s%s:" % (pad, key))
            lines.extend(_sequence(value, indent + 2))
        elif isinstance(value, list):
            lines.append("%s%s: []" % (pad, key))
        else:
            lines.append("%s%s: %s" % (pad, key, _scalar(value)))
    return lines


def _sequence(items, indent):
    pad = " " * indent
    lines = []
    for item in items:
        if isinstance(item, dict):
            body = _mapping(item, indent + 2)
            lines.append(pad + "- " + body[0][indent + 2:])
            lines.extend(body[1:])
        else:
            lines.append("%s- %s" % (pad, _scalar(item)))
    return lines


def emit_yaml(tree):
    return "\n".join(_mapping(tree, 0)) + "\n"


def emit_json(tree):
    return json.dumps(tree, ensure_ascii=False, indent=2) + "\n"


def kind_of(path):
    """Which canonical kind a repository file is, by its path."""
    norm = path.replace(os.sep, "/")
    if norm.endswith("removed.yaml"):
        return "tombstones"
    if norm.endswith("enums/topics.json"):
        return "enum-topics"
    if "/enums/" in "/" + norm and norm.endswith(".json"):
        return "enum-list"
    return "record"


def canonical_text(tree, kind):
    canon = canonicalize(tree, kind)
    return emit_json(canon) if kind.startswith("enum") else emit_yaml(canon)


def load_tree(path):
    import yaml
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    return json.loads(text) if path.endswith(".json") else yaml.safe_load(text)


def _main(argv):
    if len(argv) < 3 or argv[1] not in ("--check", "--fix"):
        print(__doc__)
        return 2
    mode, files, status = argv[1], argv[2:], 0
    for path in files:
        try:
            wanted = canonical_text(load_tree(path), kind_of(path))
        except CanonicalError as error:
            print("%s: %s" % (path, error))
            status = 1
            continue
        with open(path, encoding="utf-8", newline="") as handle:
            current = handle.read()
        if current == wanted:
            continue
        if mode == "--fix":
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(wanted)
            print("rewrote " + path)
        else:
            print("canonical: %s differs; canonical text:\n%s" % (path, wanted))
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

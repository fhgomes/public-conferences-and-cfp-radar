#!/usr/bin/env python3
"""Build the downloadable bundles from the event files: JSON, JSONL, ICS, manifest and badges.

    python3 scripts/build_bundles.py --root . --out _site [--now 2026-10-20T06:15:00Z]

`updatedAt` of a record is the time of the last commit touching its file (one `git log --name-only` pass).
A file git does not know yet (not committed) and a tree outside git fall back to the HEAD commit time, then to --now.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "schema")
SCHEMA_FILES = ("event.schema.json", "bundle.schema.json")
MAX_EVENTS_BYTES = 15 * 1024 * 1024
ATTRIBUTION = ("Public Conferences and Call for Papers Radar - curated by Fernando Gomes, "
               "https://github.com/fhgomes/public-conferences-and-cfp-radar, CC BY 4.0")
UID_DOMAIN = "public-conferences-and-cfp-radar"


def utc_z(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_now(text):
    if text:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def git(root, *args):
    """stdout of a git command in root, or None when git says no (not a repository, no commit yet)."""
    result = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def head_info(root, now):
    out = git(root, "log", "-1", "--format=%H %cI")
    if not out or not out.strip():
        return "unknown", utc_z(now)
    sha, committed = out.split()
    return sha, utc_z(datetime.datetime.fromisoformat(committed))


def commit_times(root):
    """{path relative to root: UTC time of its last commit} from ONE git log pass."""
    out = git(root, "log", "--relative", "--name-only", "--format=@@%cI", "--", "events") or ""
    times, current = {}, None
    for line in out.splitlines():
        if line.startswith("@@"):
            current = utc_z(datetime.datetime.fromisoformat(line[2:]))
        elif line.strip():
            times.setdefault(line.strip(), current)
    return times


def load_records(root, now):
    sha, head_time = head_info(root, now)
    times = commit_times(root)
    records = []
    events = os.path.join(root, "events")
    for folder, _, names in os.walk(events):
        for name in names:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, encoding="utf-8") as handle:
                record = yaml.safe_load(handle)
            record["updatedAt"] = times.get(rel, head_time)
            records.append(record)
    with open(os.path.join(root, "removed.yaml"), encoding="utf-8") as handle:
        removed = yaml.safe_load(handle)["removed"]
    return sorted(records, key=lambda r: r["id"]), removed, sha, head_time


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def is_upcoming(record, today):
    dates = record["dates"]
    last = dates.get("end") or dates.get("start")
    return dates["tba"] or (last is not None and last >= today)


def is_cfp_open(record, today):
    cfp = record.get("cfp") or {}
    closes = cfp.get("closesOn")
    return closes is not None and closes >= today and cfp.get("opensOn", today) <= today


def escape_text(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """Fold a content line at 75 octets (continuation lines start with one space), never inside a character."""
    chunks, current, size, limit = [], "", 0, 75
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            chunks.append(current)
            current, size, limit = " ", 1, 75
        current += char
        size += width
    chunks.append(current)
    return "\r\n".join(chunks)


def next_day(date_text):
    day = datetime.date.fromisoformat(date_text) + datetime.timedelta(days=1)
    return day.strftime("%Y%m%d")


def compact_date(date_text):
    return date_text.replace("-", "")


def location_text(record):
    location = record.get("location") or {}
    if location.get("modality") == "ONLINE":
        return "Online"
    parts = [location.get("city"), location.get("countryCode")]
    return ", ".join(p for p in parts if p) or None


def calendar(events, stamp, name):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//public-conferences-and-cfp-radar//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:" + name]
    for event in events:
        lines += ["BEGIN:VEVENT"] + [l for l in event if l] + ["END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines).replace("{STAMP}", stamp)


def event_vevent(record):
    dates, cfp = record["dates"], record.get("cfp") or {}
    description = []
    if cfp.get("closesOn"):
        description.append("CFP closes on " + cfp["closesOn"] + (" - " + cfp["url"] if cfp.get("url") else ""))
    description.append(ATTRIBUTION)
    where = location_text(record)
    return [
        "UID:%s@%s" % (record["id"], UID_DOMAIN), "DTSTAMP:{STAMP}",
        "DTSTART;VALUE=DATE:" + compact_date(dates["start"]),
        "DTEND;VALUE=DATE:" + next_day(dates.get("end") or dates["start"]),
        "SUMMARY:" + escape_text(record["name"]),
        "LOCATION:" + escape_text(where) if where else "",
        "URL:" + record["links"]["website"] if record.get("links") else "",
        "DESCRIPTION:" + escape_text("\n".join(description)),
    ]


def cfp_vevent(record):
    cfp = record["cfp"]
    if cfp.get("closeTimeKnown") and cfp.get("closesAt"):
        when = ["DTSTART:" + cfp["closesAt"].replace("-", "").replace(":", "")]
    else:
        when = ["DTSTART;VALUE=DATE:" + compact_date(cfp["closesOn"]), "DTEND;VALUE=DATE:" + next_day(cfp["closesOn"])]
    link = cfp.get("url") or (record.get("links") or {}).get("website")
    return ["UID:%s-cfp@%s" % (record["id"], UID_DOMAIN), "DTSTAMP:{STAMP}"] + when + [
        "SUMMARY:" + escape_text("CFP closes: " + record["name"]),
        "URL:" + link if link else "",
        "DESCRIPTION:" + escape_text(ATTRIBUTION),
    ]


def build(records, removed, sha, head_time, now):
    today = now.strftime("%Y-%m-%d")
    stamp = head_time.replace("-", "").replace(":", "")
    texts = {
        "events.json": dumps(records) + "\n",
        "events.jsonl": "".join(dumps(r) + "\n" for r in records),
        "events-upcoming.json": dumps([r for r in records if is_upcoming(r, today)]) + "\n",
        "cfps-open.json": dumps([r for r in records if is_cfp_open(r, today)]) + "\n",
        "removed.json": dumps(removed) + "\n",
        "events.ics": calendar([event_vevent(r) for r in records if r["dates"].get("start")], stamp,
                               "Public Conferences Radar"),
        "cfps.ics": calendar([cfp_vevent(r) for r in records if (r.get("cfp") or {}).get("closesOn")], stamp,
                             "Call for Papers Radar"),
        "badges/events.json": dumps({"schemaVersion": 1, "label": "events", "message": str(len(records)),
                                     "color": "blue"}) + "\n",
        "badges/updated.json": dumps({"schemaVersion": 1, "label": "last export", "message": today,
                                      "color": "informational"}) + "\n",
    }
    files = {name: text.encode("utf-8") for name, text in texts.items()}
    for name in SCHEMA_FILES:
        with open(os.path.join(SCHEMA_DIR, name), "rb") as handle:
            files["schema/" + name] = handle.read()
    manifest = {
        "schemaVersion": 1, "generatedAt": utc_z(now), "commit": sha, "recordCount": len(records),
        "files": {n: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for n, b in sorted(files.items())},
        "licence": "CC-BY-4.0", "attribution": ATTRIBUTION,
    }
    files["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return files


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    now = parse_now(args.now)
    records, removed, sha, head_time = load_records(args.root, now)
    files = build(records, removed, sha, head_time, now)
    size = len(files["events.json"])
    if size > MAX_EVENTS_BYTES:
        print("build_bundles: events.json is %d bytes, over the %d byte budget" % (size, MAX_EVENTS_BYTES),
              file=sys.stderr)
        return 1
    for name, data in files.items():
        target = os.path.join(args.out, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    print("built %d records, %d files into %s" % (len(records), len(files), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

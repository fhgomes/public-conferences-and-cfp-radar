#!/usr/bin/env python3
"""Self test of the scripts: goldens, invalid cases, repository rules, bundle build. Prints `selftest ok <n>`.

    python3 -I scripts/selftest.py

The golden and invalid-case fixtures are the same files the platform's Java tests read (one copy, two readers).
"""
import contextlib
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import warnings

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_bundles  # noqa: E402
import canonical  # noqa: E402
import validate  # noqa: E402
import yaml  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

warnings.simplefilter("ignore", DeprecationWarning)
from jsonschema import RefResolver  # noqa: E402

ROOT = os.path.join(HERE, os.pardir)
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
GOLDEN_PAIRS = [("full", "record"), ("minimal", "record"), ("removed", "tombstones"), ("removed-empty", "tombstones")]
NOW = "2027-01-10T00:00:00Z"

failures, checks = [], 0


def check(condition, label):
    global checks
    checks += 1
    if not condition:
        failures.append(label)


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8", newline="") as handle:
        return handle.read()


def load_json(*parts):
    return json.loads(read(*parts))


def first_difference(wanted, got):
    for number, (a, b) in enumerate(zip(wanted.splitlines(), got.splitlines()), 1):
        if a != b:
            return "line %d: wanted %r got %r" % (number, a, b)
    return "length: wanted %d lines got %d" % (len(wanted.splitlines()), len(got.splitlines()))


def goldens():
    base = os.path.join(FIXTURES, "canonical")
    for name, kind in GOLDEN_PAIRS:
        tree, wanted = load_json(base, name + ".json"), read(base, name + ".yaml")
        got = canonical.canonical_text(tree, kind)
        check(got == wanted, "golden %s.yaml mismatch, %s" % (name, first_difference(wanted, got)))
        check(yaml.safe_load(wanted) == canonical.canonicalize(tree, kind), "golden %s.yaml does not parse back" % name)
    wanted = read(base, "topics.out.json")
    got = canonical.canonical_text(load_json(base, "topics.json"), "enum-topics")
    check(got == wanted, "golden topics.out.json mismatch, " + first_difference(wanted, got))
    for name in ("full", "minimal"):
        found = [code for code, _ in validate.check_record(load_json(base, name + ".json"))]
        check(found == [], "golden %s.json must be valid, got %s" % (name, found))


def invalid_cases():
    cases = load_json(FIXTURES, "invalid-cases.json")
    check(len(cases) == 16, "invalid-cases.json has %d cases, wanted 16" % len(cases))
    for case in cases:
        expect = case["expect"]
        wanted = expect["python"] if isinstance(expect, dict) else expect
        found = [code for code, _ in validate.check_record(case["record"])]
        check(wanted in found, "invalid case %s: wanted %s, got %s" % (case["name"], wanted, found))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def repo_rules():
    repo = os.path.join(FIXTURES, "repo")
    findings, count = validate.validate_repo(repo)
    check(findings == [] and count == 3, "fixture repo must validate: %s" % findings)
    event = read(repo, "events", "2027", "porto-java-days-2027.yaml")
    other = read(repo, "events", "tba", "tba-meetup-x.yaml")
    removed = read(repo, "removed.yaml")
    mutations = [
        ("path:folder-year", "events/tba/porto-java-days-2027.yaml", event),
        ("path:filename-slug", "events/2027/porto.yaml", event),
        ("canonical", "events/2027/porto-java-days-2027.yaml", event.replace("name:", "name:  ")),
        ("dup:id", "events/tba/dup.yaml", other.replace('slug: "tba-meetup-x"', 'slug: "dup"')),
        ("dup:slug", "events/tba/dup.yaml", other.replace("5a0d9a4e-7f43-4c1b-8a55-0c2d3e4f5a6b", "6a0d9a4e-7f43-4c1b-8a55-0c2d3e4f5a6b")),
        ("enum-file:topic", "events/2027/porto-java-days-2027.yaml", event.replace('"java"', '"nope"')),
        ("yaml", "events/2027/broken.yaml", "a: [unclosed\n"),
        ("removed:live-id", "removed.yaml", removed.replace("0b6f3a52-2c1e-4c55-9d1f-3f1a8f0e9a10", "5a0d9a4e-7f43-4c1b-8a55-0c2d3e4f5a6b", 1)
         .replace('"renamed"', '"merged"')),
    ]
    for code, rel, text in mutations:
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, "repo")
            shutil.copytree(repo, work)
            write(os.path.join(work, rel), text)
            found = [c for _, _, c, _ in validate.validate_repo(work)[0]]
            check(code in found, "repository rule %s not reported, got %s" % (code, found))
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "repo")
        shutil.copytree(repo, work)
        os.remove(os.path.join(work, "removed.yaml"))
        found = [c for _, _, c, _ in validate.validate_repo(work)[0]]
        check("path:removed-missing" in found, "a missing removed.yaml must be reported, got %s" % found)


def bundle_validator():
    schemas = {name: load_json(ROOT, "schema", name) for name in build_bundles.SCHEMA_FILES}
    store = {schema["$id"]: schema for schema in schemas.values()}
    bundle = schemas["bundle.schema.json"]
    resolver = RefResolver(base_uri=bundle["$id"], referrer=bundle, store=store)
    return Draft202012Validator(bundle, resolver=resolver)


def quiet_build(*args):
    """build_bundles.main without its progress output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return build_bundles.main(list(args))


def unfold(text):
    return text.replace("\r\n ", "")


def bundles():
    repo = os.path.join(FIXTURES, "repo")
    with tempfile.TemporaryDirectory() as out:
        check(quiet_build("--root", repo, "--out", out, "--now", NOW) == 0, "bundle build failed")
        events = load_json(out, "events.json")
        check(len(events) == 3, "events.json has %d records, wanted 3" % len(events))
        errors = [e.message for e in bundle_validator().iter_errors(events)]
        check(errors == [], "events.json does not validate against bundle.schema.json: %s" % errors[:2])
        check([e["id"] for e in events] == sorted(e["id"] for e in events), "events.json is not sorted by id")
        jsonl = read(out, "events.jsonl").splitlines()
        check([json.loads(line) for line in jsonl] == events, "events.jsonl differs from events.json")
        upcoming = {e["slug"] for e in load_json(out, "events-upcoming.json")}
        check(upcoming == {"devnexus-2027", "tba-meetup-x", "porto-java-days-2027"}, "events-upcoming: %s" % upcoming)
        check([e["slug"] for e in load_json(out, "cfps-open.json")] == ["porto-java-days-2027"], "cfps-open.json")
        check(len(load_json(out, "removed.json")) == 2, "removed.json must list both tombstones")
        ics_checks(out)
        manifest_checks(out)
    guard_check(repo)


def ics_checks(out):
    for name in ("events.ics", "cfps.ics"):
        with open(os.path.join(out, name), "rb") as handle:
            raw = handle.read()
        check(b"\n" not in raw.replace(b"\r\n", b""), name + " has a bare LF")
        check(all(len(line) <= 75 for line in raw.split(b"\r\n")), name + " has a line over 75 octets")
        text = unfold(raw.decode("utf-8"))
        check(text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n"), name + " framing")
        check(text.count("BEGIN:VEVENT") == text.count("END:VEVENT") > 0, name + " VEVENT count")
    events = unfold(read_bytes(out, "events.ics"))
    cfps = unfold(read_bytes(out, "cfps.ics"))
    check(events.count("BEGIN:VEVENT") == 2, "events.ics: one VEVENT per dated event (2)")
    check("DTEND;VALUE=DATE:20270220\r\n" in events, "events.ics: DTEND is end + 1")
    check("DTSTART:20261102T045900Z\r\n" in cfps, "cfps.ics: timed close in UTC")
    check("DTSTART;VALUE=DATE:20270215\r\n" in cfps, "cfps.ics: all-day close when the time is unknown")
    long_line = "DESCRIPTION:" + "Conferência é àçãõ " * 20
    folded = build_bundles.fold(long_line)
    check(unfold(folded) == long_line, "fold must be reversible")
    check(all(len(p.encode("utf-8")) <= 75 for p in folded.split("\r\n")), "fold exceeds 75 octets")
    when = datetime.datetime(2027, 1, 10, tzinfo=datetime.timezone.utc)
    check(build_bundles.utc_z(when) == "2027-01-10T00:00:00Z", "utc_z")


def read_bytes(out, name):
    with open(os.path.join(out, name), "rb") as handle:
        return handle.read().decode("utf-8")


def manifest_checks(out):
    manifest = load_json(out, "manifest.json")
    check(manifest["recordCount"] == 3 and manifest["schemaVersion"] == 1, "manifest header")
    check(manifest["licence"] == "CC-BY-4.0", "manifest licence")
    for name, entry in manifest["files"].items():
        with open(os.path.join(out, name), "rb") as handle:
            data = handle.read()
        check(hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["bytes"],
              "manifest entry %s does not match the file" % name)
    check({"events.json", "cfps.ics", "schema/event.schema.json", "badges/events.json"} <= set(manifest["files"]),
          "manifest lists the bundle files")


def guard_check(repo):
    original = build_bundles.MAX_EVENTS_BYTES
    build_bundles.MAX_EVENTS_BYTES = 10
    try:
        with tempfile.TemporaryDirectory() as out:
            check(quiet_build("--root", repo, "--out", out, "--now", NOW) == 1, "size guard must refuse")
            check(not os.path.exists(os.path.join(out, "events.json")), "size guard must write nothing")
    finally:
        build_bundles.MAX_EVENTS_BYTES = original


def main():
    goldens()
    invalid_cases()
    repo_rules()
    bundles()
    if failures:
        for line in failures:
            print("selftest FAIL: " + line)
        print("selftest: %d of %d checks failed" % (len(failures), checks))
        return 1
    print("selftest ok %d" % checks)
    return 0


if __name__ == "__main__":
    sys.exit(main())

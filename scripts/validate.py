#!/usr/bin/env python3
"""Validate the dataset: JSON Schema plus every Python rule of dataset-format section 7.

    python3 scripts/validate.py [--root .] [--github-annotations] [--base <ref>]

Exit 0 = valid. With --github-annotations each finding is also printed as
`::error file=<path>,line=<n>::<code> <message>` so it shows inline on a pull request.
With --base <ref> a file under events/ without an `id` is accepted when it is new compared with <ref>
(the radar assigns the id; the next export renames the file).
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canonical  # noqa: E402

import yaml  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "schema")

# PublicPrivacyContractTest.DENYLIST (compared case-insensitively) - a key containing "email" is denied too
DENYLIST = {k.lower() for k in (
    "fitScore", "fitWhy", "chance", "chanceScore", "chanceWhy", "action", "effectiveAction", "priority",
    "scoringNotes", "notes", "cfpNotes", "internalNotes", "reviewerNotes", "timeline", "aliases", "sourceKey",
    "submissions", "deliveries", "talks", "fitTalks", "talkFit", "bios", "bio", "preferredBioId",
    "legacyStatus", "dataQuality", "proposal", "cost", "forFernando", "renown", "lastImport", "contentStats",
    "createdBy", "version", "watchOuts", "lookingFor", "supportNotes", "submissionNotes", "apiKey", "token",
    "secret", "attention", "notice", "notices", "snooze", "snoozedUntil", "alsoMatched",
    "deck", "decks", "imagePrompt", "imagePrompts", "promptText", "negativePrompt", "referenceImages",
    "slideRef", "hints", "deadlineRaw", "externalId", "candidate",
    "quote", "confidence", "promptVersion", "proposalId", "proposals", "aiEstimates", "tokens",
    "sourceHash", "origin", "rejectReason", "translationStatus",
    "byStatus", "confirmationsPerWeek", "confirmationRate",
    "geoSource", "geoRef", "geoStatus", "geoReason", "venueHint", "inputKey", "geoUpdatedAt")}

EMAIL = re.compile(r"(?i)[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}")
PHONE = re.compile(r"(?<![\w/.-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,3}\)[ .-]?|\d{2,3}[ .-])\d{4,5}[ .-]?\d{4}(?![\w/-])")
CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EVENT_FILE = re.compile(r"^events/[^/]+/[^/]+\.yaml$")
FREE_TEXT = re.compile(r"^(name|edition|(nameNote|organizer|summary)\.[^.]+|location\.city)$")
DATE_PATHS = ("dates.start", "dates.end", "cfp.opensOn", "cfp.closesOn")
INSTANT_PATHS = ("cfp.opensAt", "cfp.closesAt", "verification.checkedAt", "cfp.verification.checkedAt",
                 "firstPublishedAt", "updatedAt")
REASONS = ("withdrawn", "merged", "renamed")
PATTERN_VALIDATORS = ("pattern", "minLength", "maxLength")
SKIPPED_SCHEMA_PATHS = ("anyOf", "then", "else", "not", "if")  # re-expressed as cross:* rules below


def load_schema(name):
    with open(os.path.join(SCHEMA_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def render_path(parts, strip_index=False):
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += "[]" if strip_index else "[%d]" % part
        else:
            out += ("." if out else "") + part
    return out


def schema_findings(record, validator):
    found = []
    for error in validator.iter_errors(record):
        if any(step in SKIPPED_SCHEMA_PATHS for step in error.schema_path):
            continue
        parts, kind = list(error.absolute_path), error.validator
        if kind == "required":
            found += [("required:" + render_path(parts + [k], True), "missing required key")
                      for k in error.validator_value if k not in error.instance]
        elif kind == "additionalProperties":
            allowed = error.schema.get("properties", {})
            found += [("unknown-key:" + render_path(parts + [k]), "key is not part of the format")
                      for k in error.instance if k not in allowed]
        elif kind == "type":
            found.append(("type:" + render_path(parts), error.message))
        elif kind in PATTERN_VALIDATORS:
            found.append(("pattern:" + render_path(parts), error.message))
        elif kind in ("enum", "const"):
            found.append(("enum:" + render_path(parts), error.message))
        else:
            found.append(("schema:%s@%s" % (kind, render_path(parts)), error.message))
    return found


def walk_strings(value, parts=()):
    if isinstance(value, str):
        yield render_path(parts), value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from walk_strings(child, parts + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_strings(child, parts + (index,))


def walk_keys(value, parts=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield render_path(parts + (key,)), key
            yield from walk_keys(child, parts + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_keys(child, parts + (index,))


def at(record, dotted):
    node = record
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def real_date(text):
    try:
        datetime.date.fromisoformat(text)
        return True
    except ValueError:
        return False


def real_instant(text):
    try:
        datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def calendar_findings(record):
    found = []
    for dotted, check in [(p, real_date) for p in DATE_PATHS] + [(p, real_instant) for p in INSTANT_PATHS]:
        value = at(record, dotted)
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value) and not check(value):
            found.append(("pattern:" + dotted, "not a real calendar value: " + value))
    return found


def valid_date(record, dotted):
    value = at(record, dotted)
    return value if isinstance(value, str) and real_date(value) else None


def cross_findings(record):
    found = []
    start, end = valid_date(record, "dates.start"), valid_date(record, "dates.end")
    opens, closes = valid_date(record, "cfp.opensOn"), valid_date(record, "cfp.closesOn")
    if start and end and end < start:
        found.append(("cross:end-before-start", "dates.end is before dates.start"))
    if at(record, "location.modality") == "ONLINE" and at(record, "location.city"):
        found.append(("cross:online-with-city", "an ONLINE event has no city"))
    if end and closes and closes > end:
        found.append(("cross:closes-after-end", "cfp.closesOn is after dates.end"))
    if opens and closes and opens > closes:
        found.append(("cross:opens-after-closes", "cfp.opensOn is after cfp.closesOn"))
    remote = at(record, "remoteSpeaking")
    if isinstance(remote, dict) and "mode" in remote and remote.get("value") != "YES":
        found.append(("cross:mode-without-yes", "remoteSpeaking.mode needs value YES"))
    if not at(record, "links.website") and not at(record, "cfp.url"):
        found.append(("cross:no-link", "neither links.website nor cfp.url"))
    for entry in record.get("machineTranslated") or []:
        field, _, locale = str(entry).partition(".")
        if not at(record, field + "." + locale):
            found.append(("cross:machine-translated", "%s names a text that is not present" % entry))
    for where in ("verification", "cfp.verification"):
        found += verification_findings(where, at(record, where))
    return found


def verification_findings(where, verification):
    if not isinstance(verification, dict):
        return []
    status, by = verification.get("status"), verification.get("by")
    if status == "unverified" and ("checkedAt" in verification or "by" in verification):
        return [("cross:verification-by", where + ": unverified carries no checkedAt or by")]
    if status == "human_verified" and by not in (None, "curator"):
        return [("cross:verification-by", where + ": human_verified is checked by curator")]
    if status == "official_source_checked" and by not in (None, "official-page-check"):
        return [("cross:verification-by", where + ": official_source_checked is checked by official-page-check")]
    return []


def privacy_findings(record):
    found = []
    for path, key in walk_keys(record):
        if key.lower() in DENYLIST or "email" in key.lower():
            found.append(("privacy:key@" + path, "key is on the privacy denylist"))
    for path, text in walk_strings(record):
        if EMAIL.search(text):
            found.append(("pii:email@" + path, "looks like an e-mail address"))
        if FREE_TEXT.match(re.sub(r"\[\d+\]", "", path)) and PHONE.search(text):
            found.append(("pii:phone@" + path, "looks like a phone number"))
        if CPF.search(text):
            found.append(("pii:cpf@" + path, "looks like a CPF number"))
    return found


def enum_findings(record, topics, countries):
    found = []
    if topics is not None:
        found += [("enum-file:topic", "topic %s is not in enums/topics.json" % t)
                  for t in record.get("topics") or [] if t not in topics]
    code = at(record, "location.countryCode")
    if countries is not None and code and code not in countries:
        found.append(("enum-file:country", "country %s is not in enums/countries.json" % code))
    return found


def check_record(record, topics=None, countries=None):
    """All record-level findings as (code, message), in a stable order. topics/countries: sets or None (skip)."""
    tree = canonical.prune(record)
    validator = Draft202012Validator(load_schema("event.schema.json"))
    found = schema_findings(tree, validator)
    if isinstance(tree, dict):
        found += calendar_findings(tree) + cross_findings(tree) + privacy_findings(tree) + enum_findings(tree, topics, countries)
    return found


def find_line(text, code):
    """Line of the last key named in the code's path (1 when it cannot be found)."""
    path = code.partition("@")[2] or code.partition(":")[2]
    keys = [k for k in re.split(r"[.\[\]]", path) if k and not k.isdigit()]
    if keys:
        pattern = re.compile(r"^\s*(- )?%s:" % re.escape(keys[-1]))
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.match(line):
                return number
    return 1


class Repo:
    def __init__(self, root, base):
        self.root, self.base, self.findings = root, base, []

    def add(self, rel, code, message, text=""):
        self.findings.append((rel, find_line(text, code), code, message))

    def read(self, rel):
        path = os.path.join(self.root, rel)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()

    def new_files(self):
        if not self.base:
            return set()
        result = subprocess.run(["git", "-C", self.root, "diff", "--name-only", "--diff-filter=A", self.base],
                                capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise SystemExit("validate: cannot compare with %s: %s" % (self.base, result.stderr.strip()))
        return set(result.stdout.split())

    def parse(self, rel, text):
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as error:
            line = getattr(getattr(error, "problem_mark", None), "line", 0) + 1
            self.findings.append((rel, line, "yaml", "not valid YAML: " + str(error).splitlines()[0]))
            return None

    def check_canonical(self, rel, text, tree, kind):
        try:
            wanted = canonical.canonical_text(tree, kind)
        except canonical.CanonicalError as error:
            self.add(rel, str(error), "key is not part of the format", text)
            return
        if wanted != text:
            self.add(rel, "canonical", "not in canonical form; run: python3 scripts/canonical.py --fix " + rel, text)

    def enum_set(self, rel, kind):
        text = self.read(rel)
        if text is None:
            self.findings.append((rel, 1, "enum-file:missing", rel + " is missing"))
            return None
        try:
            tree = json.loads(text)
        except json.JSONDecodeError as error:
            self.findings.append((rel, error.lineno, "json", "not valid JSON: " + error.msg))
            return None
        before = len(self.findings)
        self.check_canonical(rel, text, tree, kind)
        if len(self.findings) > before:
            return None
        return {item["slug"] for item in tree} if kind == "enum-topics" else set(tree)

    def event_files(self):
        found = []
        for folder, _, names in os.walk(os.path.join(self.root, "events")):
            found += [os.path.relpath(os.path.join(folder, n), self.root).replace(os.sep, "/") for n in names]
        return sorted(found)

    def check_event(self, rel, topics, countries, new_files):
        text = self.read(rel)
        if not EVENT_FILE.match(rel):
            self.add(rel, "path:layout", "events live in events/<YYYY|tba>/<slug>.yaml")
            return None
        record = self.parse(rel, text)
        if record is None:
            return None
        if not isinstance(record, dict):
            self.add(rel, "type:", "a record is a mapping", text)
            return None
        before = len(self.findings)
        has_id = "id" in record
        if "updatedAt" in record:
            self.add(rel, "unknown-key:updatedAt", "updatedAt exists in bundles only", text)
        for code, message in check_record(record, topics, countries):
            if code == "required:id" and rel in new_files:
                continue
            self.add(rel, code, message, text)
        if has_id:
            self.check_path(rel, record, text)
        if len(self.findings) == before:
            self.check_canonical(rel, text, record, "record")
        return record

    def check_path(self, rel, record, text):
        folder, name = rel.split("/")[1], rel.split("/")[2]
        start = at(record, "dates.start")
        year = start[:4] if isinstance(start, str) and re.match(r"^\d{4}", start) else "tba"
        if folder != year:
            self.add(rel, "path:folder-year", "folder %s but dates.start says %s" % (folder, year), text)
        if name != "%s.yaml" % record.get("slug"):
            self.add(rel, "path:filename-slug", "file name must be <slug>.yaml", text)

    def check_unique(self, records):
        for key, code in (("id", "dup:id"), ("slug", "dup:slug")):
            seen = {}
            for rel, record in records:
                value = record.get(key)
                if value is None:
                    continue
                if value in seen:
                    self.add(rel, code, "%s %s is also used by %s" % (key, value, seen[value]), self.read(rel))
                seen.setdefault(value, rel)

    def check_removed(self, records):
        rel = "removed.yaml"
        text = self.read(rel)
        if text is None:
            self.findings.append((rel, 1, "path:removed-missing", "removed.yaml is always present (removed: [])"))
            return
        tree = self.parse(rel, text)
        if tree is None:
            return
        before = len(self.findings)
        items = tree.get("removed") if isinstance(tree, dict) else None
        if not isinstance(items, list):
            self.add(rel, "type:removed", "removed must be a list", text)
            return
        live_ids = {r.get("id") for _, r in records}
        live_slugs = {r.get("slug") for _, r in records}
        for item in items:
            self.check_tombstone(rel, text, item, live_ids, live_slugs)
        if len(self.findings) == before:
            self.check_canonical(rel, text, tree, "tombstones")

    def check_tombstone(self, rel, text, item, live_ids, live_slugs):
        if not isinstance(item, dict):
            self.add(rel, "type:removed", "a tombstone is a mapping", text)
            return
        for key in ("id", "slug", "reason", "removedOn"):
            if key not in item:
                self.add(rel, "required:removed[]." + key, "missing required key", text)
        for key, ok in (("id", UUID), ("replacedBy", UUID), ("slug", SLUG)):
            if key in item and not (isinstance(item[key], str) and ok.match(item[key])):
                self.add(rel, "pattern:removed[]." + key, "invalid " + key, text)
        if "reason" in item and item["reason"] not in REASONS:
            self.add(rel, "enum:removed[].reason", "reason is one of " + ", ".join(REASONS), text)
        if "removedOn" in item and not (isinstance(item["removedOn"], str) and real_date(item["removedOn"])):
            self.add(rel, "pattern:removed[].removedOn", "not a real calendar date", text)
        if item.get("reason") != "renamed" and item.get("id") in live_ids:
            self.add(rel, "removed:live-id", "a withdrawn or merged id has a file in events/", text)
        if item.get("slug") in live_slugs:
            self.add(rel, "removed:live-slug", "the removed slug has a file in events/", text)


def validate_repo(root, base=None):
    repo = Repo(root, base)
    topics = repo.enum_set("enums/topics.json", "enum-topics")
    countries = repo.enum_set("enums/countries.json", "enum-list")
    repo.enum_set("enums/modalities.json", "enum-list")
    new_files = repo.new_files()
    records = []
    for rel in repo.event_files():
        record = repo.check_event(rel, topics, countries, new_files)
        if record is not None:
            records.append((rel, record))
    repo.check_unique(records)
    repo.check_removed(records)
    return repo.findings, len(records)


def escape_annotation(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--github-annotations", action="store_true")
    parser.add_argument("--base")
    args = parser.parse_args(argv)
    warnings.simplefilter("ignore", DeprecationWarning)
    findings, count = validate_repo(args.root, args.base)
    for rel, line, code, message in findings:
        print("%s:%d: %s %s" % (rel, line, code, message))
        if args.github_annotations:
            print("::error file=%s,line=%d::%s" % (rel, line, escape_annotation("%s %s" % (code, message))))
    if findings:
        print("validate: %d finding(s) in %d event file(s)" % (len(findings), count))
        return 1
    print("validate ok: %d event file(s)" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

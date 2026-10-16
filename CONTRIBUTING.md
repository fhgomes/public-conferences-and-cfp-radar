# Contributing

Thank you for helping keep the dataset correct. By contributing you agree that your contribution is released under CC BY 4.0
(data) or MIT (scripts).

## What to send

- **A new event**: open the "New event" issue form, or add one file `events/<year>/<slug>.yaml` in a pull request. Leave `id` out:
  the radar assigns it and the next export renames the file to its final name.
- **A correction**: open the "Fix event" issue form with a public source URL, or edit the one file in a pull request.
- Edit **one file per pull request**.

## Rules

- **Public facts only.** Never add personal contact data: e-mail addresses, phone numbers, speakers, attendees. The validation
  fails on them.
- Every event needs a link: `links.website` or `cfp.url`.
- Give a public source for what you change (the official event page is best).
- `verification` tells readers how much to trust a record: `human_verified` (a curator confirmed it), `official_source_checked`
  (the official page was read automatically), `unverified`. Do not set it yourself; the radar sets it when it reviews your change.

## Canonical form

Files have one exact layout (key order, double-quoted strings, LF line ends) so that exports and edits never produce noise.
Rewrite a file into that form with:

```bash
pip install -r scripts/requirements.txt
python3 scripts/canonical.py --fix events/2027/my-event.yaml
python3 scripts/validate.py
```

## How a pull request becomes data

1. The `validate` check runs the schema and the rules (it comments inline on the lines that fail).
2. The maintainer merges the pull request.
3. The change is reviewed in the radar before it becomes part of the dataset.
4. The next export makes the file match the reviewed data (a rejected change is reverted by that export).

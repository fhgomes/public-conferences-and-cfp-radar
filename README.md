# Public Conferences and Call for Papers Radar

[![Data licence: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-blue)](https://creativecommons.org/licenses/by/4.0/)
![Events](https://img.shields.io/endpoint?url=https%3A%2F%2Ffhgomes.github.io%2Fpublic-conferences-and-cfp-radar%2Fbadges%2Fevents.json)
![Last export](https://img.shields.io/endpoint?url=https%3A%2F%2Ffhgomes.github.io%2Fpublic-conferences-and-cfp-radar%2Fbadges%2Fupdated.json)
[![validate](https://github.com/fhgomes/public-conferences-and-cfp-radar/actions/workflows/validate.yml/badge.svg)](https://github.com/fhgomes/public-conferences-and-cfp-radar/actions/workflows/validate.yml)

An open dataset of tech conferences and their Calls for Papers: dates, places, links, CFP windows and sources. It is exported
daily from the cfp-radar platform and is open to corrections: every event is one YAML file in `events/`.

## How to cite

> Public Conferences and Call for Papers Radar — curated by Fernando Gomes, https://github.com/fhgomes/public-conferences-and-cfp-radar, CC BY 4.0

## Disclaimer

Entries marked `unverified` were collected automatically and not confirmed by a human; always check the official event page before submitting.

`verification.status` has three values: `human_verified` (a curator confirmed it), `official_source_checked` (the official page was
read by an automatic check) and `unverified`. A `cfp` block carries its own `verification` for the deadline.

## Get the data

Everything below is rebuilt on every push to `main` and once a day (so "upcoming" and "open" stay current):

| File | Content |
|---|---|
| https://fhgomes.github.io/public-conferences-and-cfp-radar/events.json | all events (array) |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/events.jsonl | the same, one record per line |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/events-upcoming.json | events that have not ended, plus date-to-be-announced ones |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/cfps-open.json | events whose CFP is open today |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/events.ics | calendar: one all-day entry per dated event |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/cfps.ics | calendar: one entry per CFP deadline |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/removed.json | withdrawn, merged and renamed entries |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/manifest.json | counts, sha256 and size of every file |
| https://fhgomes.github.io/public-conferences-and-cfp-radar/schema/event.schema.json | JSON Schema of one record |

Single files: `https://raw.githubusercontent.com/fhgomes/public-conferences-and-cfp-radar/main/events/<year>/<slug>.yaml`.
Monthly snapshots are published as releases named `data-YYYY.MM`.

## Example

Open CFPs closing in the next 30 days (needs `curl` and `jq`):

```bash
curl -s https://fhgomes.github.io/public-conferences-and-cfp-radar/cfps-open.json \
  | jq -r --arg limit "$(date -u -d '+30 days' +%F)" '
      .[] | select(.cfp.closesOn != null and .cfp.closesOn <= $limit)
      | [.name, .cfp.closesOn, (.cfp.url // .links.website)] | @tsv'
```

Subscribe to `cfps.ics` in your calendar app to get every deadline as an entry.

## Fields

A key that is absent means unknown. No key holds an empty object or an empty list.

| Key | Meaning |
|---|---|
| `id` | stable identifier (UUID); never reused |
| `slug` | URL-friendly name; equals the file name |
| `name`, `edition` | event name and edition label |
| `nameNote`, `organizer`, `summary` | texts, per language (`en`, `pt-BR`) |
| `machineTranslated` | which texts above were machine translated (`summary.pt-BR`) |
| `dates` | `start`, `end` (`YYYY-MM-DD`), `tba`, `status` (`CONFIRMED`, `ESTIMATED`, `ESTIMATED_HISTORICAL`, `UNKNOWN`, `RECURRING`) |
| `location` | `city`, `cityStatus` (`TBA`, `MULTIPLE`), `countryCode` (ISO 3166-1 alpha-2), `region`, `modality` (`IN_PERSON`, `ONLINE`, `HYBRID`) |
| `geo` | `lat`, `lng` (decimal strings), `precision` (`CITY`, `VENUE`) |
| `links` | `website` |
| `topics` | slugs listed in `enums/topics.json` |
| `talkLanguages` | languages of the talks |
| `eventType`, `audienceLevel` | classification |
| `remoteSpeaking` | `value` (`YES`, `NO`), `mode` (only with `YES`), `basis` |
| `cfp.opensOn`, `cfp.opensAt` | when the CFP opens (date, UTC instant) |
| `cfp.closesOn`, `cfp.closesAt`, `cfp.timezone`, `cfp.closeTimeKnown` | the deadline; `closesAt` is UTC |
| `cfp.url`, `cfp.platform` | where to submit and on which platform |
| `cfp.formats` | accepted `format`, `durationMinutes`, `maxSpeakers` |
| `cfp.firstTimeSpeakersWelcome` | first-time speakers welcome |
| `cfp.benefits` | `travel`, `hotel`, `fee`, `ticket` as `YES`, `PARTIAL`, `NO` |
| `cfp.verification` | verification of the deadline |
| `verification` | `status`, `checkedAt`, `by` for the event |
| `sources` | where the record comes from: `code`, `name`, `url`, `licence`, `role` |
| `firstPublishedAt` | when the event first appeared in the dataset |
| `updatedAt` | bundles only: time of the last commit that touched the file |

## Stable ids

Key your data on `id`. A slug can change (a rename or a merge), the id does not. `removed.yaml` (and `removed.json`) lists
withdrawn, merged and renamed entries with the reason, the surviving id (`replacedBy`) and the date.

## Sources and licences

| Source | Licence | Role |
|---|---|---|
| cfp-radar | CC BY 4.0 | origin |
| confs.tech | MIT | origin (notice in `NOTICE.md`) |
| javaconferences.org | CC0 | origin |
| developers.events | data CC BY-NC 4.0, code MIT | facts only, `discovered_via` |
| Calling All Papers, agenda-tech-brasil, dev.events, cfp.watch | not stated | facts only, `discovered_via` |
| the radar's discovery agent | n/a | — |

Facts (names, dates, places, links) are not copyrightable; no description or tag from a NonCommercial or unlicensed source is ever copied.
Takedown: open an issue; the source's records or texts leave the next export.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Pull requests and issue forms are welcome. Changes are reviewed in the radar before they become part of the dataset; the next export makes the file match the reviewed data.

## No personal data

This dataset contains no personal data: no e-mail addresses, phone numbers, speakers or attendees. Do not add any.

## Licence

Data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (`LICENSE`). Scripts: MIT (`LICENSE-CODE`). Third parties: `NOTICE.md`.

# browser-trail

**Your browser remembers more than you think.** Reads the local profiles of every Chromium browser
and Firefox on the machine and gives you one merged, searchable timeline: history, downloads with
their real target paths, bookmarks with folders, and per-profile totals — saved logins, autofill
rows and cookie domains counted, never read.

Pure Python standard library. No cookies exported, no password decryption.

```
$ python main.py summary

┌─ chrome / Default
    path        C:\Users\you\AppData\Local\Google\Chrome\User Data\Default
    activity    19800 visits, 2095 downloads, 26 bookmarks
    secrets     0 saved logins, 1117 autofill rows, 0 cookie hosts
    range       2026-08-28 15:43 .. 2026-11-26 09:01
    top hosts   www.youtube.com (2890), github.com (1477), www.unknowncheats.me (409)
```

---

## Why

Two honest uses:

1. **Your own machine.** What did I download last week, in which browser, to which path? Which
   profile still has 2000 downloads I forgot about? Which sites dominate my history?
2. **An incident.** A machine was used and you need the timeline: visits, downloads and the exact
   target paths, merged across Chrome, Edge, Brave, Opera and Firefox, filtered by date and query.

The tool never prints a cookie value, a password or a token. Counts and origins only, because the
question is "what happened", not "what is the password".

## Install

Python 3.10+, nothing else.

```bash
git clone https://github.com/Pajt9whauht283as/browser-trail
cd browser-trail
python main.py profiles
```

```bash
pip install .        # gives you the browser-trail command
```

## Commands

| Command | Output |
|---|---|
| `profiles` | every detected profile, with which artifacts exist |
| `summary` | visits, downloads, bookmarks, logins, autofill, cookie hosts, date range, top hosts |
| `history` | merged timeline: time, browser, profile, title, url |
| `downloads` | time, file, size, real target path, source url |
| `bookmarks` | folder path, name, url |

Filters on every command:

| Flag | Meaning |
|---|---|
| `--since 2026-11-01` / `--since 7d` | lower bound (`7d`, `24h`, `90m`, `2w`) |
| `--until` | upper bound |
| `--query text` | substring match on url/title/target |
| `--limit N` | rows to print (default 50) |
| `--browser chrome` | restrict to one browser |
| `--profile PATH` | read a single profile directory |
| `--root PATH` | scan a different User Data directory |
| `--csv` / `--json` | export instead of table |

Examples:

```bash
python main.py history --since 7d --query github --limit 20
python main.py downloads --since 30d --csv > downloads.csv
python main.py bookmarks --query tools
python main.py summary --json
```

## What is read

| Artifact | Chromium | Firefox | Content |
|---|---|---|---|
| history | `History` (`urls`) | `places.sqlite` (`moz_places`) | url, title, visit count, last visit |
| downloads | `History` (`downloads`) | — | target path, source url, size, start time |
| bookmarks | `Bookmarks` (JSON tree) | `places.sqlite` (`moz_bookmarks`) | name, url, folder path |
| autofill | `Web Data` (`autofill`) | — | row count only |
| logins | `Login Data` (`logins`) | — | row count only |
| cookies | `Network/Cookies` (`cookies`) | — | distinct host count only |

Browsers detected out of the box: Chrome, Edge, Brave, Opera, Opera GX, Vivaldi, Chromium and
Firefox, including every `Profile N` directory.

## Locked databases

A running browser keeps its SQLite files open, and on Windows a plain copy fails with
"being used by another process". `trail/browsers.py` handles that properly:

1. try a normal copy;
2. if it fails, open the file with `CreateFileW` and `FILE_SHARE_READ | WRITE | DELETE`, then copy
   through `msvcrt.open_osfhandle`;
3. if even that is refused, degrade to an empty snapshot so one locked artifact does not take the
   whole report down.

Every read happens on a temp copy, opened read-only. The originals are never modified and never
locked longer than the copy. `-wal` and `-shm` sidecars travel with the copy so recent writes are
included.

## Timestamps

Chromium stores microseconds since 1601-01-01 UTC, Firefox microseconds since the Unix epoch.
Both are converted to timezone-aware UTC datetimes and displayed in local time.

## Limits

- **Firefox downloads** are not in `places.sqlite` in a form worth guessing at; not implemented
  rather than approximated.
- **Sessions, tabs, cache and service workers** are not read. This is history, downloads and
  bookmarks.
- **Profiles are read as they are on disk.** If the browser is mid-write, the snapshot is a
  consistent past state, not necessarily the last second.
- **Cookie and login values are deliberately never decrypted.** The counts are the useful signal;
  the secrets are not this tool's job.

## Tests

```bash
python -m unittest discover -s tests -v     # 12 tests
```

The fixtures build a real Chromium profile: `History` with `urls`/`downloads`, a nested
`Bookmarks` JSON tree, `Web Data`, `Login Data` and a `Network/Cookies` database — so discovery,
queries, filters, the JSON walk and the summary are all exercised without touching a real browser.

## License

MIT.

"""Command line for browser-trail."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from . import browsers

VERSION = "1.0.0"
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(code, text):
    return "\x1b[%sm%s\x1b[0m" % (code, text) if COLOR else text


def bold(t):
    return _paint("1", t)


def dim(t):
    return _paint("2", t)


def cyan(t):
    return _paint("36", t)


def green(t):
    return _paint("32", t)


def yellow(t):
    return _paint("33", t)


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024:
            return "%.0f %s" % (size, unit)
        size /= 1024.0
    return "%.1f TB" % size


def table(headers, rows, right=()):
    if not rows:
        print("  " + dim("(nothing)"))
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print("  " + dim("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))))
    print("  " + dim("  ".join("─" * width for width in widths)))
    for row in rows:
        cells = [cell.rjust(widths[i]) if i in right else cell.ljust(widths[i])
                 for i, cell in enumerate(row)]
        print("  " + "  ".join(cells))


def select_profiles(args) -> list[browsers.Profile]:
    if args.profile:
        found = browsers.discover(root=args.profile)
        if not found:
            print(yellow("no Chromium-style History file in %s" % args.profile))
        return found
    found = browsers.discover(root=args.root, browser=args.browser)
    if not found:
        print(yellow("no browser profiles found"))
    return found


def stamp(value) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else "-"


def cmd_profiles(args) -> int:
    profiles = select_profiles(args)
    if not profiles:
        return 1
    print()
    print(cyan("┌─ ") + bold("profiles"))
    rows = []
    for profile in profiles:
        artifacts = ", ".join(name for name in ("history", "downloads", "bookmarks", "autofill",
                                                "logins", "cookies") if profile.has(name))
        rows.append([profile.browser, profile.name, artifacts or "-", profile.path])
    table(["browser", "profile", "artifacts", "path"], rows)
    if args.json:
        print(json.dumps([{"browser": p.browser, "name": p.name, "path": p.path,
                           "artifacts": [a for a in ("history", "downloads", "bookmarks",
                                                     "autofill", "logins", "cookies") if p.has(a)]}
                          for p in profiles], indent=2))
    return 0


def cmd_summary(args) -> int:
    profiles = select_profiles(args)
    if not profiles:
        return 1
    summaries = [browsers.summarize(profile) for profile in profiles]
    payload = []
    for summary in summaries:
        profile = summary.profile
        print()
        print(cyan("┌─ ") + bold(profile.label))
        print("    %-11s %s" % (dim("path"), profile.path))
        print("    %-11s %d visits, %d downloads, %d bookmarks"
              % (dim("activity"), summary.visits, summary.downloads, summary.bookmarks))
        if profile.kind == "chromium":
            print("    %-11s %d saved logins, %d autofill rows, %d cookie hosts"
                  % (dim("secrets"), summary.logins, summary.autofill, summary.cookie_hosts))
        if summary.first:
            print("    %-11s %s .. %s" % (dim("range"), stamp(summary.first), stamp(summary.last)))
        if summary.top_hosts:
            print("    %-11s %s" % (dim("top hosts"), ", ".join(
                "%s (%d)" % (host, count) for host, count in summary.top_hosts[:6])))
        payload.append({
            "browser": profile.browser, "profile": profile.name, "path": profile.path,
            "visits": summary.visits, "downloads": summary.downloads,
            "bookmarks": summary.bookmarks, "autofill": summary.autofill,
            "logins": summary.logins, "cookie_hosts": summary.cookie_hosts,
            "first": summary.first.isoformat() if summary.first else None,
            "last": summary.last.isoformat() if summary.last else None,
            "top_hosts": summary.top_hosts,
        })
    print()
    print(dim("  cookie values and passwords are never read: counts only"))
    if args.json:
        print(json.dumps(payload, indent=2))
    return 0


def cmd_history(args) -> int:
    since = browsers.parse_when(args.since)
    until = browsers.parse_when(args.until)
    visits = []
    for profile in select_profiles(args):
        visits.extend(browsers.history(profile, since, until, args.query, args.limit))
    visits.sort(key=lambda item: item.when or 0, reverse=True)
    visits = visits[: args.limit]

    if args.csv:
        writer = csv.writer(sys.stdout)
        writer.writerow(["time", "browser", "profile", "title", "url"])
        for visit in visits:
            writer.writerow([visit.when.isoformat() if visit.when else "", visit.browser,
                             visit.profile, visit.title, visit.url])
        return 0

    print()
    print(cyan("┌─ ") + bold("history") + dim("  %d entries" % len(visits)))
    rows = [[stamp(visit.when), visit.browser, (visit.title or visit.url)[:78], visit.url[:60]]
            for visit in visits]
    table(["time", "browser", "title", "url"], rows)
    if args.json:
        print(json.dumps([{"time": v.when.isoformat() if v.when else None, "browser": v.browser,
                           "profile": v.profile, "title": v.title, "url": v.url}
                          for v in visits], indent=2))
    return 0


def cmd_downloads(args) -> int:
    since = browsers.parse_when(args.since)
    until = browsers.parse_when(args.until)
    items = []
    for profile in select_profiles(args):
        items.extend(browsers.downloads(profile, since, until, args.query, args.limit))
    items.sort(key=lambda item: item.when or 0, reverse=True)
    items = items[: args.limit]

    if args.csv:
        writer = csv.writer(sys.stdout)
        writer.writerow(["time", "browser", "target", "source", "bytes"])
        for item in items:
            writer.writerow([item.when.isoformat() if item.when else "", item.browser,
                             item.target, item.source, item.total_bytes])
        return 0

    print()
    print(cyan("┌─ ") + bold("downloads") + dim("  %d entries" % len(items)))
    rows = [[stamp(item.when), item.browser, os.path.basename(item.target)[:60],
             human(item.total_bytes), item.target[:60]] for item in items]
    table(["time", "browser", "file", "size", "target"], rows, right=(3,))
    if args.json:
        print(json.dumps([{"time": d.when.isoformat() if d.when else None, "browser": d.browser,
                           "profile": d.profile, "target": d.target, "source": d.source,
                           "bytes": d.total_bytes} for d in items], indent=2))
    return 0


def cmd_bookmarks(args) -> int:
    items = []
    for profile in select_profiles(args):
        items.extend(browsers.bookmarks(profile))
    if args.query:
        needle = args.query.lower()
        items = [item for item in items
                 if needle in item.name.lower() or needle in item.url.lower()]
    print()
    print(cyan("┌─ ") + bold("bookmarks") + dim("  %d entries" % len(items)))
    rows = [[item.browser, item.folder[:28], item.name[:50] or "-", item.url[:60]]
            for item in items[: args.limit]]
    table(["browser", "folder", "name", "url"], rows)
    if args.json:
        print(json.dumps([{"browser": b.browser, "profile": b.profile, "folder": b.folder,
                           "name": b.name, "url": b.url} for b in items], indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="browser-trail",
        description="Read local browser history, downloads and bookmarks across every profile.",
        epilog="examples:\n"
               "  main.py profiles\n"
               "  main.py summary\n"
               "  main.py history --since 7d --query github\n"
               "  main.py downloads --since 30d --csv\n"
               "  main.py history --profile \"C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data\\Default\"\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="browser-trail " + VERSION)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="User Data directory to scan instead of the defaults")
    common.add_argument("--browser", help="chrome, edge, brave, opera, vivaldi, firefox")
    common.add_argument("--profile", help="a single profile directory")
    common.add_argument("--query", help="substring filter")
    common.add_argument("--since", help="2026-11-20 or 7d / 24h / 90m")
    common.add_argument("--until")
    common.add_argument("--limit", type=int, default=50)
    common.add_argument("--json", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("profiles", parents=[common], help="list detected profiles")
    p.set_defaults(func=cmd_profiles)
    p = sub.add_parser("summary", parents=[common], help="per-profile statistics")
    p.set_defaults(func=cmd_summary)
    p = sub.add_parser("history", parents=[common], help="merged history timeline")
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_history)
    p = sub.add_parser("downloads", parents=[common], help="download records with target paths")
    p.add_argument("--csv", action="store_true")
    p.set_defaults(func=cmd_downloads)
    p = sub.add_parser("bookmarks", parents=[common], help="bookmarks with folders")
    p.set_defaults(func=cmd_bookmarks)
    return parser


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        return 130

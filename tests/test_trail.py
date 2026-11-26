"""Tests: python -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from trail import browsers  # noqa: E402

EPOCH = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def chrome_stamp(when: datetime) -> int:
    return int((when.timestamp() + browsers.CHROME_EPOCH_OFFSET) * 1_000_000)


def build_profile(directory: str) -> None:
    os.makedirs(os.path.join(directory, "Network"), exist_ok=True)

    conn = sqlite3.connect(os.path.join(directory, "History"))
    conn.executescript("""
        CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER,
                           last_visit_time INTEGER);
        CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER,
                             transition INTEGER);
        CREATE TABLE downloads (id INTEGER PRIMARY KEY, target_path TEXT, tab_url TEXT,
                                total_bytes INTEGER, start_time INTEGER, state INTEGER);
    """)
    rows = [
        (1, "https://github.com/Pajt9whauht283as", "GitHub", 5, chrome_stamp(EPOCH)),
        (2, "https://unknowncheats.me/forum/index.php", "UC", 2,
         chrome_stamp(EPOCH - timedelta(days=3))),
        (3, "https://example.com/docs", "Docs", 1, chrome_stamp(EPOCH - timedelta(days=40))),
    ]
    conn.executemany("INSERT INTO urls VALUES (?,?,?,?,?)", rows)
    conn.execute("INSERT INTO downloads VALUES (1,?,?,?,?,0)",
                 ("C:\\Users\\me\\Downloads\\pack.zip", "https://example.com/pack.zip",
                  1024 * 1024, chrome_stamp(EPOCH - timedelta(hours=2))))
    conn.commit()
    conn.close()

    with open(os.path.join(directory, "Bookmarks"), "w", encoding="utf-8") as fh:
        json.dump({"roots": {"bookmark_bar": {"name": "Bookmarks bar", "type": "folder",
                                             "children": [
                                                 {"type": "url", "name": "GitHub",
                                                  "url": "https://github.com"},
                                                 {"type": "folder", "name": "tools",
                                                  "children": [
                                                      {"type": "url", "name": "hashcat",
                                                       "url": "https://hashcat.net"}]}]}}}, fh)

    web = sqlite3.connect(os.path.join(directory, "Web Data"))
    web.execute("CREATE TABLE autofill (name TEXT, value TEXT, count INTEGER)")
    web.executemany("INSERT INTO autofill VALUES (?,?,?)",
                    [("email", "a@b.c", 4), ("name", "Someone", 2)])
    web.commit()
    web.close()

    logins = sqlite3.connect(os.path.join(directory, "Login Data"))
    logins.execute("CREATE TABLE logins (origin_url TEXT, username_value TEXT)")
    logins.executemany("INSERT INTO logins VALUES (?,?)",
                       [("https://example.com", "user"), ("https://github.com", "dev")])
    logins.commit()
    logins.close()

    cookies = sqlite3.connect(os.path.join(directory, "Network", "Cookies"))
    cookies.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)")
    cookies.executemany("INSERT INTO cookies VALUES (?,?,?)",
                        [("example.com", "a", b"x"), ("example.com", "b", b"y"),
                         ("github.com", "c", b"z")])
    cookies.commit()
    cookies.close()


class TestProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "User Data", "Default")
        os.makedirs(self.dir)
        build_profile(self.dir)
        self.profiles = browsers.discover(root=os.path.join(self.tmp.name, "User Data"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery(self):
        self.assertEqual(len(self.profiles), 1)
        profile = self.profiles[0]
        self.assertTrue(profile.has("history"))
        self.assertTrue(profile.has("bookmarks"))
        self.assertTrue(profile.has("cookies"))

    def test_history(self):
        visits = browsers.history(self.profiles[0])
        self.assertEqual(len(visits), 3)
        self.assertEqual(visits[0].url, "https://github.com/Pajt9whauht283as")
        self.assertEqual(visits[0].when.date(), EPOCH.date())

    def test_history_query(self):
        visits = browsers.history(self.profiles[0], query="unknowncheats")
        self.assertEqual(len(visits), 1)
        self.assertIn("unknowncheats", visits[0].url)

    def test_history_since(self):
        since = EPOCH - timedelta(days=7)
        visits = browsers.history(self.profiles[0], since=since)
        self.assertEqual(len(visits), 2)

    def test_downloads(self):
        items = browsers.downloads(self.profiles[0])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].target.endswith("pack.zip"))
        self.assertEqual(items[0].total_bytes, 1024 * 1024)

    def test_bookmarks_walk(self):
        items = browsers.bookmarks(self.profiles[0])
        names = sorted(item.name for item in items)
        self.assertEqual(names, ["GitHub", "hashcat"])
        folders = {item.name: item.folder for item in items}
        self.assertIn("tools", folders["hashcat"])

    def test_summary(self):
        summary = browsers.summarize(self.profiles[0])
        self.assertEqual(summary.visits, 3)
        self.assertEqual(summary.downloads, 1)
        self.assertEqual(summary.bookmarks, 2)
        self.assertEqual(summary.autofill, 2)
        self.assertEqual(summary.logins, 2)
        self.assertEqual(summary.cookie_hosts, 2)
        self.assertTrue(summary.top_hosts)
        self.assertEqual(summary.first.date(), (EPOCH - timedelta(days=40)).date())

    def test_snapshot_does_not_touch_original(self):
        before = os.path.getmtime(self.profiles[0].files["history"])
        browsers.history(self.profiles[0])
        self.assertEqual(before, os.path.getmtime(self.profiles[0].files["history"]))


class TestTime(unittest.TestCase):
    def test_parse_relative(self):
        now = datetime.now(timezone.utc)
        parsed = browsers.parse_when("7d")
        self.assertLess(abs((now - parsed).total_seconds() - 7 * 86400), 60)

    def test_parse_date(self):
        parsed = browsers.parse_when("2026-11-01")
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.day, 1)

    def test_invalid(self):
        self.assertIsNone(browsers.parse_when("not a date"))

    def test_chrome_time_roundtrip(self):
        stamp = chrome_stamp(EPOCH)
        self.assertEqual(browsers.chrome_time(stamp).date(), EPOCH.date())


if __name__ == "__main__":
    unittest.main()

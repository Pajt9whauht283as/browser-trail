"""Browser profile discovery and local artifact readers (history, downloads, bookmarks)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

CHROME_EPOCH_OFFSET = 11644473600          # seconds between 1601-01-01 and 1970-01-01

CHROMIUM_BROWSERS = {
    "chrome": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data"),
    "edge": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"),
    "brave": os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "User Data"),
    "opera": os.path.join(os.environ.get("APPDATA", ""), "Opera Software", "Opera Stable"),
    "opera gx": os.path.join(os.environ.get("APPDATA", ""), "Opera Software", "Opera GX Stable"),
    "vivaldi": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Vivaldi", "User Data"),
    "chromium": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Chromium", "User Data"),
}

FIREFOX_ROOT = os.path.join(os.environ.get("APPDATA", ""), "Mozilla", "Firefox", "Profiles")


@dataclass
class Profile:
    browser: str
    name: str
    path: str
    kind: str                      # chromium | firefox
    files: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "%s / %s" % (self.browser, self.name)

    def has(self, artifact: str) -> bool:
        path = self.files.get(artifact)
        return bool(path and os.path.exists(path))


def _chromium_profiles(browser: str, root: str) -> list[Profile]:
    found: list[Profile] = []
    if not os.path.isdir(root):
        return found
    candidates = []
    default = os.path.join(root, "Default")
    if os.path.isdir(default):
        candidates.append(("Default", default))
    for name in sorted(os.listdir(root)):
        if name.startswith("Profile ") and os.path.isdir(os.path.join(root, name)):
            candidates.append((name, os.path.join(root, name)))
    for name, path in candidates:
        files = {
            "history": os.path.join(path, "History"),
            "downloads": os.path.join(path, "History"),
            "bookmarks": os.path.join(path, "Bookmarks"),
            "autofill": os.path.join(path, "Web Data"),
            "logins": os.path.join(path, "Login Data"),
            "cookies": os.path.join(path, "Network", "Cookies"),
        }
        found.append(Profile(browser=browser, name=name, path=path, kind="chromium", files=files))
    return found


def _firefox_profiles(root: str) -> list[Profile]:
    found: list[Profile] = []
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        places = os.path.join(path, "places.sqlite")
        if not os.path.exists(places):
            continue
        found.append(Profile(
            browser="firefox",
            name=name,
            path=path,
            kind="firefox",
            files={"history": places, "bookmarks": places},
        ))
    return found


def discover(root: str | None = None, browser: str | None = None) -> list[Profile]:
    profiles: list[Profile] = []
    if root:
        # an explicit path is treated as a User Data directory or a single profile
        if os.path.exists(os.path.join(root, "History")):
            profiles.append(Profile(browser=browser or "custom", name="Default", path=root,
                                    kind="chromium", files={
                                        "history": os.path.join(root, "History"),
                                        "downloads": os.path.join(root, "History"),
                                        "bookmarks": os.path.join(root, "Bookmarks"),
                                    }))
            return profiles
        profiles = _chromium_profiles(browser or "custom", root)
        if profiles:
            return profiles
        # last resort: the root holds install directories, e.g. one vendor folder
        for name, path in CHROMIUM_BROWSERS.items():
            if browser and browser != name:
                continue
            base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or ""
            candidate = os.path.join(root, os.path.relpath(path, base)) if base else ""
            if candidate and os.path.isdir(candidate):
                profiles.extend(_chromium_profiles(name, candidate))
        return profiles

    for name, path in CHROMIUM_BROWSERS.items():
        if browser and browser != name:
            continue
        profiles.extend(_chromium_profiles(name, path))
    if not browser or browser == "firefox":
        profiles.extend(_firefox_profiles(FIREFOX_ROOT))
    return profiles


# ------------------------------------------------------------------ time

def chrome_time(value: int | None) -> datetime | None:
    if not value:
        return None
    try:
        seconds = value / 1_000_000 - CHROME_EPOCH_OFFSET
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def firefox_time(value: int | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(value / 1_000_000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_when(text: str | None) -> datetime | None:
    """Accept 2026-11-20, 7d, 24h, 90m."""
    if not text:
        return None
    text = text.strip().lower()
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    try:
        if text.endswith("d"):
            return now - timedelta(days=float(text[:-1]))
        if text.endswith("h"):
            return now - timedelta(hours=float(text[:-1]))
        if text.endswith("m"):
            return now - timedelta(minutes=float(text[:-1]))
        if text.endswith("w"):
            return now - timedelta(weeks=float(text[:-1]))
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ------------------------------------------------------------------ sqlite

class SnapshotError(Exception):
    pass


def _copy_locked(source: str, target: str) -> None:
    """Copy a file another process holds open.

    Browsers keep their databases open without FILE_SHARE_READ, which makes a plain
    copy fail on Windows; opening the handle ourselves with full sharing works.
    """
    try:
        shutil.copy2(source, target)
        return
    except PermissionError:
        if os.name != "nt":
            raise

    import ctypes
    import msvcrt
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    SHARE_ALL = 0x00000007
    OPEN_EXISTING = 3
    INVALID = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.HANDLE]
    handle = kernel32.CreateFileW(source, GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, 0, None)
    if handle in (None, INVALID):
        raise SnapshotError("cannot open %s (error %d)"
                            % (source, ctypes.get_last_error()))
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError:
        kernel32.CloseHandle(handle)
        raise SnapshotError("cannot wrap handle for %s" % source)
    with os.fdopen(fd, "rb") as reader, open(target, "wb") as writer:
        shutil.copyfileobj(reader, writer, 1 << 20)


class Snapshot:
    """A copy of a locked database, opened read-only."""

    def __init__(self, path: str):
        self.source = path
        self.tmpdir = tempfile.mkdtemp(prefix="trail-")
        target = os.path.join(self.tmpdir, os.path.basename(path))
        self.failed = False
        try:
            _copy_locked(path, target)
        except (OSError, SnapshotError):
            # the browser holds the file with no sharing at all: degrade to an empty
            # snapshot instead of taking the whole report down
            self.failed = True
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = ""
            self.conn = sqlite3.connect(":memory:")
            self.conn.execute("CREATE TABLE if_missing (x)")
            return
        for suffix in ("-wal", "-shm"):
            sidecar = path + suffix
            if os.path.exists(sidecar):
                try:
                    _copy_locked(sidecar, target + suffix)
                except (OSError, SnapshotError):
                    pass
        self.conn = sqlite3.connect("file:%s?mode=ro" % target.replace("\\", "/"), uri=True)

    def rows(self, query: str, params=()) -> list[tuple]:
        try:
            return list(self.conn.execute(query, params))
        except sqlite3.Error:
            return []

    def close(self) -> None:
        try:
            self.conn.close()
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ------------------------------------------------------------------ artifacts

@dataclass
class Visit:
    when: datetime | None
    url: str
    title: str
    browser: str
    profile: str
    kind: str = "visit"


def history(profile: Profile, since=None, until=None, query=None, limit=1000) -> list[Visit]:
    if not profile.has("history"):
        return []
    out: list[Visit] = []
    with Snapshot(profile.files["history"]) as db:
        if profile.kind == "chromium":
            rows = db.rows(
                "SELECT url, title, visit_count, last_visit_time FROM urls "
                "WHERE last_visit_time > 0 ORDER BY last_visit_time DESC")
            for url, title, count, stamp in rows:
                when = chrome_time(stamp)
                if not _keep(when, since, until):
                    continue
                if query and query.lower() not in (url or "").lower() \
                        and query.lower() not in (title or "").lower():
                    continue
                out.append(Visit(when, url or "", title or "", profile.browser, profile.name))
        else:
            rows = db.rows(
                "SELECT url, title, last_visit_date FROM moz_places "
                "WHERE last_visit_date IS NOT NULL ORDER BY last_visit_date DESC")
            for url, title, stamp in rows:
                when = firefox_time(stamp)
                if not _keep(when, since, until):
                    continue
                if query and query.lower() not in (url or "").lower() \
                        and query.lower() not in (title or "").lower():
                    continue
                out.append(Visit(when, url or "", title or "", profile.browser, profile.name))
    out.sort(key=lambda item: item.when or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[:limit]


@dataclass
class Download:
    when: datetime | None
    target: str
    source: str
    total_bytes: int
    browser: str
    profile: str


def downloads(profile: Profile, since=None, until=None, query=None, limit=1000) -> list[Download]:
    if profile.kind != "chromium" or not profile.has("downloads"):
        return []
    out: list[Download] = []
    with Snapshot(profile.files["downloads"]) as db:
        rows = db.rows(
            "SELECT target_path, tab_url, total_bytes, start_time FROM downloads "
            "ORDER BY start_time DESC")
        for target, source, size, stamp in rows:
            when = chrome_time(stamp)
            if not _keep(when, since, until):
                continue
            if query and query.lower() not in (target or "").lower() \
                    and query.lower() not in (source or "").lower():
                continue
            out.append(Download(when, target or "", source or "", size or 0,
                                profile.browser, profile.name))
    return out[:limit]


@dataclass
class Bookmark:
    name: str
    url: str
    folder: str
    browser: str
    profile: str


def bookmarks(profile: Profile) -> list[Bookmark]:
    out: list[Bookmark] = []
    if profile.kind == "chromium":
        path = profile.files.get("bookmarks", "")
        if not os.path.exists(path):
            return out
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return out

        def walk(node, trail):
            if isinstance(node, dict):
                name = node.get("name", "")
                kind = node.get("type")
                if kind == "url" and node.get("url"):
                    out.append(Bookmark(name, node["url"], "/".join(trail) or "root",
                                        profile.browser, profile.name))
                for child in node.get("children", []) or []:
                    walk(child, trail + ([name] if name and kind != "url" else []))

        for root_name, root in (data.get("roots") or {}).items():
            walk(root, [root_name])
        return out

    if not profile.has("bookmarks"):
        return out
    with Snapshot(profile.files["bookmarks"]) as db:
        rows = db.rows(
            "SELECT b.title, p.url, b.parent FROM moz_bookmarks b "
            "JOIN moz_places p ON b.fk = p.id WHERE b.type = 1")
        parents = dict(db.rows("SELECT id, title FROM moz_bookmarks"))
        for title, url, parent in rows:
            out.append(Bookmark(title or "", url or "", parents.get(parent) or "root",
                                profile.browser, profile.name))
    return out


def _keep(when: datetime | None, since, until) -> bool:
    if when is None:
        return since is None and until is None
    if since and when < since:
        return False
    if until and when > until:
        return False
    return True


@dataclass
class Summary:
    profile: Profile
    visits: int = 0
    downloads: int = 0
    bookmarks: int = 0
    autofill: int = 0
    logins: int = 0
    cookie_hosts: int = 0
    first: datetime | None = None
    last: datetime | None = None
    top_hosts: list[tuple[str, int]] = field(default_factory=list)


def _count(profile: Profile, artifact: str, query: str) -> int:
    path = profile.files.get(artifact, "")
    if not path or not os.path.exists(path):
        return 0
    with Snapshot(path) as db:
        rows = db.rows(query)
    return rows[0][0] if rows else 0


def summarize(profile: Profile) -> Summary:
    summary = Summary(profile=profile)
    visits = history(profile, limit=100000)
    summary.visits = len(visits)
    if visits:
        dated = [visit.when for visit in visits if visit.when]
        if dated:
            summary.first, summary.last = min(dated), max(dated)
    summary.downloads = len(downloads(profile, limit=100000))
    summary.bookmarks = len(bookmarks(profile))
    if profile.kind == "chromium":
        summary.autofill = _count(profile, "autofill", "SELECT COUNT(*) FROM autofill")
        summary.logins = _count(profile, "logins", "SELECT COUNT(*) FROM logins")
        path = profile.files.get("cookies", "")
        if os.path.exists(path):
            with Snapshot(path) as db:
                rows = db.rows("SELECT COUNT(DISTINCT host_key) FROM cookies")
            summary.cookie_hosts = rows[0][0] if rows else 0

    hosts: dict[str, int] = {}
    for visit in visits:
        host = _host(visit.url)
        if host:
            hosts[host] = hosts.get(host, 0) + 1
    summary.top_hosts = sorted(hosts.items(), key=lambda pair: -pair[1])[:10]
    return summary


def _host(url: str) -> str:
    without_scheme = url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].split("?", 1)[0].lower()

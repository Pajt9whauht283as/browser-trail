"""browser-trail: local browser artifact reader."""

from .browsers import (Bookmark, Download, Profile, Summary, Visit, bookmarks, chrome_time,
                       discover, downloads, firefox_time, history, parse_when, summarize)

__version__ = "1.0.0"
__all__ = ["Profile", "Visit", "Download", "Bookmark", "Summary", "discover", "history",
           "downloads", "bookmarks", "summarize", "chrome_time", "firefox_time", "parse_when",
           "__version__"]

#!/usr/bin/env python3
"""browser-trail - entry point.

    python main.py profiles
    python main.py summary
    python main.py history --since 7d --query github
    python main.py downloads --csv
"""

import sys

from trail.cli import main

if __name__ == "__main__":
    sys.exit(main())

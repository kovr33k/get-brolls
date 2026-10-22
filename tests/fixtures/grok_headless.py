#!/usr/bin/env python3
"""Retired synthetic peer.

This file is not a native media transport. The unverified streaming-json
prototype is archived outside the linted tree and production code does not
launch it.
"""

from __future__ import annotations

import sys


def main():
    sys.stderr.write("This synthetic peer is not a native media transport.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

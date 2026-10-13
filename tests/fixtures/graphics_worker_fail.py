#!/usr/bin/env python3
"""Failing graphics worker used to keep a version in the failed state."""

import sys

sys.stderr.write("intentional graphics worker failure\n")
raise SystemExit(2)

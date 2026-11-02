#!/usr/bin/env python3
"""Claude Code statusline hook: stores `rate_limits` from stdin JSON into data/usage.json, prints a short line.
Optional argv: a command to pipe the same stdin into (wrap an existing statusline); its output is printed instead."""
import json
import subprocess
import sys
from pathlib import Path

USAGE = Path(__file__).resolve().parent.parent / "data" / "usage.json"


def capture(raw):
    try:
        rl = json.loads(raw).get("rate_limits")
    except (ValueError, AttributeError):
        return
    if not rl:
        return
    try:
        cur = json.loads(USAGE.read_text())
    except (OSError, ValueError):
        cur = {}
    import time
    cur["rate_limits"] = rl
    cur["rate_limits_ts"] = time.time()
    try:
        USAGE.parent.mkdir(exist_ok=True)
        tmp = USAGE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur))
        tmp.replace(USAGE)
    except OSError:
        pass


def short(raw):
    try:
        rl = json.loads(raw).get("rate_limits") or {}
        f, s = rl.get("five_hour", {}), rl.get("seven_day", {})
        return f"5h {f.get('used_percentage', '?')}% | 7d {s.get('used_percentage', '?')}%"
    except (ValueError, AttributeError):
        return "claude"


if __name__ == "__main__":
    raw = sys.stdin.read()
    capture(raw)
    if len(sys.argv) > 1:
        r = subprocess.run(sys.argv[1:], input=raw, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
    else:
        print(short(raw))

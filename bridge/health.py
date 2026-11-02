"""launchd job health: last exit code + log mtime vs schedule. Stdlib only; never raises."""
import datetime
import os
import plistlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRACE = datetime.timedelta(hours=2)
EXIT_RE = re.compile(r"last exit code = (-?\d+)")
STATE_RE = re.compile(r"^\s*state = (\w[\w ]*)$", re.M)


def parse_exit(text):
    """int exit code, or None when absent / '(never exited)'."""
    m = EXIT_RE.search(text or "")
    return int(m.group(1)) if m else None


def parse_state(text):
    m = STATE_RE.search(text or "")
    return m.group(1).strip() if m else None


def last_slot(sched, now):
    """Most recent scheduled datetime <= now for a StartCalendarInterval dict (daily/hourly only)."""
    h, m = sched.get("Hour"), sched.get("Minute", 0)
    if h is None:
        return None
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return slot if slot <= now else slot - datetime.timedelta(days=1)


def judge(exit_code, state, keepalive, sched, last_run, now):
    """-> (ok, detail). last_run is a naive local datetime or None."""
    if keepalive:
        return (state == "running", "running" if state == "running" else "not running")
    if exit_code:
        return False, f"exit {exit_code}"
    if isinstance(sched, list):
        sched = sched[0] if sched else None
    if sched:
        slot = last_slot(sched, now - GRACE)
        if slot and (last_run is None or last_run < slot):
            return False, f"missed {slot:%H:%M} run"
    return True, "ok"


def _last_run(label):
    stem = label.replace("com.filip.", "").replace("aos-bridge", "bridge")
    times = [p.stat().st_mtime for p in (ROOT / "data/logs").glob(stem + "*.log")]
    return datetime.datetime.fromtimestamp(max(times)) if times else None


def _print(label):
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                       capture_output=True, text=True, timeout=5)
    return r.returncode, r.stdout


def health(now=None):
    now = now or datetime.datetime.now()
    out = []
    for p in sorted((ROOT / "launchd").glob("com.filip.aos-*.plist")):
        label = p.stem
        job = label.replace("com.filip.", "")
        last = None
        try:
            plist = plistlib.loads(p.read_bytes())
            last = _last_run(label)
            rc, text = _print(label)
            if rc != 0:
                ok, detail = False, "not loaded"
            else:
                ok, detail = judge(parse_exit(text), parse_state(text), bool(plist.get("KeepAlive")),
                                   plist.get("StartCalendarInterval"), last, now)
        except Exception as e:  # never raise
            ok, detail = False, type(e).__name__
        out.append({"job": job, "last_run": last.isoformat(timespec="seconds") if last else None,
                    "ok": ok, "detail": detail})
    return out

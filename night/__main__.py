"""python3 -m night run [--offline] [--teacher fake|claude] [--force]"""
import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m night")
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--offline", action="store_true", help="no network: fake teacher, mock Jev")
    ap.add_argument("--teacher", choices=["fake", "claude"])
    ap.add_argument("--force", action="store_true", help="rerun even if tonight already ran")
    a = ap.parse_args(argv)
    offline = a.offline or os.environ.get("AOS_OFFLINE") == "1"
    if offline:
        os.environ["AOS_OFFLINE"] = "1"
    teacher_name = a.teacher or ("fake" if offline else "claude")
    if offline and teacher_name == "claude":
        ap.error("--teacher claude needs the network; drop --offline")
    from night import school
    teacher = school.fake_teacher if teacher_name == "fake" else school.claude_teacher(school.paths()["vault"])
    s = school.run(teacher=teacher, force=a.force)
    if s.get("skipped"):
        print(s["message"])
        return 0
    g = s["gate"] or {}
    print(f"night school {s['day']}: {s['learned']}/{s['cases']} labelled {json.dumps(s['tier_mix'])}")
    if s["teacher_error"]:
        print(f"teacher: {s['teacher_error']}")
    print(f"proposal: {s['proposal']}")
    if g:
        print(f"gate: {g['decision']} - {g['reason']}")
    print(f"pending: {len(s['pending'])} ({', '.join(x['id'] for x in s['pending']) or 'none'})")
    print(f"jev: {s['jev_calls']} calls, ${s['jev_usd']:.4f}")
    print(f"note: {s['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

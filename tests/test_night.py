import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("AOS_OFFLINE", "1")

from bridge.log import Log  # noqa: E402
from night import api, school  # noqa: E402
from router.rulebook import Rulebook  # noqa: E402

NOW = datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)
SEED = Rulebook.load(Path(__file__).resolve().parent.parent / "rulebook.seed.json")
WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa".split()


def text_for(i, kind="T2"):
    w = f"{WORDS[i % 16]} {WORDS[(i // 16) % 16]} {i}"
    return {"T1": f"show my priorities {w}", "T3": f"draft a long report on {w}", "T2": f"what is {w}"}[kind]


class Env:
    """Temp DB + vault, wired through AOS_DB / AOS_VAULT."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / "data" / "requests.db"
        self.vault = root / "vault"
        self.patch = mock.patch.dict(os.environ, {"AOS_DB": str(self.db), "AOS_VAULT": str(self.vault)})
        self.patch.start()
        self.log = Log(self.db)
        self.cfg = {"jev_threshold": 0.9, "vault_path": str(self.vault)}
        self.p = school.paths(self.cfg)

    def add(self, text, age_h=1.0, **kw):
        rid = self.log.insert(text=text, mode="auto", final_tier=kw.pop("final_tier", "T2"), **kw)
        with closing(sqlite3.connect(str(self.db))) as db, db:
            db.execute("UPDATE requests SET ts = ? WHERE id = ?", ((NOW - timedelta(hours=age_h)).isoformat(), rid))
        return rid

    def close(self):
        self.patch.stop()
        self.tmp.cleanup()


class FakeJev:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def decide(self, text):
        self.calls += 1
        return self.fn(text)


def factory(base_fn, cand_fn, made=None):
    def make(path):
        j = FakeJev(cand_fn if Rulebook.load(path).notes else base_fn)
        if made is not None:
            made.append(j)
        return j
    return make


def labels(n):
    out = []
    for i in range(n):
        kind = ("T1", "T2", "T3")[i % 3]
        out.append(dict(id=f"r{i}", ts=f"2026-10-{1 + i // 10:02d}T{i % 10:02d}:00", text=text_for(i, kind), tier=kind))
    return out


TRUTH = {}
for _l in labels(400):
    TRUTH[_l["text"]] = _l["tier"]
CAND = SEED.with_note("Generic test note.")


def right(text):
    return TRUTH[text], 0.95, 0.0001


class TestExport(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def test_selection_cap_determinism(self):
        e = self.e
        for i in range(30):
            e.add(text_for(i), feedback="down", jev_choice="T2", jev_p=0.95)
        for i in range(30, 50):
            e.add(text_for(i), jev_choice="T2", jev_p=0.5)  # unsure
        for i in range(50, 70):
            e.add(text_for(i), jev_choice="T2", jev_p=0.97)  # confident
        parent = e.add("escalated one", jev_choice="T2", jev_p=0.95)
        e.add("escalated one", parent_id=parent, final_tier="T3")
        e.add("old unsure", age_h=30, jev_p=None)
        cases = school.export(e.db, 0.9, "2026-11-01", NOW)
        self.assertEqual(len(cases), 40)
        texts = [c["text"] for c in cases]
        self.assertNotIn("old unsure", texts)
        self.assertEqual(texts.count("escalated one"), 1)  # parent kept, the rerun child is not a case
        self.assertEqual(sum(c["feedback"] == "down" for c in cases), 30)
        self.assertEqual(sum(c["jev_p"] == 0.97 for c in cases), 2)  # ceil(10% of 20) confident
        self.assertEqual(cases, school.export(e.db, 0.9, "2026-11-01", NOW))

    def test_small_day_takes_all_flagged(self):
        e = self.e
        e.add("a", jev_p=None)
        e.add("b", jev_p=0.3)
        e.add("c", jev_p=0.99)
        cases = school.export(e.db, 0.9, "2026-11-01", NOW)
        self.assertEqual(sorted(c["text"] for c in cases), ["a", "b", "c"])


class TestParsing(unittest.TestCase):
    def test_labels_bad_lines_dropped(self):
        raw = "\n".join([
            '{"id": "c1", "tier": "T1", "reason": "lookup of saved data"}',
            '{"id": "c2", "tier": "T9", "reason": "bad tier"}',
            '{"id": "c3", "tier": "T2", "reason": "' + "word " * 16 + '"}',
            'not json at all',
            '{"id": "c99", "tier": "T2", "reason": "unknown id"}',
            '{"id": "c4", "tier": "T3"}',
            '{"id": "c1", "tier": "T3", "reason": "duplicate id"}',
            '```',
            '{"id": "c5", "tier": "T3", "reason": "drafting work"}',
        ])
        got = school.parse_labels(raw, {"c1", "c2", "c3", "c4", "c5"})
        self.assertEqual(got, {"c1": ("T1", "lookup of saved data"), "c5": ("T3", "drafting work")})

    def test_leak_guard(self):
        g = school.grams("please summarise the quarterly budget review for the board today")
        self.assertIsNotNone(school.leak("Mail filip@example.com items go to T1", g))
        self.assertIsNotNone(school.leak("See https://x.y for T3 cases", g))
        self.assertIsNotNone(school.leak("Request deadbeef01 goes to T2", g))
        self.assertIsNotNone(school.leak("Anything like summarise the quarterly budget review for the board is T3", g))
        self.assertIsNone(school.leak("Summaries of long documents go to T3.", g))

    def test_parse_proposal(self):
        self.assertEqual(school.parse_proposal('x {"edit":"note","text":"Short note."} y', SEED),
                         ("note", None, "Short note."))
        self.assertEqual(school.parse_proposal('{"edit":"criterion","option":"T2","text":"New."}', SEED)[1], "T2")
        self.assertIsNone(school.parse_proposal('{"edit":"criterion","option":"T7","text":"New."}', SEED))
        self.assertIsNone(school.parse_proposal('{"edit":"note","text":"' + "x" * 301 + '"}', SEED))


class TestGate(unittest.TestCase):
    def gate(self, n, base, cand, made=None):
        with tempfile.TemporaryDirectory() as d:
            return school.run_gate(labels(n), SEED, CAND, factory(base, cand, made), 0.9, "2026-11-01", d)

    def test_pass(self):
        g = self.gate(30, right, right)
        self.assertEqual(g["decision"], "pass", g["reason"])
        self.assertEqual(len(g["splits"]), 3)
        self.assertTrue(all(s["n"] == 10 for s in g["splits"]))

    def test_one_sure_miss_fails(self):
        def cand(text):
            return ("T3", 0.99, 0.0) if TRUTH[text] == "T1" else right(text)
        g = self.gate(30, right, cand)
        self.assertEqual(g["decision"], "fail")
        self.assertIn("misses", g["reason"])

    def test_agreement_drop_fails(self):
        def cand(text):  # unsure (no miss) but wrong more often
            return ("T2", 0.5, 0.0) if TRUTH[text] == "T1" else right(text)
        g = self.gate(30, right, cand)
        self.assertEqual(g["decision"], "fail")
        self.assertIn("agreement dropped", g["reason"])

    def test_not_enough_data(self):
        made = []
        g = self.gate(14, right, right, made)
        self.assertEqual(g["decision"], "not_enough_data")
        self.assertIn("not enough data yet", g["reason"])
        self.assertEqual(made, [])

    def test_cost_cap_skips(self):
        made = []
        with mock.patch.object(school, "MAX_CALLS", 10):
            g = self.gate(30, right, right, made)
        self.assertEqual(g["decision"], "skipped_cost")
        self.assertEqual(made, [])
        with mock.patch.object(school, "MAX_USD", 1e-9):
            self.assertEqual(self.gate(30, right, right)["decision"], "skipped_cost")

    def test_window_keeps_estimate_under_cap(self):
        g = self.gate(400, right, right)
        self.assertEqual(g["decision"], "pass")
        self.assertLessEqual(g["calls"], school.MAX_CALLS)


class TestShortcuts(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def test_detection(self):
        e = self.e
        for h in (1, 20, 100):
            e.add("Show my priorities?", age_h=h, provider="tier1", model="priorities", final_tier="T1")
        for h in (1, 2, 3):
            e.add("weather in Paris", age_h=h, final_tier="T2", feedback="up")
        for h in (1, 2):
            e.add("two times only", age_h=h, provider="tier1", model="usage", final_tier="T1")
        for h in (1, 2, 400):
            e.add("too old ones", age_h=h, provider="tier1", model="usage", final_tier="T1")
        for h in (1, 2, 3):
            rid = e.add("project status", age_h=h, final_tier="T2")
            e.log.set_night_label(rid, "T1")
        got = {s["example"]: s for s in school.find_shortcuts(e.db, NOW)}
        self.assertEqual(set(got), {"show my priorities", "project status"})
        self.assertEqual(got["show my priorities"]["lookup"], "priorities")
        self.assertIsNone(got["project status"]["lookup"])
        import re
        self.assertTrue(re.match(got["show my priorities"]["pattern"], "  show my priorities?? "))


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def test_run_note_approve(self):
        e = self.e
        for i in range(24):
            e.add(text_for(i, ("T1", "T2", "T3")[i % 3]), jev_choice="T2", jev_p=0.6)
        for h in (1, 2, 3):
            e.add("any new emails", age_h=h, provider="tier1", model="inbox", final_tier="T1", jev_p=0.95)

        def jev(text):
            low = text.lower()
            return ("T1" if "priorities" in low or "emails" in low else "T3" if "draft" in low else "T2"), 0.95, 0.0001
        s = school.run(self.e.cfg, teacher=school.fake_teacher, jev_factory=factory(jev, jev), now=NOW)
        self.assertEqual(s["learned"], s["cases"])
        self.assertEqual(s["gate"]["decision"], "pass", s["gate"]["reason"])
        kinds = sorted(x["id"][:2] for x in s["pending"])
        self.assertEqual(kinds, ["rb", "sc"])
        self.assertEqual(len(e.p["labels"].read_text().splitlines()), s["learned"])
        with closing(sqlite3.connect(str(e.db))) as db:
            n = db.execute("SELECT COUNT(*) FROM requests WHERE night_label IS NOT NULL").fetchone()[0]
        self.assertEqual(n, s["learned"])
        note = (e.vault / "outputs" / "night-school" / f"{s['day']}.md").read_text()
        self.assertTrue(note.startswith("---\ntype: night-school\n"))
        for want in ("## Learned", "Gate: **pass**", "## Needs approval", "Jev tonight:"):
            self.assertIn(want, note)
        for x in s["pending"]:
            self.assertIn(x["id"], note)

        self.assertTrue(school.run(self.e.cfg, teacher=school.fake_teacher, now=NOW)["skipped"])  # once a night

        st = api.status(e.cfg)
        self.assertEqual(st["learned"], s["learned"])
        self.assertEqual({x["id"] for x in st["pending"]}, {x["id"] for x in s["pending"]})

        rb_id = next(x["id"] for x in s["pending"] if x["id"].startswith("rb"))
        sc_id = next(x["id"] for x in s["pending"] if x["id"].startswith("sc"))
        before = e.p["rulebook"].read_text()
        r = api.approve(e.cfg, rb_id)
        self.assertTrue(r["ok"], r["message"])
        backups = list(e.p["night"].glob("rulebook-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before)
        self.assertIn("even when short", " ".join(Rulebook.load(e.p["rulebook"]).notes))
        self.assertFalse(api.approve(e.cfg, rb_id)["ok"])  # no longer pending

        self.assertTrue(api.approve(e.cfg, sc_id)["ok"])
        sc = json.loads(e.p["shortcuts"].read_text())
        self.assertEqual(sc[0]["lookup"], "inbox")
        self.assertEqual(api.status(e.cfg)["pending"], [])

    def test_approve_unknown_and_stale(self):
        e = self.e
        self.assertFalse(api.approve(e.cfg, "nope")["ok"])
        e.p["rulebook"].parent.mkdir(parents=True, exist_ok=True)
        SEED.save(e.p["rulebook"])
        school.write_json(e.p["proposals"], [dict(id="rb-x", kind="rulebook", summary="s", status="pending",
                                                  created="", payload=dict(base_hash="000", rulebook=CAND.to_dict()))])
        r = api.approve(e.cfg, "rb-x")
        self.assertFalse(r["ok"])
        self.assertIn("changed", r["message"])

    def test_teacher_error_and_leak(self):
        e = self.e
        for i in range(5):
            e.add(text_for(i, "T3"), jev_choice="T2", jev_p=0.4)

        def broken(prompt):
            raise school.TeacherError("teacher exited 1")
        s = school.run(e.cfg, teacher=broken, jev_factory=factory(right, right), now=NOW)
        self.assertEqual(s["learned"], 0)
        self.assertEqual(s["teacher_error"], "teacher exited 1")

        def leaky(prompt):
            if '"edit"' in prompt:
                return '{"edit":"note","text":"Requests like draft a long report on alpha alpha go to T3."}'
            return school.fake_teacher(prompt)
        s = school.run(e.cfg, teacher=leaky, jev_factory=factory(right, right), now=NOW, force=True)
        self.assertIn("leak guard", s["proposal"])
        self.assertIsNone(s["gate"])
        self.assertEqual(s["pending"], [])


if __name__ == "__main__":
    unittest.main()

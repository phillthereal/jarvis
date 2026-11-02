import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bridge import widgets

NOTION = {"results": [
    {"url": "https://notion.so/a", "properties": {
        "Name": {"type": "title", "title": [{"plain_text": "Reply to "}, {"plain_text": "Bob"}]},
        "Status": {"type": "status", "status": {"name": "Not started"}},
        "Follow-up": {"type": "date", "date": {"start": "2020-01-02"}}}},
    {"url": "https://notion.so/b", "properties": {
        "Task": {"type": "title", "title": [{"plain_text": "Old one"}]},
        "Done": {"type": "checkbox", "checkbox": True}}},
    {"url": "https://notion.so/c", "properties": {
        "Task": {"type": "title", "title": [{"plain_text": "Closed via select"}]},
        "State": {"type": "select", "select": {"name": "Done"}}}},
    {"url": "https://notion.so/d", "properties": {
        "Task": {"type": "title", "title": [{"plain_text": "Future"}]},
        "Due": {"type": "date", "date": {"start": "2999-01-01T09:00:00Z"}}}},
]}


class InboxTests(unittest.TestCase):
    def test_parse_notion_generic_properties(self):
        items = widgets.parse_notion(NOTION)
        self.assertEqual([i["done"] for i in items], [False, True, True, False])
        self.assertEqual(items[0]["title"], "Reply to Bob")
        self.assertEqual(items[0]["date"], "2020-01-02")
        self.assertEqual(items[3]["date"], "2999-01-01")

    def test_unconfigured(self):
        self.assertEqual(widgets.inbox({}), {"configured": False})
        self.assertEqual(widgets.inbox({"NOTION_TOKEN": "x"}), {"configured": False})

    def test_error_is_secret_free(self):
        with mock.patch.object(widgets, "_notion_query", side_effect=OSError("secret_TOKEN123 failed")):
            r = widgets.inbox({"NOTION_TOKEN": "secret_TOKEN123", "NOTION_EMAIL_TASKS_DB": "db"})
        self.assertTrue(r["configured"])
        self.assertNotIn("secret", json.dumps(r))

    def test_inbox_open_items(self):
        with mock.patch.object(widgets, "_notion_query", return_value=NOTION):
            r = widgets.inbox({"NOTION_TOKEN": "t", "NOTION_EMAIL_TASKS_DB": "d"})
        self.assertEqual(r["open"], 2)


class CalendarPlanIntelTests(unittest.TestCase):
    def test_parse_jxa(self):
        ev = widgets.parse_jxa("2026-11-01T15:30:00.000Z\tLunch\nbad line\n2026-11-01T08:00:00.000Z\tStandup\n")
        self.assertEqual([e["title"] for e in ev], sorted([e["title"] for e in ev], key=lambda t: t != "Standup" and 1 or 0))
        self.assertEqual(len(ev), 2)
        self.assertRegex(ev[0]["start"], r"^\d\d:\d\d$")

    def setUp(self):
        widgets._CAL["v"] = None

    def test_calendar_permission_and_timeout(self):
        def helper(text):  # fake `open --stdout <file> JarvisCalendar.app`
            return lambda cmd, **kw: Path(cmd[cmd.index("--stdout") + 1]).write_text(text)
        with mock.patch.object(widgets, "CAL_APP", Path(__file__)), \
                mock.patch("subprocess.run", side_effect=helper("2026-11-01T09:30:00Z\tStandup\n")):
            self.assertEqual(widgets._calendar_fetch()["events"][0]["title"], "Standup")
        with mock.patch.object(widgets, "CAL_APP", Path(__file__)), \
                mock.patch("subprocess.run", side_effect=helper("ERR no-permission status=0\n")):
            self.assertEqual(widgets.calendar_today(), {"calendar": "no-permission"})
        self.assertEqual(widgets.calendar_today(), {"calendar": "no-permission"})  # cached
        widgets._CAL["v"] = None
        import subprocess
        with mock.patch.object(widgets, "CAL_APP", Path(__file__)), \
                mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("open", 8)):
            self.assertEqual(widgets.calendar_today(), {"calendar": "unavailable"})

    def test_directives_first_three(self):
        t = "# D\n- [ ] one\n- [x] two\nnote\n- [ ] three\n- [ ] four\n"
        d = widgets.parse_directives(t)
        self.assertEqual([x["text"] for x in d], ["one", "two", "three"])
        self.assertTrue(d[1]["done"])

    def test_plan_without_vault_or_notion(self):
        with mock.patch.object(widgets, "calendar_today", return_value={"calendar": "unavailable"}):
            r = widgets.plan({"vault_path": "/nonexistent-vault"}, {})
        self.assertEqual(r["directives"], [])
        self.assertEqual(r["follow_ups"], [])

    def test_plan_follow_ups_due(self):
        with mock.patch.object(widgets, "calendar_today", return_value={"events": []}), \
             mock.patch.object(widgets, "_notion_query", return_value=NOTION):
            r = widgets.plan({"vault_path": "/nonexistent-vault"}, {"NOTION_TOKEN": "t", "NOTION_EMAIL_TASKS_DB": "d"})
        self.assertEqual([f["title"] for f in r["follow_ups"]], ["Reply to Bob"])

    def test_intel(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"vault_path": d}
            self.assertEqual(widgets.intel(cfg), {"empty": True})
            p = Path(d) / "outputs" / "intel"
            p.mkdir(parents=True)
            (p / "2026-10-31.md").write_text("- old\n")
            (p / "2026-11-01.md").write_text("# T\n## Headlines\n- [b](https://x/1) — Src\n- c\nprose\n- d\n- e\n- f\n- g\n")
            r = widgets.intel(cfg)
            self.assertEqual(r["date"], "2026-11-01")
            self.assertEqual(r["headlines"][:2], [{"title": "b", "url": "https://x/1", "source": "Src"},
                                                  {"title": "c", "url": "", "source": ""}])
            self.assertEqual([h["title"] for h in r["headlines"]], ["b", "c", "d", "e", "f"])


if __name__ == "__main__":
    unittest.main()


class WeeklyTests(unittest.TestCase):
    def test_counts_from_temp_vault_and_jobs(self):
        import os
        import time
        with tempfile.TemporaryDirectory() as t:
            v = Path(t)
            for sub in ("briefs", "plans", "intel", "night-school"):
                (v / "outputs" / sub).mkdir(parents=True)
            (v / "outputs" / "plans" / "new.md").write_text("x")
            (v / "outputs" / "plans" / "README.md").write_text("x")
            old = v / "outputs" / "intel" / "old.md"
            old.write_text("x")
            os.utime(old, (time.time() - 9 * 86400,) * 2)
            (v / "outputs" / "intel" / "fresh.md").write_text("x")
            today = datetime.date.today()
            for d, n in ((0, 3), (3, 4), (20, 99)):
                day = (today - datetime.timedelta(days=d)).isoformat()
                (v / "outputs" / "night-school" / f"{day}.md").write_text(f"## Learned\n- {n} of 9 exported cases labelled (tier mix: T1 1).\n")
            rows = [{"name": "plan-today", "state": "done", "started": time.time()},
                    {"name": "plan-today", "state": "done", "started": time.time() - 100},
                    {"name": "vault-lint", "state": "error", "started": time.time()},
                    {"name": "vault-lint", "state": "done", "started": time.time() - 30 * 86400}]
            r = widgets.weekly_counts(v, {"T1": 2, "T4": 3}, rows)
        self.assertEqual(r["asked_by_tier"], {"T1": 2, "T2": 0, "T3": 0, "T4": 3, "T5": 0})
        self.assertEqual((r["asked_total"], r["briefs"], r["night_learned"]), (5, 2, 7))
        self.assertEqual(r["skills_run"], [{"name": "plan-today", "count": 2}])

    def test_log_asked_by_tier(self):
        from bridge.log import Log
        with tempfile.TemporaryDirectory() as t:
            log = Log(Path(t) / "r.db")
            for tier in ("T1", "T2", "T2", None):
                log.insert(text="q", final_tier=tier)
            self.assertEqual(log.asked_by_tier(7), {"T1": 1, "T2": 2})


class SystemTests(unittest.TestCase):
    def test_shape_never_leaks_key_values(self):
        cfg = {"tier4_providers": [{"name": "groq", "key_env": "GROQ_API_KEY"}, {"name": "openrouter", "key_env": "OR"}]}
        r = widgets.system_status(cfg, {"GROQ_API_KEY": "sekrit"}, [{"job": "aos-x", "ok": True}], True, 3, None)
        self.assertEqual(r, {"ollama": {"up": True, "models": 3}, "last_backup": None, "jobs": [{"job": "aos-x", "ok": True}],
                             "keys": {"groq": True, "openrouter": False}})
        self.assertNotIn("sekrit", json.dumps(r))

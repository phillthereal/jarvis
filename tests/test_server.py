import http.client
import json
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from bridge import jobs, server
from bridge.config import load_config


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.vault = t / "vault"
        (cls.vault / "wiki").mkdir(parents=True)
        (cls.vault / "outputs" / "intel").mkdir(parents=True)
        (cls.vault / "wiki" / "note.md").write_text("Alice said the launch is Friday\n")
        (cls.vault / "outputs" / "intel" / "2026-11-01.md").write_text("# Intel\n- Headline one\n- Headline two\n")
        cfg = dict(load_config(), vault_path=str(cls.vault))
        app = server.build_app(cfg, {}, offline=True, data_dir=t / "data")
        cls.srv = server.make_server(0, app)
        cls.app, cls.port = app, cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.cookie = cls.req("GET", "/")[1].get("Set-Cookie")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    @classmethod
    def req(cls, method, path, body=None, headers=None, raw=None, auth=False):
        h = {"Host": f"127.0.0.1:{cls.port}", **(headers or {})}
        if auth:
            h["Cookie"] = cls.cookie.split(";")[0]
        if body is not None:
            raw = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        c.putrequest(method, path, skip_host=True)
        for k, v in h.items():
            c.putheader(k, v)
        c.putheader("Content-Length", str(len(raw or b"")))
        c.endheaders(raw or b"")
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        try:
            data = json.loads(data)
        except ValueError:
            pass
        return r.status, hdrs, data

    def api(self, method, path, body=None, **kw):
        s, h, d = self.req(method, path, body, auth=True, **kw)
        return s, d

    # ---- static + auth
    def test_static_and_cookie(self):
        s, h, d = self.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("SameSite=Strict", h["Set-Cookie"])
        self.assertEqual(h["X-Frame-Options"], "DENY")  # no clickjacking
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual(self.req("GET", "/app.js")[1]["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(self.req("GET", "/style.css")[1]["Content-Type"], "text/css; charset=utf-8")

    def test_static_allow_list(self):
        for p in ("/../config.json", "/config.json", "/web/app.js", "/%2e%2e/config.json"):
            self.assertEqual(self.req("GET", p)[0], 404, p)

    def test_401_without_or_with_wrong_cookie(self):
        self.assertEqual(self.req("GET", "/api/status")[0], 401)
        self.assertEqual(self.req("GET", "/api/status", headers={"Cookie": "aos=nope"})[0], 401)

    def test_bad_host_origin_content_type_size(self):
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.com"}, auth=True)[0], 403)
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.com"})[0], 403)
        self.assertEqual(self.req("GET", "/api/status", headers={"Origin": "http://evil.com"}, auth=True)[0], 403)
        own = {"Origin": f"http://localhost:{self.port}", "Host": f"localhost:{self.port}"}
        self.assertEqual(self.req("GET", "/api/status", headers=own, auth=True)[0], 200)
        s, _, _ = self.req("POST", "/api/ask", raw=b'{"text":"x"}', headers={"Content-Type": "text/plain"}, auth=True)
        self.assertEqual(s, 415)
        big = b'{"text":"' + b"a" * (256 * 1024) + b'"}'
        self.assertEqual(self.req("POST", "/api/ask", raw=big, headers={"Content-Type": "application/json"}, auth=True)[0], 413)
        self.assertEqual(self.api("POST", "/api/ask", {"text": ""})[0], 400)

    # ---- endpoints
    def test_status(self):
        s, d = self.api("GET", "/api/status")
        self.assertEqual(s, 200)
        self.assertEqual(set(d["tiers"]), {"t1", "jev", "t2", "t3", "t4", "t5"})
        self.assertIn("tts_voice", d)
        self.assertEqual(d["tiers"]["t1"]["state"], "up")
        self.assertEqual(d["tiers"]["t5"]["state"], "off")
        self.assertIn(d["tiers"]["t4"]["state"], ("up", "degraded"))

    def test_health_offline(self):
        self.assertEqual(self.api("GET", "/api/health"), (200, {"jobs": []}))

    def test_usage_shape(self):
        s, d = self.api("GET", "/api/usage")
        self.assertEqual(s, 200)
        for k in ("claude", "tokens_today", "jev_usd_month", "groq_remaining", "openrouter_remaining",
                  "ollama_calls_today", "brightdata_pct", "apify_pct", "unknown_reasons"):
            self.assertIn(k, d)
        self.assertIn("session_resets_at", d["claude"])

    def test_widgets(self):
        s, d = self.api("GET", "/api/widgets/plan")
        self.assertEqual(d["events"], [{"time": "10:00", "title": "Standup"}])
        self.assertEqual(self.api("GET", "/api/widgets/inbox")[1], {"configured": False})
        s, d = self.api("GET", "/api/widgets/intel")
        self.assertEqual([h["title"] for h in d["headlines"]], ["Headline one", "Headline two"])
        self.assertRegex(d["last_run"], r"^\d\d:\d\d$")

    def test_adapters(self):
        self.assertEqual(server.adapt_plan({"directives": [], "calendar": {"calendar": "no-permission"}}),
                         {"directives": [], "events": [], "calendar": "denied"})
        self.assertEqual(server.adapt_plan({"calendar": {"calendar": "unavailable"}})["calendar"], "unavailable")
        self.assertEqual(server.adapt_inbox({"configured": True, "open": 2, "items": [{"title": "a", "date": "", "url": ""}]}),
                         {"configured": True, "need_action": 2, "items": [{"title": "a", "from": ""}]})

    def test_ask_saves_to_vault_and_feedback(self):
        s, d = self.api("POST", "/api/ask", {"text": "tell me something\nwith newline", "mode": "auto"})
        self.assertEqual(s, 200)
        for k in ("id", "answer", "final_tier", "provider", "model", "ms", "saved", "path"):
            self.assertIn(k, d)
        self.assertTrue(d["saved"])
        self.assertIsInstance(d["final_tier"], int)
        self.assertTrue(all(isinstance(p["tier"], int) for p in d["path"]))
        md = next((self.vault / "outputs" / "conversations").glob("*.md")).read_text()
        self.assertTrue(md.startswith("---\ntype: conversation\nsource: dashboard\ncreated: "))
        self.assertIn("tell me something with newline", md)
        self.assertEqual(self.api("POST", "/api/feedback", {"id": d["id"], "verdict": "up"}), (200, {"ok": True}))
        self.assertEqual(self.app.log.get(d["id"])["feedback"], "up")
        s, e = self.api("POST", "/api/feedback", {"id": d["id"], "verdict": "escalate"})
        self.assertEqual(s, 200)
        self.assertGreater(e["final_tier"], d["final_tier"])
        self.assertEqual(self.api("POST", "/api/feedback", {"id": "nope", "verdict": "up"})[0], 404)
        self.assertEqual(self.api("POST", "/api/feedback", {"id": d["id"], "verdict": "meh"})[0], 400)

    def test_ask_force_tier_and_tier1(self):
        s, d = self.api("POST", "/api/ask", {"text": "hello", "mode": "tier", "tier": 4})
        self.assertEqual((s, d["final_tier"]), (200, 4))
        self.assertEqual(self.api("POST", "/api/ask", {"text": "hello", "mode": "tier", "tier": 9})[0], 400)
        s, d = self.api("POST", "/api/ask", {"text": "what did Alice say about the launch?"})
        self.assertEqual(d["final_tier"], 1)
        self.assertIn("note.md:1", d["answer"])

    def test_night_missing_and_present(self):
        with mock.patch.dict(sys.modules, {"night": types.ModuleType("night"), "night.api": None}):
            self.assertEqual(self.api("GET", "/api/night")[1], {"last_run": None, "learned": 0, "pending": []})
            self.assertEqual(self.api("POST", "/api/night/approve", {"proposal_id": "p1"})[0], 503)
        fake = types.SimpleNamespace(status=lambda cfg: {"last_run": "22:00", "learned": 3, "pending": []},
                                     approve=lambda cfg, pid: {"ok": True, "id": pid})
        with mock.patch.dict(sys.modules, {"night": types.ModuleType("night"), "night.api": fake}):
            self.assertEqual(self.api("GET", "/api/night")[1]["learned"], 3)
            self.assertEqual(self.api("POST", "/api/night/approve", {"proposal_id": "p1"}), (200, {"ok": True, "id": "p1"}))
        self.assertEqual(self.api("POST", "/api/night/approve", {})[0], 400)

    # ---- actions
    def test_ask_proposes_action_and_approve_flow(self):
        block = ('Drafted it.\n\n```keystone-action\n{"type": "email_draft", "to": "jo@example.com", '
                 '"subject": "Rent", "body": "Hi Jo"}\n```\n\n```keystone-action\n{"type": "shell"}\n```')
        t2 = self.app.router.providers["T2"]
        with mock.patch.object(t2, "complete", return_value=server.Answer(block, "t2", "m", True, None, 1)) as c:
            s, d = self.api("POST", "/api/ask", {"text": "draft a reply to Jo about the rent"})
        self.assertIn("keystone-action", c.call_args.kwargs["system"])
        self.assertEqual(s, 200)
        self.assertEqual(d["answer"], "Drafted it.")
        self.assertEqual([a["type"] for a in d["actions"]], ["email_draft"])
        self.assertEqual(len(d["action_errors"]), 1)
        aid = d["actions"][0]["id"]
        md = next((self.vault / "outputs" / "conversations").glob("*.md")).read_text()
        self.assertIn(f"Proposed action #{aid}: Draft: email to jo@example.com", md)
        self.assertNotIn("keystone-action", md)
        s, lst = self.api("GET", "/api/actions")
        self.assertEqual([p["id"] for p in lst["pending"]], [aid])
        self.assertEqual(lst["pending"][0]["payload"]["to"], "jo@example.com")
        s, out = self.api("POST", f"/api/actions/{aid}/approve", {})
        self.assertEqual((s, out["status"]), (200, "done"))
        self.assertTrue(out["result"]["mailto"].startswith("mailto:jo@example.com?subject=Rent"))
        self.assertTrue(Path(out["result"]["path"]).is_file())
        self.assertEqual(self.api("POST", f"/api/actions/{aid}/approve", {})[0], 409)
        self.assertEqual(self.api("POST", f"/api/actions/{aid}/reject", {})[0], 409)
        self.assertEqual(self.api("POST", "/api/actions/99999/approve", {})[0], 404)
        self.assertEqual(self.api("GET", "/api/actions")[1]["recent"][0]["id"], aid)

    def test_plain_ask_has_no_system_prompt(self):
        t2 = self.app.router.providers["T2"]
        with mock.patch.object(t2, "complete", return_value=server.Answer("ok", "t2", "m", True, None, 1)) as c:
            s, d = self.api("POST", "/api/ask", {"text": "explain sqlite wal mode please"})
        self.assertNotIn("system", c.call_args.kwargs)
        self.assertEqual((d["actions"], d["action_errors"]), ([], []))

    def test_offline_fakes_notion_and_calendar(self):
        a, err = self.app.actions.propose({"type": "notion_task_update", "task": "Reply to landlord", "done": True}, {})
        self.assertIsNone(err)
        self.assertEqual(self.api("POST", f"/api/actions/{a['id']}/approve", {})[1]["result"], "updated Reply to landlord")
        a, err = self.app.actions.propose({"type": "calendar_add", "title": "X", "duration_min": 30,
                                           "start": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")}, {})
        self.assertEqual(self.api("POST", f"/api/actions/{a['id']}/reject", {})[1]["status"], "rejected")

    # ---- v2 widgets
    def test_new_widget_routes_offline(self):
        s, d = self.api("GET", "/api/widgets/weekly")
        self.assertEqual(s, 200)
        self.assertEqual(set(d), {"asked_by_tier", "asked_total", "skills_run", "briefs", "night_learned"})
        s, d = self.api("GET", "/api/widgets/system")
        self.assertEqual((s, d["ollama"], d["keys"]), (200, {"up": True, "models": 2}, {"groq": False, "openrouter": False}))

    # ---- skills
    def test_skill_allow_list_busy_and_done(self):
        self.assertEqual(self.api("POST", "/api/skills/rm-rf/run", {})[0], 404)
        self.assertEqual(self.api("POST", "/api/skills/night-school/run", {})[0], 404)
        gate = threading.Event()
        report = str((self.vault / "outputs" / "plans" / "x.md").resolve())

        def fake_run(cmd, **kw):
            self.assertEqual(kw["cwd"], str(self.vault))
            self.assertIs(kw["stdin"], subprocess.DEVNULL)
            gate.wait(5)
            return subprocess.CompletedProcess(cmd, 0, stdout=f"working\n{report}\n", stderr="")

        with mock.patch.object(jobs.subprocess, "run", fake_run):
            s, d = self.api("POST", "/api/skills/plan-today/run", {})
            self.assertEqual(s, 200)
            self.assertEqual(self.api("GET", f"/api/jobs/{d['job_id']}")[1]["state"], "running")
            self.assertEqual(self.api("POST", "/api/skills/vault-lint/run", {})[0], 409)
            gate.set()
            for _ in range(50):
                j = self.api("GET", f"/api/jobs/{d['job_id']}")[1]
                if j["state"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual((j["state"], j["report_path"], j["error"]), ("done", report, None))
        self.assertEqual(self.api("GET", "/api/jobs/000000000000")[0], 404)

    def test_report_path_must_be_in_vault(self):
        j = jobs.Jobs(self.vault, Path(self.tmp.name) / "d2")
        self.assertIsNone(j.report_path("/etc/passwd.md\n"))
        self.assertIsNone(j.report_path("no report here"))


if __name__ == "__main__":
    unittest.main()


class LibraryApiTests(ServerTests):
    """Upload, listing, file and remind endpoints (inherits the fixture; its own tests rerun harmlessly)."""
    def up(self, name="Policy.pdf", data=b"%PDF-x", extra=None, ctype="application/octet-stream", auth=True):
        h = {"Content-Type": ctype, "X-Filename": name, **(extra or {})}
        s, _, d = self.req("POST", "/api/library/upload", raw=data, headers=h, auth=auth)
        return s, d

    def inbox(self):
        return self.app.inbox_dir

    def test_upload_basic_and_sanitising(self):
        s, d = self.up("..%2F..%2Fetc%2FMy%20Car%3A%20Policy.PDF")
        self.assertEqual((s, d["name"]), (200, "My Car Policy.pdf"))
        self.assertEqual((self.inbox() / "My Car Policy.pdf").read_bytes(), b"%PDF-x")
        s, d = self.up("C:\\Users\\x\\scan.jpg")
        self.assertEqual(d["name"], "scan.jpg")
        s, d = self.up("scan.jpg")  # no overwrite
        self.assertEqual(d["name"], "scan (2).jpg")
        self.assertEqual([p.name for p in self.inbox().glob(".upload-*")], [])

    def test_upload_sidecar(self):
        s, d = self.up("Side.txt", extra={"X-Description": "Jo%27s%20car%20policy"})
        self.assertEqual(json.loads((self.inbox() / "Side.keystone.json").read_text()), {"description": "Jo's car policy"})
        self.up("Plain.txt")
        self.assertFalse((self.inbox() / "Plain.keystone.json").exists())
        self.up("Long.txt", extra={"X-Description": "x" * 900})
        self.assertEqual(len(json.loads((self.inbox() / "Long.keystone.json").read_text())["description"]), 500)

    def test_upload_rejections(self):
        self.assertEqual(self.up("evil.exe")[0], 415)
        self.assertEqual(self.up("noext")[0], 415)
        self.assertEqual(self.up("a.pdf", ctype="application/json")[0], 415)
        self.assertEqual(self.up("a.pdf", data=b"")[0], 400)
        self.assertEqual(self.up("a.pdf", auth=False)[0], 401)
        s, _, _ = self.req("POST", "/api/library/upload", raw=b"x", auth=True,
                           headers={"Content-Type": "application/octet-stream", "X-Filename": "a.pdf",
                                    "Host": "evil.com"})
        self.assertEqual(s, 403)

    def test_upload_size_cap(self):
        with mock.patch.object(server, "MAX_UPLOAD", 1000):
            self.assertEqual(self.up("big.pdf", data=b"a" * 1001)[0], 413)
            self.assertEqual(self.up("ok.pdf", data=b"a" * 1000)[0], 200)
        self.assertFalse((self.inbox() / "big.pdf").exists())

    def test_octet_stream_only_on_upload(self):
        s, _, _ = self.req("POST", "/api/ask", raw=b"x", headers={"Content-Type": "application/octet-stream"}, auth=True)
        self.assertEqual(s, 415)

    def _filed(self, **f):
        note = self.vault / "library" / "Car" / "n.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("note")
        fields = {"category": "Car", "title": "Car insurance", "renews": (date.today() + timedelta(days=60)).isoformat(), **f}
        lib = self.app.library
        rid = lib._exec("INSERT INTO library (original_name, path, status, fields, note_path, created, decided) "
                        "VALUES ('c.pdf','/x','filed',?,?,'2026-11-02','2026-11-02T10:00:00')",
                        (json.dumps(fields), str(note)))[1]
        return rid

    def _review(self):
        return self.app.library._exec("INSERT INTO library (original_name, path, status, fields, created) "
                                      "VALUES ('r.pdf',?,'review','{\"reason\":\"no text found\"}','2026-11-02')",
                                      (str(self.vault / "r.pdf"),))[1]

    def test_listing_and_file(self):
        rid = self._review()
        (self.vault / "r.pdf").write_bytes(b"pdf")
        s, d = self.api("GET", "/api/library")
        self.assertEqual(s, 200)
        self.assertIn(rid, [r["id"] for r in d["review"]])
        self.assertEqual(self.api("POST", f"/api/library/{rid}/file", {"category": "Pets"})[0], 400)
        self.assertEqual(self.api("POST", f"/api/library/{rid}/file", {})[0], 400)
        self.assertEqual(self.api("POST", f"/api/library/{rid}/file", {"category": "Car", "date": "x"})[0], 400)
        self.assertEqual(self.api("POST", "/api/library/99999/file", {"category": "Car"})[0], 404)
        s, d = self.api("POST", f"/api/library/{rid}/file", {"category": "Car", "title": "Fixed"})
        self.assertEqual((s, d["status"]), (200, "filed"))
        self.assertEqual(self.api("POST", f"/api/library/{rid}/file", {"category": "Car"})[0], 409)

    def test_remind_date_maths(self):
        from datetime import datetime
        now = datetime(2026, 11, 2, 15, 0)
        self.assertEqual(server.remind_start("2026-12-31", now), datetime(2026, 12, 17, 9, 0))
        self.assertEqual(server.remind_start("2026-11-10", now), datetime(2026, 11, 3, 9, 0))  # past -> tomorrow
        self.assertEqual(server.remind_start("2026-11-16", now), datetime(2026, 11, 3, 9, 0))  # today 09:00 is gone

    def test_remind_endpoint(self):
        rid = self._filed()
        s, a = self.api("POST", f"/api/library/{rid}/remind", {})
        self.assertEqual((s, a["type"]), (200, "calendar_add"))
        self.assertIn("Renew: Car insurance", a["summary"])
        p = [x for x in self.app.actions.pending() if x["id"] == a["id"]][0]["payload"]
        self.assertEqual((p["start"][11:], p["notes"]), ("09:00", "library/Car/n.md"))
        self.assertEqual(p["end"][11:], "09:15")
        e = self._filed(renews=None, expires=(date.today() + timedelta(days=3)).isoformat(), title="Passport")
        s, a = self.api("POST", f"/api/library/{e}/remind", {})
        self.assertIn("Expires: Passport", a["summary"])
        self.assertEqual(self.api("POST", f"/api/library/{self._filed(renews=None)}/remind", {})[0], 400)
        self.assertEqual(self.api("POST", f"/api/library/{self._review()}/remind", {})[0], 400)
        self.assertEqual(self.api("POST", "/api/library/99999/remind", {})[0], 404)

    def test_ask_vault_search_includes_library(self):
        self._filed()
        (self.vault / "library" / "Car" / "n.md").write_text("Car insurance renews 2026-12-17\n")
        self.assertIn("library/Car/n.md:1:", self.app.vault_search("insurance renews")[0])

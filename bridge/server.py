import hmac
import importlib
import json
import os
import re
import secrets
import shutil
import tempfile
import urllib.parse
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bridge import actions, awr, jobs, library, usage, widgets
from bridge.config import ROOT, load_config, load_env
from bridge.log import Log
from bridge.providers import Answer
from bridge.route import Router

WEB = ROOT / "web"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
MAX_BODY = 256 * 1024
MAX_UPLOAD = 25 * 1024 * 1024
UPLOAD_EXT = {"pdf", "png", "jpg", "jpeg", "heic", "tiff", "txt", "md", "csv", "doc", "docx", "rtf", "odt"}


# ---- offline fakes (AOS_OFFLINE=1): the whole server runs with no network, no subprocess ------------------
class FakeProvider:
    def __init__(self, name="fake"):
        self.name = name

    def up(self):
        return True

    def complete(self, prompt, system=None, timeout=60):
        text = "PASS" if system and "grade" in system else f"[offline {self.name}] canned answer"
        return Answer(text, self.name, "fake-model", True, None, 1)


class FakeJev:
    def decide(self, text):
        return "T2", 0.95, 0.0


class FakeWidgets:
    intel = staticmethod(widgets.intel)  # pure file read

    @staticmethod
    def inbox(env):
        return {"configured": False}

    ollama_models = staticmethod(lambda: 2)
    last_backup = staticmethod(lambda vault_dir: "2026-11-02T00:00:00+00:00")
    weekly_counts = staticmethod(widgets.weekly_counts)  # pure file/db reads over the (temp) vault
    system_status = staticmethod(widgets.system_status)

    @staticmethod
    def plan(cfg, env):
        return {"directives": [{"done": False, "text": "Ship it"}], "follow_ups": [],
                "calendar": {"events": [{"start": "10:00", "title": "Standup"}]}}


class FakeNotion:
    """Offline stand-in for actions.notion_http: one Email Tasks page, a checkbox and a status property."""
    PAGE = {"id": "0" * 31 + "1", "properties": {"Name": {"type": "title", "title": [{"plain_text": "Reply to landlord"}]}}}

    def __call__(self, method, path, env, body=None):
        db = env.get("NOTION_EMAIL_TASKS_DB", "")
        if path.endswith("/query"):
            return {"results": [self.PAGE]}
        if path.startswith("pages/") and method == "GET":
            return dict(self.PAGE, parent={"type": "database_id", "database_id": db})
        if path.startswith("databases/"):
            return {"properties": {"Done": {"type": "checkbox"}, "Status": {"type": "status", "status": {
                "options": [{"name": "To do"}, {"name": "Done"}]}}}}
        return {}


# ---- adapters: widget/usage outputs -> the response shapes fixed by the dashboard ---------------------------
def tnum(tier):
    return int(tier[1:]) if isinstance(tier, str) and re.fullmatch(r"T[1-5]", tier) else None


def adapt_plan(raw):
    cal = raw.get("calendar") or {}
    out = {"directives": raw.get("directives", []),
           "events": [{"time": e["start"], "title": e["title"]} for e in cal.get("events", [])]}
    if "calendar" in cal:
        out["calendar"] = "denied" if cal["calendar"] == "no-permission" else "unavailable"
    return out


def adapt_inbox(raw):
    if "items" not in raw:
        return raw
    return {"configured": True, "need_action": raw.get("open", len(raw["items"])),
            "items": [{"title": i["title"], "from": i.get("from", "")} for i in raw["items"]]}


def adapt_intel(raw):
    if raw.get("empty"):
        return raw
    last = datetime.fromtimestamp(Path(raw["path"]).stat().st_mtime).strftime("%H:%M") if raw.get("path") else None
    return {"headlines": raw.get("headlines", []), "last_run": last, "path": raw.get("path")}


def adapt_usage(raw, stats):
    pro, tok, fc = raw["claude_pro"], raw["claude_tokens_today"], raw.get("free_cloud", {})

    out = {"claude": {"session_pct": pro.get("session_pct"), "week_pct": pro.get("week_pct"),
                      "session_resets_at": pro.get("resets_at"), "week_resets_at": pro.get("week_resets_at"),
                      "source": pro.get("source")},
           "tokens_today": [{"model": m, "tokens": t} for m, t in (tok.get("models") or {}).items()],
           "jev_usd_month": stats.get("jev_usd_month"), "ollama_calls_today": stats.get("ollama_calls_today"),
           "groq_remaining": fc.get("groq", {}).get("remaining"),
           "openrouter_remaining": fc.get("openrouter", {}).get("remaining"),
           "brightdata_pct": raw.get("brightdata", {}).get("pct"), "apify_pct": raw.get("apify", {}).get("pct")}
    why = {"groq_remaining": "No Groq rate-limit header seen yet (no key, or no call made).",
           "openrouter_remaining": "No OpenRouter rate-limit header seen yet (no key, or no call made)."}
    out["unknown_reasons"] = {k: why.get(k, "Not available from the source yet.")
                              for k, v in out.items() if v is None and k != "unknown_reasons"}
    return out


def shape_answer(r, saved):
    steps = []
    if tnum(r.get("jev_choice")):
        steps.append({"tier": tnum(r["jev_choice"]), "provider": "jev", "p": r.get("jev_p"), "step": "jev"})
    for s in r.get("path", []):
        step = {"tier": tnum(s.get("tier")), "provider": s.get("provider"), "model": s.get("model"),
                "ok": s.get("ok"), "ms": s.get("ms")}
        if s.get("check"):
            step["verdict"] = s["check"].split(":")[0].strip().lower()
        if s.get("error"):
            step["error"] = s["error"]
        steps.append(step)
    return {"id": r.get("id"), "answer": r["answer"], "final_tier": tnum(r.get("final_tier")),
            "provider": r.get("provider"), "model": r.get("model"), "ms": r.get("ms"), "saved": saved, "path": steps}


def save_upload(inbox, stem, ext, side, rfile, n):
    """Stream n bytes to a hidden temp file in inbox, then (sidecar first, so the scanner sees it) link the file
    into place without overwriting. -> final file name, or None if the body was shorter than n."""
    inbox.mkdir(parents=True, exist_ok=True)
    tmp = inbox / f".upload-{secrets.token_hex(6)}.part"
    try:
        with tmp.open("wb") as fh:
            left = n
            while left > 0:
                chunk = rfile.read(min(1 << 20, left))
                if not chunk:
                    return None
                fh.write(chunk)
                left -= len(chunk)
        for i in range(1, 1000):
            base = stem + (f" ({i})" if i > 1 else "")
            dest, sc = inbox / (base + ext), inbox / (base + library.SIDECAR)
            if dest.exists():
                continue
            if side:
                try:
                    with sc.open("x") as fh:
                        json.dump(side, fh)
                except FileExistsError:
                    continue
            try:
                os.link(tmp, dest)  # atomic and fails if the name is taken
            except FileExistsError:
                sc.unlink(missing_ok=True)  # only ever our own reservation
                continue
            return dest.name
        raise OSError("too many files with this name")
    finally:
        tmp.unlink(missing_ok=True)


def remind_start(date, now):
    """09:00 local, 14 days before `date` (YYYY-MM-DD); tomorrow 09:00 if that is not in the future."""
    start = datetime.fromisoformat(date).replace(hour=9) - timedelta(days=14)
    return start if start >= now else (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)


def library_remind(app, rid, kind=None):
    r = app.library.get(rid)
    if r is None:
        return 404, {"error": "unknown document"}
    f = r["fields"]
    kinds = [k for k in ("renews", "expires") if f.get(k)]
    if r["status"] != "filed" or not kinds or (kind is not None and kind not in kinds):
        return 400, {"error": "only a filed document with a renews or expires date can have a reminder"}
    kind = kind or kinds[0]
    title = f.get("title") or Path(r["original_name"]).stem
    try:
        note = str(Path(r["note_path"]).relative_to(app.vault))
    except (TypeError, ValueError):
        note = r["note_path"] or ""
    start = remind_start(f[kind], app.actions.now())
    a, err = app.actions.propose({"type": "calendar_add", "title": ("Renew: " if kind == "renews" else "Expires: ") + title,
                                  "start": start.strftime(actions.TIME_FMT), "duration_min": 15,
                                  **({"notes": note} if note else {})}, app.env)
    return (200, a) if a else (400, {"error": err})


# ---- the app: all state, no HTTP ------------------------------------------------------------------------
class App:
    def __init__(self, cfg, env, log, ollama, w, jobs_, data_dir, health=lambda: []):
        self.cfg, self.env, self.log, self.ollama = cfg, env, log, ollama
        self.w, self.jobs, self.data_dir = w, jobs_, data_dir
        self.health = health
        self.router = None  # set by build_app (its lookups need this object)
        self.token = secrets.token_urlsafe(32)  # once per process
        self.vault = widgets.vault(cfg)
        self.actions = None  # set by build_app (needs the db path)
        self.library = None  # set by build_app
        self.inbox_dir = None  # uploads land here (first library_inbox_dirs entry)

    def status(self):
        t4_key = any(self.env.get(e.get("key_env", "")) for e in self.cfg.get("tier4_providers", []))
        up = {"state": "up"}
        return {"tts_voice": self.cfg.get("tts_voice"), "tiers": {
            "t1": up,
            "jev": up if awr.jev_key(self.env) else {"state": "degraded", "reason": "no key"},
            "t2": up if self.ollama.up() else {"state": "off", "reason": "ollama not reachable"},
            "t3": up if shutil.which("claude") else {"state": "off", "reason": "claude CLI not found"},
            "t4": up if t4_key else {"state": "degraded", "reason": "no key"},
            "t5": up if self.cfg.get("paid_enabled") else {"state": "off", "reason": "paid_enabled is false"}}}

    def weekly(self):
        return self.w.weekly_counts(self.vault, self.log.asked_by_tier(7), self.jobs.jobs.values())

    def system(self):
        return self.w.system_status(self.cfg, self.env, self.health(), self.ollama.up(), self.w.ollama_models(),
                                    self.w.last_backup(self.vault))

    def usage(self):
        return adapt_usage(usage.get_usage(self.cfg), self.log.stats())

    def save_conversation(self, question, r):
        """Append to vault outputs/conversations/YYYY-MM-DD.md. Returns saved flag; never raises."""
        if not r.get("final_tier") or not self.vault.is_dir():
            return False
        now = datetime.now()
        f = self.vault / "outputs" / "conversations" / f"{now:%Y-%m-%d}.md"
        q = " ".join(question.split())[:60]
        route_line = f"route: {r['final_tier']} · {r['provider']} · {r['model']} · {r['ms']} ms"
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            if not f.exists():
                f.write_text(f"---\ntype: conversation\nsource: dashboard\ncreated: {now:%Y-%m-%d}\n---\n")
            with f.open("a") as fh:
                fh.write(f"\n## {now:%H:%M} — {q}\n\n{r['answer']}\n\n*{route_line}*\n")
            return True
        except OSError:
            return False

    def answer_with_actions(self, question, r):
        """Strip keystone-action blocks, store valid ones as pending, save the clean answer. Never executes."""
        props, errs = [], []
        if r.get("final_tier") and r["final_tier"] != "T1" and self.actions:  # T1 text is data, not a model answer
            clean, items = actions.extract(r["answer"])
            for raw in items:
                a, err = self.actions.propose(raw, self.env) if isinstance(raw, dict) else (None, raw)
                if a:
                    props.append(a)
                else:
                    errs.append(err)
            r = dict(r, answer=clean)
        saved_text = r["answer"] + "".join(f"\n\nProposed action #{a['id']}: {a['summary']} — needs approval"
                                           for a in props)
        out = shape_answer(r, self.save_conversation(question, dict(r, answer=saved_text)))
        out.update(actions=props, action_errors=errs)
        return out

    def ask(self, text, mode, tier, model):
        return self.answer_with_actions(text, self.router.ask(text, mode=mode, tier=tier, model=model))

    def escalate(self, rid):
        row = self.log.get(rid)
        return self.answer_with_actions(row["text"], self.router.escalate(rid))

    def night(self, fn, *args, default):
        try:
            api = importlib.import_module("night.api")
        except ImportError:
            return default
        return getattr(api, fn)(self.cfg, *args)

    def vault_search(self, term):
        hits, low = [], term.lower()
        for sub in ("wiki", "outputs", "library"):
            for f in sorted((self.vault / sub).rglob("*.md")):
                try:
                    lines = f.read_text(errors="replace").splitlines()
                except OSError:
                    continue
                for n, line in enumerate(lines, 1):
                    if low in line.lower():
                        hits.append(f"{f.relative_to(self.vault)}:{n}: {line.strip()[:200]}")
                        if len(hits) == 5:
                            return hits
        return hits or "Nothing found."


def build_app(cfg, env, offline=False, data_dir=None):
    data_dir = Path(data_dir or ROOT / "data")
    vault = widgets.vault(cfg)
    log = Log(data_dir / "requests.db")
    if offline:
        providers = {t: FakeProvider(t.lower()) for t in ("T2", "T3", "T4", "T5")}
        ollama, checker, jev, w = FakeProvider("ollama"), FakeProvider("check"), FakeJev(), FakeWidgets
    else:
        from bridge.jevtier import JevTier
        from bridge.providers.claude_cli import ClaudeCliProvider
        from bridge.providers.free_cloud import FreeCloudProvider
        from bridge.providers.ollama import OllamaProvider
        from bridge.providers.paid import PaidProvider
        ollama = OllamaProvider(cfg["ollama_model"], cfg.get("ollama_fallback"))
        providers = {"T2": ollama, "T3": ClaudeCliProvider(cfg["tier3_model"], vault),
                     "T4": FreeCloudProvider(cfg["tier4_providers"], env), "T5": PaidProvider(cfg)}
        checker = OllamaProvider(cfg["check_model"])
        jev = JevTier(data_dir / "rulebook.json", cfg.get("jev_threshold", 0.9))
        w = widgets
    from bridge import health as health_mod
    app = App(cfg, env, log, ollama, w, jobs.Jobs(vault, data_dir), data_dir,
              health=(lambda: []) if offline else health_mod.health)

    def priorities():
        try:
            items = widgets.parse_directives((vault / "wiki" / "directives.md").read_text())
        except OSError:
            return "No directives file found."
        return [("[done] " if d["done"] else "") + d["text"] for d in items] or "No directives set."

    def inbox_lookup():
        r = adapt_inbox(w.inbox(env))
        if r.get("configured") is False:
            return "Notion is not connected."
        if r.get("error"):
            return f"Inbox unavailable: {r['error']}"
        return [f"{r['need_action']} need action"] + [i["title"] for i in r["items"][:5]]

    def usage_lookup():
        u = adapt_usage(usage.get_usage(cfg), log.stats())
        flat = {**u["claude"], "jev_usd_month": u["jev_usd_month"], "ollama_calls_today": u["ollama_calls_today"]}
        return {k: v for k, v in flat.items() if v is not None}

    app.actions = actions.Actions(log.path, http=FakeNotion(), calendar=lambda *a: "OK offline-event") if offline \
        else actions.Actions(log.path)
    if offline:  # no Ollama, no reader subprocess: uploads just land in data_dir/inbox
        app.inbox_dir = data_dir / "inbox"
        app.library = library.Library(log.path, vault, None, lambda p: None)
    else:
        dirs = cfg.get("library_inbox_dirs") or [str(data_dir / "inbox")]
        app.inbox_dir = Path(dirs[0]).expanduser()
        app.library = library.Library(log.path, vault, library.default_llm(cfg), notify=library.macos_notify)
    lookups = {"priorities": priorities, "inbox": inbox_lookup, "usage": usage_lookup,
               "vault_search": app.vault_search}
    # the router reads session_pct at the top level; get_usage nests it under claude_pro
    app.router = Router(cfg, providers, checker, jev, lookups, lambda: usage.get_usage(cfg)["claude_pro"], log)
    return app


# ---- HTTP -----------------------------------------------------------------------------------------------
# Scripts only from us; no framing (clickjacking); fonts from Google only. Inline styles: app.js sets a few.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'")


class Handler(BaseHTTPRequestHandler):
    timeout = 120  # socket timeout; the longest request is /api/ask

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def _err(self, code, msg):
        self._json(code, {"error": msg})

    def _guard(self):
        """Host / Origin checks for every request. Returns False after sending the rejection."""
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._err(403, "bad host")
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            self._err(403, "bad origin")
            return False
        return True

    def _authed(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:  # noqa: BLE001 - malformed cookie header = unauthenticated
            return False
        m = c.get("aos")
        return bool(m) and hmac.compare_digest(m.value.encode(), self.server.app.token.encode())

    def _body(self):
        """Parsed JSON object, or None after sending the rejection."""
        if self.headers.get_content_type() != "application/json":
            self._err(415, "content-type must be application/json")
            return None
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._err(400, "bad content-length")
            return None
        if n > MAX_BODY:
            left = min(n, 1 << 20)  # drain a bounded amount so the client sees our 413, not a reset
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            self._err(413, "body too large")
            return None
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self._err(400, "body must be a JSON object")
            return None
        return data

    def _drain(self, n):
        left = min(n, 1 << 20)  # bounded, so the client sees our error, not a reset
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)

    def _upload(self, app):
        """POST /api/library/upload: raw bytes streamed to the inbox. Filename/description in headers."""
        if self.headers.get_content_type() != "application/octet-stream":
            return self._err(415, "content-type must be application/octet-stream")
        try:
            n = int(self.headers.get("Content-Length") or "")
        except ValueError:
            return self._err(400, "content-length required")
        if n > MAX_UPLOAD:
            self._drain(n)
            return self._err(413, "file too large (max 25 MB)")
        if n <= 0:
            return self._err(400, "empty file")
        hdr = lambda k: urllib.parse.unquote(self.headers.get(k) or "")  # noqa: E731
        raw = re.split(r"[\\/]", hdr("X-Filename"))[-1]
        stem, ext = os.path.splitext(raw)
        ext = ext.lower().lstrip(".")
        if ext not in UPLOAD_EXT:
            self._drain(n)
            return self._err(415, "file type not allowed (pdf, images, txt, md, csv, doc, docx, rtf, odt)")
        desc = " ".join(hdr("X-Description").split())[:500]
        side = {"description": desc} if desc else {}
        try:
            name = save_upload(app.inbox_dir, library.safe_name(stem, "Document"), "." + ext, side, self.rfile, n)
        except OSError as e:
            return self._err(500, f"could not save the file ({type(e).__name__})")
        if name is None:
            return self._err(400, "upload was cut short")
        self._json(200, {"ok": True, "name": name})

    def _handle(self, method):
        if not self._guard():
            return
        path = self.path.split("?", 1)[0]
        app = self.server.app
        if method == "GET" and path in STATIC:
            name, ctype = STATIC[path]
            try:
                body = (WEB / name).read_bytes()
            except OSError:
                return self._err(404, "not found")
            extra = []
            if path in ("/", "/index.html"):
                extra = [("Set-Cookie", f"aos={app.token}; HttpOnly; SameSite=Strict; Path=/")]
            return self._send(200, body, ctype, extra)
        if not path.startswith("/api/"):
            return self._err(404, "not found")
        if not self._authed():
            return self._err(401, "unauthorized")
        if method == "POST" and path == "/api/library/upload":
            return self._upload(app)  # the one non-JSON body
        data = {}
        if method == "POST":
            data = self._body()
            if data is None:
                return
        try:
            code, obj = route(app, method, path, data)
        except Exception as exc:  # noqa: BLE001 - no internals or secrets in the response
            code, obj = 500, {"error": f"internal error ({type(exc).__name__})"}
        self._json(code, obj)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def route(app, method, path, data):
    """-> (status, json-able). All endpoint logic lives here, none in the handler."""
    if method == "GET":
        simple = {"/api/status": app.status, "/api/health": lambda: {"jobs": app.health()}, "/api/usage": app.usage,
                  "/api/widgets/inbox": lambda: adapt_inbox(app.w.inbox(app.env)),
                  "/api/widgets/plan": lambda: adapt_plan(app.w.plan(app.cfg, app.env)),
                  "/api/widgets/weekly": app.weekly, "/api/widgets/system": app.system,
                  "/api/widgets/intel": lambda: adapt_intel(app.w.intel(app.cfg)),
                  "/api/night": lambda: app.night("status", default={"last_run": None, "learned": 0, "pending": []}),
                  "/api/library": app.library.listing,
                  "/api/actions": lambda: {"pending": app.actions.pending(), "recent": app.actions.recent()}}
        if path in simple:
            return 200, simple[path]()
        m = re.fullmatch(r"/api/jobs/([0-9a-f]{12})", path)
        j = app.jobs.get(m.group(1)) if m else None
        if j:
            return 200, {k: j[k] for k in ("state", "started", "finished", "report_path", "error")}
        return 404, {"error": "not found"}
    if path == "/api/ask":
        text, mode, tier = data.get("text"), data.get("mode", "auto"), data.get("tier")
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            return 400, {"error": "text required (max 8000 chars)"}
        if mode not in ("auto", "tier", "model"):
            return 400, {"error": "bad mode"}
        if mode == "tier":
            if tier not in (1, 2, 3, 4, 5):
                return 400, {"error": "tier must be 1-5"}
            tier = f"T{tier}"
        if mode == "model" and not (isinstance(data.get("model"), str) and data["model"].strip()):
            return 400, {"error": "model required"}
        return 200, app.ask(text, mode, tier if mode == "tier" else None, data.get("model") if mode == "model" else None)
    if path == "/api/feedback":
        rid, verdict = data.get("id"), data.get("verdict")
        if not isinstance(rid, str) or verdict not in ("up", "down", "escalate"):
            return 400, {"error": "id and verdict (up|down|escalate) required"}
        if not app.log.get(rid):
            return 404, {"error": "unknown request id"}
        if verdict == "escalate":
            return 200, app.escalate(rid)
        app.log.set_feedback(rid, verdict)
        return 200, {"ok": True}
    m = re.fullmatch(r"/api/skills/([^/]+)/run", path)
    if m:
        try:
            return 200, {"job_id": app.jobs.start(m.group(1))}
        except KeyError:
            return 404, {"error": "unknown skill"}
        except jobs.Busy:
            return 409, {"error": "a skill is already running"}
    m = re.fullmatch(r"/api/actions/(\d{1,9})/(approve|reject)", path)
    if m:
        aid = int(m.group(1))
        return app.actions.approve(aid, app.env, app.vault) if m.group(2) == "approve" else app.actions.reject(aid)
    m = re.fullmatch(r"/api/library/(\d{1,9})/(file|remind)", path)
    if m:
        rid = int(m.group(1))
        if m.group(2) == "remind":
            return library_remind(app, rid, data.get("kind"))
        if not isinstance(data.get("category"), str) or \
                any(data.get(k) is not None and not isinstance(data[k], str) for k in ("title", "date")):
            return 400, {"error": "category required"}
        return app.library.file_review(rid, data["category"], data.get("title"), data.get("date"))
    if path == "/api/night/approve":
        pid = data.get("proposal_id")
        if not isinstance(pid, str) or not pid:
            return 400, {"error": "proposal_id required"}
        r = app.night("approve", pid, default=None)
        if r is None:
            return 503, {"error": "night school is not installed"}
        return 200, r if isinstance(r, dict) else {"ok": True}
    return 404, {"error": "not found"}


def make_server(port=0, app=None):
    if app is None:
        offline = os.environ.get("AOS_OFFLINE") == "1"
        app = build_app(load_config(), load_env(), offline=offline,
                        data_dir=tempfile.mkdtemp(prefix="aos-") if offline else None)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.app = app
    return srv

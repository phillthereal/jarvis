"""Actions with approval (SPEC "v2 additions"). Model answers may carry ```keystone-action JSON blocks; the bridge
validates them into *pending* rows in requests.db. Nothing runs until POST /api/actions/<id>/approve, which executes
once (status guard). Never sends email: email_draft only writes a vault file + a mailto: link. Stdlib only."""
import contextlib
import datetime
import json
import re
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bridge import widgets

SCHEMA = """CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY, type TEXT NOT NULL, payload TEXT NOT NULL, summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL, decided TEXT, result TEXT);"""

FENCE_RE = re.compile(r"```keystone-action[ \t]*\r?\n(.*?)```", re.S)
MAX_PER_ANSWER = 3
EMAIL_RE = re.compile(r"[^@\s<>,;:\"'()\[\]\\]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
NOTION_ID_RE = re.compile(r"[0-9a-f]{32}")
TIME_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d")
TIME_FMT = "%Y-%m-%dT%H:%M"
MAILTO_CAP = 1800
TRUNC_NOTE = "\n\n… (full draft in vault)"
FIELDS = {"notion_task_update": {"task", "page_id", "done", "status"},
          "calendar_add": {"title", "start", "end", "duration_min", "notes"},
          "email_draft": {"to", "subject", "body"}}


class ActionError(Exception):
    """A known, secret-free failure message (shown to Filip as-is)."""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _nodash(s):
    return str(s or "").replace("-", "").lower()


def _err(exc):
    """Secret-free text for an unexpected executor failure."""
    if isinstance(exc, ActionError):
        return str(exc)
    return type(exc).__name__ + (f" {exc.code}" if isinstance(exc, urllib.error.HTTPError) else "")


# ---- parsing ------------------------------------------------------------------------------------
def extract(answer_text):
    """-> (clean_text, items). Each item is a dict (raw proposal) or an error string. Blocks are always stripped."""
    items = []
    for i, m in enumerate(FENCE_RE.finditer(answer_text or "")):
        if i >= MAX_PER_ANSWER:
            items.append(f"more than {MAX_PER_ANSWER} action blocks; the rest were ignored")
            break
        try:
            raw = json.loads(m.group(1))
        except ValueError:
            items.append("action block is not valid JSON")
            continue
        items.append(raw if isinstance(raw, dict) else "action block must be a JSON object")
    clean = FENCE_RE.sub("", answer_text or "")
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    return re.sub(r"\n{3,}", "\n\n", clean).strip(), items


def _str(raw, key, maxlen, required=True, oneline=False):
    v = raw.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ActionError(f"{key} must be a non-empty string")
    if len(v) > maxlen:
        raise ActionError(f"{key} is longer than {maxlen} characters")
    if oneline and ("\n" in v or "\r" in v):
        raise ActionError(f"{key} must be one line")
    return v.strip() if oneline else v


def _time(raw, key):
    v = raw.get(key)
    if not isinstance(v, str) or not TIME_RE.fullmatch(v):
        raise ActionError(f"{key} must be YYYY-MM-DDTHH:MM (local time)")
    try:
        return datetime.datetime.strptime(v, TIME_FMT)
    except ValueError:
        raise ActionError(f"{key} is not a real date/time") from None


# ---- notion http (injectable) ---------------------------------------------------------------------
def notion_http(method, path, env, body=None):
    if not env.get("NOTION_TOKEN") or not env.get("NOTION_EMAIL_TASKS_DB"):
        raise ActionError("Notion is not configured")
    req = urllib.request.Request(
        "https://api.notion.com/v1/" + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {env['NOTION_TOKEN']}", "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _page_title(page):
    for p in (page.get("properties") or {}).values():
        if p.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in p.get("title", []))
    return ""


# ---- calendar helper (injectable) -----------------------------------------------------------------
def calendar_run(title, start, end, notes=""):
    """Runs KeystoneCalendar.app in add mode. -> first output line ('OK <id>' / 'ERR <reason>')."""
    if not widgets.CAL_APP.exists():
        raise ActionError("KeystoneCalendar.app is not installed (run macos/calendar/build.sh)")
    args = ["add", "--no-prompt", title, start, end] + ([notes] if notes else [])
    with tempfile.NamedTemporaryFile("r", suffix=".txt") as out:
        try:
            subprocess.run(["open", "-W", "-g", "-n", "--stdout", out.name, str(widgets.CAL_APP), "--args", *args],
                           capture_output=True, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            raise ActionError("calendar helper did not respond") from None
        return (out.read().strip().splitlines() or [""])[0]


# ---- email draft helpers ----------------------------------------------------------------------------
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40].strip("-") or "draft"


def _fit(build, text, cap):
    """Longest prefix n of text with len(build(text[:n])) < cap (build is monotonic in n)."""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(build(text[:mid])) < cap:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def mailto(to, subject, body, cap=MAILTO_CAP):
    q = lambda s: urllib.parse.quote(s, safe="")  # noqa: E731
    url = lambda subj, b: f"mailto:{urllib.parse.quote(to, safe='@')}?subject={q(subj)}&body={q(b)}"  # noqa: E731
    if len(url(subject, body)) < cap:
        return url(subject, body)
    if len(url(subject, TRUNC_NOTE)) >= cap:  # a huge non-ASCII subject alone can blow the cap
        subject = _fit(lambda s: url(s, TRUNC_NOTE), subject, cap)
    return url(subject, _fit(lambda b: url(subject, b + TRUNC_NOTE), body, cap) + TRUNC_NOTE)


# ---- the store ------------------------------------------------------------------------------------------
class Actions:
    def __init__(self, path, http=notion_http, calendar=calendar_run, now=datetime.datetime.now):
        self.path, self.http, self.calendar, self.now = str(path), http, calendar, now
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self._db()) as db:
            db.executescript(SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _exec(self, sql, args=()):
        with contextlib.closing(self._db()) as db, db:
            cur = db.execute(sql, args)
            return cur.rowcount, cur.lastrowid, cur.fetchall()

    def get(self, aid):
        rows = self._exec("SELECT * FROM actions WHERE id = ?", (aid,))[2]
        if not rows:
            return None
        d = dict(rows[0])
        d["payload"] = json.loads(d["payload"])
        d["result"] = json.loads(d["result"]) if d["result"] else None
        return d

    def pending(self):
        rows = self._exec("SELECT id FROM actions WHERE status = 'pending' ORDER BY id")[2]
        return [{k: a[k] for k in ("id", "type", "summary", "payload", "created")} for a in map(self.get, [r[0] for r in rows])]

    def recent(self, n=5):
        rows = self._exec("SELECT id FROM actions WHERE status != 'pending' ORDER BY decided DESC, id DESC LIMIT ?", (n,))[2]
        return [{k: a[k] for k in ("id", "type", "summary", "status", "result", "decided")} for a in map(self.get, [r[0] for r in rows])]

    # ---- proposal
    def propose(self, raw, env):
        """-> (action dict | None, error | None). Only valid proposals are stored (as pending)."""
        try:
            if not isinstance(raw, dict):
                raise ActionError("action must be a JSON object")
            kind = raw.get("type")
            if kind not in FIELDS:
                raise ActionError(f"unknown action type {str(kind)[:40]!r}")
            extra = set(raw) - FIELDS[kind] - {"type"}
            if extra:
                raise ActionError(f"{kind}: unknown field(s) {', '.join(sorted(x[:40] for x in extra))}")
            payload, summary = getattr(self, "_v_" + kind)(raw, env)
        except ActionError as e:
            return None, str(e)
        except Exception as e:  # noqa: BLE001 - e.g. Notion lookup failed; never raise to the caller
            return None, f"{raw.get('type')}: {_err(e)}"
        aid = self._exec("INSERT INTO actions (type, payload, summary, status, created) VALUES (?,?,?,'pending',?)",
                         (kind, json.dumps(payload), summary, _now()))[1]
        return {"id": aid, "type": kind, "summary": summary}, None

    def _v_notion_task_update(self, raw, env):
        if ("task" in raw) == ("page_id" in raw):
            raise ActionError("notion_task_update needs exactly one of task or page_id")
        if "done" not in raw and "status" not in raw:
            raise ActionError("notion_task_update needs done and/or status")
        if "done" in raw and not isinstance(raw["done"], bool):
            raise ActionError("done must be true or false")
        status = _str(raw, "status", 50, required=False, oneline=True)
        if "page_id" in raw:
            pid = _nodash(raw["page_id"]) if isinstance(raw["page_id"], str) else ""
            if not NOTION_ID_RE.fullmatch(pid):
                raise ActionError("page_id must be a Notion page id")
            title = ""
        else:
            want = _str(raw, "task", 200, oneline=True)
            # ponytail: first 100 rows of the DB only; paginate if the Email Tasks DB ever grows past that
            res = self.http("POST", f"databases/{env.get('NOTION_EMAIL_TASKS_DB', '')}/query", env, {"page_size": 100})
            hits = [p for p in res.get("results", []) if _page_title(p).strip().casefold() == want.casefold()]
            if len(hits) != 1:
                raise ActionError(f"no Email Tasks page titled {want!r}" if not hits else
                                  f"{len(hits)} Email Tasks pages are titled {want!r}; use page_id")
            pid, title = _nodash(hits[0].get("id")), _page_title(hits[0]).strip()
        payload = {"page_id": pid, "title": title}
        bits = []
        if "done" in raw:
            payload["done"] = raw["done"]
            bits.append("mark done" if raw["done"] else "mark not done")
        if status:
            payload["status"] = status
            bits.append(f"set status to {status!r}")
        return payload, f"Notion: {' and '.join(bits)} on {repr(title) if title else 'page ' + pid[:8]}"

    def _v_calendar_add(self, raw, env):
        title = _str(raw, "title", 200, oneline=True)
        start = _time(raw, "start")
        if ("end" in raw) == ("duration_min" in raw):
            raise ActionError("calendar_add needs exactly one of end or duration_min")
        if "end" in raw:
            end = _time(raw, "end")
        else:
            d = raw["duration_min"]
            if not isinstance(d, int) or isinstance(d, bool) or not 5 <= d <= 1440:
                raise ActionError("duration_min must be a whole number from 5 to 1440")
            end = start + datetime.timedelta(minutes=d)
        if end <= start:
            raise ActionError("end must be after start")
        now = self.now()
        if not now <= start <= now + datetime.timedelta(days=365):
            raise ActionError("start must be within the next 365 days")
        payload = {"title": title, "start": start.strftime(TIME_FMT), "end": end.strftime(TIME_FMT)}
        notes = _str(raw, "notes", 2000, required=False)
        if notes:
            payload["notes"] = notes
        span = f"{start:%a %d %b %H:%M}–{end:%H:%M}" if end.date() == start.date() else \
            f"{start:%a %d %b %H:%M} – {end:%a %d %b %H:%M}"
        return payload, f"Calendar: add {title!r} {span}"

    def _v_email_draft(self, raw, env):
        to = _str(raw, "to", 254, oneline=True)
        if not EMAIL_RE.fullmatch(to):
            raise ActionError("to must be a single email address")
        subject = _str(raw, "subject", 200, oneline=True)
        body = _str(raw, "body", 20000)
        return {"to": to, "subject": subject, "body": body}, f"Draft: email to {to} — {subject!r} (saved, not sent)"

    # ---- decisions
    def _guard(self, aid, status):
        """Atomic pending -> status. -> None on success, else (code, error body)."""
        n = self._exec("UPDATE actions SET status = ?, decided = ? WHERE id = ? AND status = 'pending'",
                       (status, _now(), aid))[0]
        if n:
            return None
        a = self.get(aid)
        return (404, {"error": "unknown action"}) if a is None else \
            (409, {"error": f"action is already {a['status']}", "action": self._public(a)})

    @staticmethod
    def _public(a):
        return {k: a[k] for k in ("id", "type", "summary", "status", "result", "decided")}

    def reject(self, aid):
        bad = self._guard(aid, "rejected")
        return bad or (200, self._public(self.get(aid)))

    def approve(self, aid, env, vault):
        bad = self._guard(aid, "approved")
        if bad:
            return bad
        a = self.get(aid)
        try:
            result, status = getattr(self, "_x_" + a["type"])(a["payload"], env, Path(vault)), "done"
        except Exception as e:  # noqa: BLE001 - every failure is recorded, secret-free
            result, status = _err(e), "failed"
        self._exec("UPDATE actions SET status = ?, result = ? WHERE id = ?", (status, json.dumps(result), aid))
        return 200, self._public(self.get(aid))

    # ---- executors
    def _x_notion_task_update(self, p, env, vault):
        db = env.get("NOTION_EMAIL_TASKS_DB", "")
        page = self.http("GET", f"pages/{p['page_id']}", env)
        parent = page.get("parent") or {}
        if parent.get("type") != "database_id" or _nodash(parent.get("database_id")) != _nodash(db):
            raise ActionError("page is not in the Email Tasks database; nothing changed")
        title = p.get("title") or _page_title(page).strip() or p["page_id"][:8]
        schema = self.http("GET", f"databases/{db}", env).get("properties") or {}
        check = next((n for n, d in schema.items() if d.get("type") == "checkbox"), None)
        # a real Status property, else a select literally named like "status" (never e.g. "Priority Level")
        stat = next((n for n, d in schema.items() if d.get("type") == "status"), None) or \
            next((n for n, d in schema.items() if d.get("type") == "select" and "status" in n.lower()), None)
        stype = schema[stat]["type"] if stat else None
        options = [o.get("name", "") for o in (schema[stat].get(stype) or {}).get("options") or []] if stat else []
        props, want = {}, p.get("status")
        if "done" in p:
            if check:
                props[check] = {"checkbox": p["done"]}
            elif not want and p["done"]:  # no checkbox: fall back to a done-like status option
                want = next((o for o in options if o.lower() in widgets.DONE_NAMES), None)
                if not want:
                    raise ActionError("the database has no checkbox or done-like status to set")
            elif not want:
                raise ActionError("the database has no checkbox property for done")
        if want:
            if not stat:
                raise ActionError("the database has no status or select property")
            match = next((o for o in options if o.casefold() == want.casefold()), None)
            if match is None:
                raise ActionError("status must be one of " + ", ".join(options))
            props[stat] = {stype: {"name": match}}
        self.http("PATCH", f"pages/{p['page_id']}", env, {"properties": props})
        return f"updated {title}"

    def _x_calendar_add(self, p, env, vault):
        line = self.calendar(p["title"], p["start"], p["end"], p.get("notes", ""))
        if not line.startswith("OK"):
            raise ActionError("calendar: " + (line[:120] or "no output from the helper"))
        return f"added {p['title']} {p['start'].replace('T', ' ')}"

    def _x_email_draft(self, p, env, vault):
        if not vault.is_dir():
            raise ActionError("vault folder not found")
        d = vault / "outputs" / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        stem, now = f"{self.now():%Y-%m-%d}-{_slug(p['subject'])}", _now()
        text = (f"---\ntype: email-draft\nto: {json.dumps(p['to'])}\nsubject: {json.dumps(p['subject'])}\n"
                f"created: {now}\n---\n\n{p['body']}\n")
        for n in range(1, 1000):
            f = d / (stem + (f"-{n}" if n > 1 else "") + ".md")
            try:
                with f.open("x") as fh:  # never overwrite
                    fh.write(text)
                break
            except FileExistsError:
                continue
        else:
            raise ActionError("too many drafts with this name")
        return {"path": str(f), "mailto": mailto(p["to"], p["subject"], p["body"])}

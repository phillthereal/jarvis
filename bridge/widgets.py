"""Widget data: inbox (Notion), calendar (osascript), plan, intel. Stdlib only.
Every function returns a JSON-ready dict and never raises; errors are short and secret-free."""
import datetime
import json
import re
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

DONE_NAMES = {"done", "complete", "completed", "closed", "resolved", "sent", "archived", "finished"}
CAL_APP = Path.home() / "Applications" / "KeystoneCalendar.app"  # built by macos/calendar/build.sh


def vault(cfg):
    return Path(cfg.get("vault_path", "~/Claude+Obsidian")).expanduser()


# ---- inbox (Notion) ---------------------------------------------------------------------------
def _notion_query(env):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{env['NOTION_EMAIL_TASKS_DB']}/query",
        data=json.dumps({"page_size": 100}).encode(), method="POST",
        headers={"Authorization": f"Bearer {env['NOTION_TOKEN']}", "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def parse_notion(data):
    """Notion query JSON -> [{title, done, date, url}] with generic property handling."""
    items = []
    for page in data.get("results", []):
        title, done, dates = "", False, {}
        for name, p in page.get("properties", {}).items():
            t = p.get("type")
            if t == "title":
                title = "".join(x.get("plain_text", "") for x in p["title"])
            elif t == "checkbox" and p["checkbox"]:
                done = True
            elif t in ("status", "select") and (p[t] or {}).get("name", "").lower() in DONE_NAMES:
                done = True
            elif t == "date" and p["date"]:
                dates[name.lower()] = (p["date"].get("start") or "")[:10]
        key = next((k for k in dates if "due" in k or "follow" in k), next(iter(dates), None))
        items.append({"title": title or "(untitled)", "done": done, "date": dates.get(key, ""), "url": page.get("url", "")})
    return items


def open_tasks(env):
    """-> list of open items, or a widget-style dict on unconfigured/error."""
    if not env.get("NOTION_TOKEN") or not env.get("NOTION_EMAIL_TASKS_DB"):
        return {"configured": False}
    try:
        return [i for i in parse_notion(_notion_query(env)) if not i["done"]]
    except Exception as e:
        return {"configured": True, "error": type(e).__name__ + (f" {e.code}" if hasattr(e, "code") else "")}


def inbox(env):
    items = open_tasks(env)
    if isinstance(items, dict):
        return items
    return {"configured": True, "open": len(items), "items": items}


# ---- calendar ---------------------------------------------------------------------------------
def parse_jxa(text):
    """Lines 'ISO-UTC<TAB>title' -> [{start:'HH:MM' local, title}] sorted."""
    ev = []
    for line in text.splitlines():
        iso, _, title = line.partition("\t")
        try:
            dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        except ValueError:
            continue
        ev.append({"start": dt.strftime("%H:%M"), "title": title.strip()})
    return sorted(ev, key=lambda e: e["start"])


_CAL = {"t": 0.0, "v": None}


def calendar_today():
    """Cached 10 min (incl. no-permission/unavailable) so the plan panel stays fast."""
    if _CAL["v"] is not None and time.monotonic() - _CAL["t"] < 600:
        return _CAL["v"]
    _CAL["v"], _CAL["t"] = _calendar_fetch(), time.monotonic()
    return _CAL["v"]


def _calendar_fetch():
    if not CAL_APP.exists():
        return {"calendar": "unavailable"}
    with tempfile.NamedTemporaryFile("r", suffix=".txt") as out:
        try:
            subprocess.run(["open", "-W", "-g", "-n", "--stdout", out.name, str(CAL_APP), "--args", "--no-prompt"],
                           capture_output=True, timeout=8)
        except (subprocess.TimeoutExpired, OSError):
            return {"calendar": "unavailable"}
        text = out.read()
    if text.startswith("ERR no-permission"):
        return {"calendar": "no-permission"}
    return {"events": parse_jxa(text)}


# ---- plan / intel -----------------------------------------------------------------------------
def parse_directives(text, n=3):
    out = []
    for l in text.splitlines():
        m = re.match(r"\s*- \[([ xX])\]\s*(.*)", l)
        if m:
            out.append({"done": m.group(1) != " ", "text": m.group(2).strip()})
    return out[:n]


def plan(cfg, env):
    try:
        directives = parse_directives((vault(cfg) / "wiki" / "directives.md").read_text())
    except OSError:
        directives = []
    tasks = open_tasks(env)
    today = datetime.date.today().isoformat()
    follow = [t for t in tasks if t["date"] and t["date"] <= today] if isinstance(tasks, list) else []
    return {"directives": directives, "calendar": calendar_today(), "follow_ups": follow}


LINK_RE = re.compile(r"^\[(.+?)\]\((\S+?)\)(?:\s+[—-]\s+(.*))?$")


def parse_headlines(text, n=5):
    """Bullet lines only (headings skipped) -> [{title, url, source}]; `[t](u) — s` is unpacked, plain text has no url."""
    out = []
    for l in text.splitlines():
        if not l.startswith("- "):
            continue
        body = l[2:].strip()
        m = LINK_RE.match(body)
        out.append({"title": m.group(1), "url": m.group(2), "source": (m.group(3) or "").strip()} if m
                   else {"title": body, "url": "", "source": ""})
    return out[:n]


def intel(cfg):
    files = sorted((vault(cfg) / "outputs" / "intel").glob("????-??-??.md"))
    if not files:
        return {"empty": True}
    f = files[-1]
    return {"date": f.stem, "headlines": parse_headlines(f.read_text()), "path": str(f)}


# ---- weekly review / system -------------------------------------------------------------------
def _recent(vault_dir, sub, days, now):
    cut = now - days * 86400
    return [f for f in (vault_dir / "outputs" / sub).glob("*.md") if f.name != "README.md" and f.stat().st_mtime >= cut]


def night_learned(vault_dir, days=7, today=None):
    """Sum of 'N of M exported cases labelled' over outputs/night-school/YYYY-MM-DD.md of the last `days` days."""
    since = ((today or datetime.date.today()) - datetime.timedelta(days=days)).isoformat()
    total = 0
    for f in (vault_dir / "outputs" / "night-school").glob("????-??-??.md"):
        if f.stem >= since:
            m = re.search(r"^- (\d+) of \d+ exported cases labelled", f.read_text(errors="replace"), re.M)
            total += int(m.group(1)) if m else 0
    return total


def weekly_counts(vault_dir, by_tier, job_rows, days=7, now=None):
    """by_tier: {"T1": n}; job_rows: Jobs.jobs values. Skills run = finished-ok runs in the persisted job list
    (data/jobs.json, newest 50), so a busy week could undercount."""
    now = now or time.time()
    runs = {}
    for j in job_rows:
        if j.get("state") == "done" and (j.get("started") or 0) >= now - days * 86400:
            runs[j["name"]] = runs.get(j["name"], 0) + 1
    return {"asked_by_tier": {f"T{i}": by_tier.get(f"T{i}", 0) for i in range(1, 6)},
            "asked_total": sum(by_tier.values()),
            "skills_run": [{"name": k, "count": v} for k, v in sorted(runs.items(), key=lambda kv: (-kv[1], kv[0]))],
            "briefs": sum(len(_recent(vault_dir, s, days, now)) for s in ("briefs", "plans", "intel")),
            "night_learned": night_learned(vault_dir, days)}


def ollama_models():
    """-> model count, or None when Ollama is unreachable."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            return len(json.load(r).get("models", []))
    except Exception:
        return None


def last_backup(vault_dir):
    """ISO time of the vault's newest git commit, or None."""
    try:
        p = subprocess.run(["git", "-C", str(vault_dir), "log", "-1", "--format=%cI"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() or None if p.returncode == 0 else None


def system_status(cfg, env, health, ollama_up, models, backup):
    return {"ollama": {"up": bool(ollama_up), "models": models or 0}, "last_backup": backup, "jobs": health,
            "keys": {p["name"]: bool(env.get(p.get("key_env", ""))) for p in cfg.get("tier4_providers", [])
                     if p.get("name") in ("groq", "openrouter")}}

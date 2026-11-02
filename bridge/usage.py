import json
import subprocess
import time
from datetime import date, datetime, timezone

from .config import ROOT
from .providers import free_cloud

USAGE_FILE = ROOT / "data" / "usage.json"
_CCUSAGE = {"ts": 0.0, "val": None}
UNKNOWN = {"value": None, "source": "unknown"}


def _read():
    try:
        return json.loads(USAGE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def claude_pro(raw):
    rl = raw.get("rate_limits")
    if not isinstance(rl, dict):
        return {"session_pct": None, "week_pct": None, "resets_at": None, "week_resets_at": None, "source": "unknown"}
    f, s = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    return {"session_pct": f.get("used_percentage"), "week_pct": s.get("used_percentage"),
            "resets_at": _iso(f.get("resets_at")), "week_resets_at": _iso(s.get("resets_at")),
            "source": "statusline", "captured_at": _iso(raw.get("rate_limits_ts"))}


def claude_tokens(now=None):
    """Tokens per model today via ccusage; cached 5 min. Unknown on any failure."""
    now = now or time.time()
    if _CCUSAGE["val"] is not None and now - _CCUSAGE["ts"] < 300:
        return _CCUSAGE["val"]
    today = date.today().strftime("%Y%m%d")
    try:
        p = subprocess.run(["ccusage", "daily", "--json", "--since", today],
                           capture_output=True, text=True, timeout=20)
        days = json.loads(p.stdout)["daily"]
        models = {}
        for d in days:
            for m in d.get("modelBreakdowns", []):
                t = sum(m.get(k, 0) for k in ("inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"))
                models[m["modelName"]] = models.get(m["modelName"], 0) + t
        val = {"models": models, "total": sum(models.values()), "source": "ccusage"}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return {"models": None, "total": None, "source": "unknown"}
    _CCUSAGE.update(ts=now, val=val)
    return val


def _pct(raw, key):
    v = raw.get(key)
    return {"pct": v, "source": "usage.json"} if isinstance(v, (int, float)) else {"pct": None, "source": "unknown"}


def _num(raw, key):
    v = raw.get(key)
    return {"value": v, "source": "usage.json"} if isinstance(v, (int, float)) else dict(UNKNOWN)


def get_usage(cfg=None):
    raw = _read()
    fc = {n: {"remaining": q["remaining"], "source": "rate-limit header"} for n, q in free_cloud.QUOTA.items()}
    for e in (cfg or {}).get("tier4_providers", []):
        fc.setdefault(e["name"], dict(UNKNOWN, remaining=None))
    return {
        "claude_pro": claude_pro(raw),
        "claude_tokens_today": claude_tokens(),
        "jev_usd_month": _num(raw, "jev_usd_month"),  # router fills later
        "ollama_calls_today": _num(raw, "ollama_calls_today"),
        "free_cloud": fc,
        "brightdata": _pct(raw, "brightdata_pct"),
        "apify": _pct(raw, "apify_pct"),
    }

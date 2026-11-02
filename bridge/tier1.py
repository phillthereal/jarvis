"""Tier 1: regex intents -> lookups of Filip's own saved data. No AI. Lookups are injected callables."""
import json
import re
import time

from bridge.config import db_path
from bridge.providers import Answer

INTENTS = [
    ("priorities", re.compile(r"\b(priorit(y|ies)|directives?|what should i (do|focus on)|top ?3)\b", re.I)),
    ("inbox", re.compile(r"\b(inbox|email tasks|any (new )?emails?)\b", re.I)),
    ("usage", re.compile(r"\b(usage|quota|rate limits?)\b", re.I)),
]
VAULT = [
    re.compile(r"\bwhat did (.+?) say\b", re.I),
    re.compile(r"\bsearch (?:my )?(?:vault|notes) for (.+)", re.I),
]


ALLOWED = {"priorities", "inbox", "usage"}


def _shortcuts_file():  # same data dir as night.school.paths
    return db_path().parent / "shortcuts.json"


def _shortcut(text):
    """Night-school shortcuts approved by Filip: [{pattern, lookup}], fullmatch on the normalised text."""
    from bridge.log import normalise  # late: bridge.log imports nothing from here, but keep tier1 import-light
    try:
        entries = json.loads(_shortcuts_file().read_text())
    except (OSError, ValueError):
        return None
    norm = normalise(text)
    for e in entries if isinstance(entries, list) else []:
        try:
            if isinstance(e, dict) and e.get("lookup") in ALLOWED and re.fullmatch(e["pattern"], norm):
                return e["lookup"]
        except (re.error, TypeError, KeyError):
            continue
    return None


def match(text):
    """Lookup key (`priorities`, `inbox`, `usage`, `vault_search:<term>`) or None."""
    text = text or ""
    if (hit := _shortcut(text)):
        return hit
    for rx in VAULT:
        m = rx.search(text)
        if m and m.group(1).strip(" ?.!\"'"):
            return "vault_search:" + m.group(1).strip(" ?.!\"'")
    for key, rx in INTENTS:
        if rx.search(text):
            return key
    return None


def _format(result):
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return "\n".join(f"{k}: {v}" for k, v in result.items())
    if isinstance(result, (list, tuple)):
        return "\n".join(f"- {_format(x) if isinstance(x, (dict, list)) else x}".replace("\n", "; ") for x in result)
    return str(result)


def answer(key, lookups):
    """Run the lookup for `key`. lookups: {"priorities": fn(), ..., "vault_search": fn(term)}. Never raises."""
    t = time.perf_counter()
    name, _, term = key.partition(":")
    fn = lookups.get(name)
    try:
        if fn is None:
            raise LookupError(f"no lookup for {name}")
        result = fn(term) if term else fn()
        text = _format(result).strip() if result is not None else ""
        if not text:
            text = "Nothing found." if result is not None else ""
        ok, err = bool(text), (None if text else "empty lookup")
    except Exception as exc:  # noqa: BLE001 - a broken lookup means "fall through", not a crash
        text, ok, err = "", False, f"lookup failed: {type(exc).__name__}"
    return Answer(text, "tier1", name, ok, err, int((time.perf_counter() - t) * 1000))

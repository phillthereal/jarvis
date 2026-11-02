#!/usr/bin/env python3
"""Fetch RSS/Atom feeds, dedupe, keep last 24h, write outputs/intel/YYYY-MM-DD.md in the vault. Stdlib only.
Bright Data (Anthropic news) and Apify (Reddit) cover feed-less sources within free allowances."""
import datetime
import json
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bridge.config import load_env  # noqa: E402

SOURCES = [
    ("Hacker News", "https://hnrss.org/frontpage"),
    ("arXiv cs.AI", "https://rss.arxiv.org/rss/cs.AI"),
    ("arXiv cs.CL", "https://rss.arxiv.org/rss/cs.CL"),
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
]
GENERAL = {"Hacker News"}  # feeds that need the AI keyword filter; lab/arXiv feeds are kept whole
AI_RE = re.compile(r"\b(AI|LLMs?|GPT\S*|Claude|Anthropic|OpenAI|models?|agents?|neural|machine learning|transformers?|"
                   r"inference|Gemini|Llama|Qwen|DeepSeek|Mistral)\b", re.I)
BD_CAP = 4000  # 80% of the 5,000 free requests
BD_FREE = 5000
APIFY_CAP_USD = 4.0  # 80% of the $5 free credit
APIFY_ACTOR = "trudax~reddit-scraper-lite"  # PAY_PER_EVENT: $0.02 start + $0.004/result (FREE tier)
APIFY_RUN_USD = 0.02 + 0.004 * 10  # worst case at maxItems 10
USAGE = ROOT / "data" / "usage.json"
ANTHROPIC_NEWS = "https://www.anthropic.com/news"
PER_SOURCE, TOTAL = 5, 15
ATOM = "{http://www.w3.org/2005/Atom}"


def _text(el, *names):
    for n in names:
        c = el.find(n)
        if c is not None and (c.text or "").strip():
            return c.text.strip()
    return ""


def _date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def parse_feed(xml_text, source):
    """RSS 2.0 or Atom -> [{title, url, date (aware datetime or None), source}]."""
    root = ET.fromstring(xml_text)
    out = []
    for it in list(root.iter("item")) + list(root.iter(ATOM + "entry")):
        title = " ".join(_text(it, "title", ATOM + "title").split())
        url = _text(it, "link")
        if not url:  # Atom: <link href=...>
            for l in it.findall(ATOM + "link"):
                if l.get("rel", "alternate") == "alternate":
                    url = l.get("href", "")
                    break
        date = _date(_text(it, "pubDate", ATOM + "published", ATOM + "updated"))
        if title and url:
            out.append({"title": title, "url": url, "date": date, "source": source})
    return out


def ai_only(items):
    return [i for i in items if i["source"] not in GENERAL or AI_RE.search(i["title"])]


def select(items, now, hours=24):
    """Dedupe by URL/title, keep last 24h (undated items are kept), newest first, capped per source and in total."""
    cutoff = now - datetime.timedelta(hours=hours)
    seen, kept, per = set(), [], {}
    floor = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    for i in sorted(items, key=lambda i: i["date"] or now, reverse=True):
        key = (i["url"].rstrip("/"), i["title"].lower())
        if i["date"] and i["date"] < cutoff or key[0] in seen or key[1] in seen:
            continue
        if per.get(i["source"], 0) >= PER_SOURCE:
            continue
        seen.update(key)
        per[i["source"]] = per.get(i["source"], 0) + 1
        kept.append(i)
    return kept[:TOTAL]


def brightdata_fetch(url, env, usage_path, now=None):
    """Fallback for a source with no feed. Returns body text, or None if skipped (no key / cap reached / error)."""
    key, zone = env.get("BRIGHTDATA_API_KEY"), env.get("WEB_UNLOCKER_ZONE")
    if not key or not zone:
        return None
    month = (now or datetime.date.today()).strftime("%Y-%m")
    usage_path = Path(usage_path)
    try:
        usage = json.loads(usage_path.read_text())
    except (OSError, ValueError):
        usage = {}
    bd = usage.get("brightdata_month") or {}
    if bd.get("month") != month:
        bd = {"month": month, "calls": 0}
    if bd["calls"] >= BD_CAP:
        return None
    bd["calls"] += 1  # count before the call: failed calls still cost quota
    bd["pct"] = round(bd["calls"] / BD_FREE * 100, 2)
    usage["brightdata_month"] = bd
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(json.dumps(usage))
    req = urllib.request.Request(
        "https://api.brightdata.com/request",
        data=json.dumps({"zone": zone, "url": url, "format": "raw"}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


class _NewsParser(HTMLParser):
    """Anthropic /news tiles: <article> holds <time> and <a href><h2|h3>title</h2|h3></a>."""

    def __init__(self):
        super().__init__()
        self.items, self.cur, self.href, self.field = [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "article":
            self.cur = {"title": "", "url": "", "dt": ""}
        elif self.cur is not None:
            if tag == "a" and a.get("href"):
                self.href = a["href"]
            elif tag in ("h2", "h3", "h4") and self.href and not self.cur["title"]:
                self.field, self.cur["url"] = "title", self.href
            elif tag == "time" and not self.cur["dt"]:
                self.field = "dt"

    def handle_data(self, data):
        if self.field and self.cur is not None:
            self.cur[self.field] += data

    def handle_endtag(self, tag):
        if tag in ("h2", "h3", "h4", "time"):
            self.field = None
        elif tag == "a":
            self.href = None
        elif tag == "article" and self.cur is not None:
            c, self.cur = self.cur, None
            if c["title"].strip() and c["url"]:
                self.items.append(c)


def parse_anthropic_news(html, source="Anthropic news", limit=5):
    """HTML -> newest <=5 [{title, url, date (aware datetime or None), source}]."""
    p = _NewsParser()
    p.feed(html)
    out = []
    for c in p.items:
        try:
            d = datetime.datetime.strptime(" ".join(c["dt"].split()), "%b %d, %Y").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            d = None
        out.append({"title": " ".join(c["title"].split()), "url": urllib.parse.urljoin(ANTHROPIC_NEWS, c["url"]),
                    "date": d, "source": source})
    floor = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    return sorted(out, key=lambda i: i["date"] or floor, reverse=True)[:limit]


def apify_fetch(env, usage_path, today=None, source="r/LocalLLaMA (Apify)"):
    """Optional: top r/LocalLLaMA posts of the day via one Apify run. Skips silently with no token, when already run
    today, or once estimated spend >= APIFY_CAP_USD. Returns [] on any skip/error."""
    token = env.get("APIFY_TOKEN")
    if not token:
        return []
    today = today or datetime.date.today()
    usage_path = Path(usage_path)
    try:
        usage = json.loads(usage_path.read_text())
    except (OSError, ValueError):
        usage = {}
    ap = usage.get("apify_month") or {}
    if ap.get("month") != today.strftime("%Y-%m"):
        ap = {"month": today.strftime("%Y-%m"), "calls": 0, "est_usd": 0.0}
    if ap.get("last_run") == today.isoformat() or ap["est_usd"] >= APIFY_CAP_USD:
        return []
    ap["calls"] += 1  # count before the call: failed runs may still cost
    ap["est_usd"] = round(ap["est_usd"] + APIFY_RUN_USD, 4)
    ap["last_run"] = today.isoformat()
    ap["pct"] = round(ap["est_usd"] / 5 * 100, 2)
    usage["apify_month"] = ap
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(json.dumps(usage))
    req = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?timeout=60&format=json",
        data=json.dumps({"startUrls": [{"url": "https://www.reddit.com/r/LocalLLaMA/top/?t=day"}], "maxItems": 10,
                         "maxPostCount": 10, "skipComments": True}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("dataType", "post") != "post":
            continue
        title, url = " ".join(str(row.get("title", "")).split()), row.get("url", "")
        if title and url:
            out.append({"title": title, "url": url, "date": _date(row.get("createdAt")), "source": source})
    return out[:PER_SOURCE]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "agentic-os/1.0", "Accept-Encoding": "identity"})
    for attempt in (1, 2):  # one retry: feeds are occasionally flaky
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 2:
                raise


def render(items, today, failed):
    lines = ["---", "type: intel", "source: rss", f"created: {today}", "---", "", f"# Morning intel {today}", "",
             "## Headlines", ""]
    lines += [f"- [{i['title'].replace(']', ')').replace('[', '(')}]({i['url']}) — {i['source']}" for i in items]
    if not items:
        lines.append("- (no new items in the last 24h)")
    if failed:
        lines += ["", f"Feeds unavailable: {', '.join(failed)}"]
    return "\n".join(lines) + "\n"


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    vault = Path(cfg.get("vault_path", "~/Claude+Obsidian")).expanduser()
    now = datetime.datetime.now(datetime.timezone.utc)
    items, failed = [], []
    for name, url in SOURCES:
        try:
            items += parse_feed(fetch(url), name)
        except Exception:
            failed.append(name)
    env = load_env()
    body = brightdata_fetch(ANTHROPIC_NEWS, env, USAGE)  # exactly 1 request per run
    if body:
        items += parse_anthropic_news(body)
    elif env.get("BRIGHTDATA_API_KEY"):
        failed.append("Anthropic news")
    items += apify_fetch(env, USAGE)
    chosen = select(ai_only(items), now)
    today = datetime.date.today().isoformat()
    out = vault / "outputs" / "intel" / f"{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(chosen, today, failed))
    print(out)


if __name__ == "__main__":
    main()

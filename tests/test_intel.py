import datetime
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_intel as fi  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
RSS = """<rss><channel>
<item><title>Fresh  one</title><link>https://a/1</link><pubDate>Sun, 01 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>Old</title><link>https://a/2</link><pubDate>Fri, 30 Oct 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""
ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom post</title><link rel="alternate" href="https://b/1"/><updated>2026-11-01T09:00:00Z</updated></entry>
</feed>"""

NEWS = """<main><article><header><time>Oct 26, 2026</time></header><a href="/news/s1"><h3>S-1 filed</h3><p>x</p></a></article>
<article><header><time>Oct 7, 2026</time></header><a href="/claude-haiku"><h3>Haiku  out</h3></a></article>
<article><header>no link</header></article></main>"""


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class T(unittest.TestCase):
    def test_ai_filter_only_on_general_feeds(self):
        mk = lambda t, s: {"title": t, "url": "u", "date": None, "source": s}
        items = [mk("Show HN: a tiny database", "Hacker News"), mk("Claude gets faster", "Hacker News"),
                 mk("Training transformers", "Hacker News"), mk("Retail results", "Hacker News"),
                 mk("Sampling paper", "arXiv cs.AI")]
        self.assertEqual([i["title"] for i in fi.ai_only(items)],
                         ["Claude gets faster", "Training transformers", "Sampling paper"])

    def test_parse_rss_and_atom(self):
        r = fi.parse_feed(RSS, "A")
        self.assertEqual([i["title"] for i in r], ["Fresh one", "Old"])
        a = fi.parse_feed(ATOM, "B")
        self.assertEqual((a[0]["url"], a[0]["date"].hour), ("https://b/1", 9))

    def test_24h_filter_and_dedupe(self):
        items = fi.parse_feed(RSS, "A") + fi.parse_feed(ATOM, "B") + fi.parse_feed(RSS, "C")
        got = fi.select(items, NOW)
        self.assertEqual(sorted(i["title"] for i in got), ["Atom post", "Fresh one"])

    def test_brightdata_cap_and_no_key(self):
        with tempfile.TemporaryDirectory() as d:
            u = Path(d) / "usage.json"
            env = {"BRIGHTDATA_API_KEY": "k", "WEB_UNLOCKER_ZONE": "z"}
            u.write_text(json.dumps({"brightdata_month": {"month": "2026-11", "calls": 4000}}))
            self.assertIsNone(fi.brightdata_fetch("https://x", env, u, datetime.date(2026, 11, 1)))
            self.assertEqual(json.loads(u.read_text())["brightdata_month"]["calls"], 4000)
            self.assertIsNone(fi.brightdata_fetch("https://x", {}, u, datetime.date(2026, 11, 1)))

    def test_parse_anthropic_news(self):
        r = fi.parse_anthropic_news(NEWS)
        self.assertEqual([(i["title"], i["url"], i["date"].day) for i in r],
                         [("S-1 filed", "https://www.anthropic.com/news/s1", 26),
                          ("Haiku out", "https://www.anthropic.com/claude-haiku", 7)])

    def test_brightdata_called_once_and_pct_written(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fi.urllib.request, "urlopen", return_value=Resp(NEWS)) as m:
            u = Path(d) / "usage.json"
            body = fi.brightdata_fetch(fi.ANTHROPIC_NEWS, {"BRIGHTDATA_API_KEY": "k", "WEB_UNLOCKER_ZONE": "z"}, u,
                                       datetime.date(2026, 11, 1))
            self.assertEqual((body, m.call_count), (NEWS, 1))
            bd = json.loads(u.read_text())["brightdata_month"]
            self.assertEqual((bd["calls"], bd["pct"]), (1, 0.02))

    def test_apify_skipped_without_token(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fi.urllib.request, "urlopen") as m:
            u = Path(d) / "usage.json"
            self.assertEqual(fi.apify_fetch({"APIFY_TOKEN": ""}, u), [])
            self.assertEqual(fi.apify_fetch({}, u), [])
            m.assert_not_called()
            self.assertFalse(u.exists())

    def test_apify_run_pct_and_daily_limit(self):
        rows = json.dumps([{"dataType": "post", "title": "T1", "url": "https://r/1", "createdAt": "2026-11-01T08:00:00.000Z"},
                           {"dataType": "comment", "title": "c", "url": "https://r/2"}])
        day = datetime.date(2026, 11, 1)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fi.urllib.request, "urlopen", return_value=Resp(rows)) as m:
            u = Path(d) / "usage.json"
            got = fi.apify_fetch({"APIFY_TOKEN": "t"}, u, day)
            self.assertEqual([i["title"] for i in got], ["T1"])
            ap = json.loads(u.read_text())["apify_month"]
            self.assertEqual((ap["calls"], ap["est_usd"], ap["pct"]), (1, 0.06, 1.2))
            self.assertEqual(fi.apify_fetch({"APIFY_TOKEN": "t"}, u, day), [])  # 1 run per day
            self.assertEqual(m.call_count, 1)

    def test_apify_cap_refusal(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fi.urllib.request, "urlopen") as m:
            u = Path(d) / "usage.json"
            u.write_text(json.dumps({"apify_month": {"month": "2026-11", "calls": 60, "est_usd": 4.0}}))
            self.assertEqual(fi.apify_fetch({"APIFY_TOKEN": "t"}, u, datetime.date(2026, 11, 2)), [])
            m.assert_not_called()
            self.assertEqual(json.loads(u.read_text())["apify_month"]["calls"], 60)


if __name__ == "__main__":
    unittest.main()

import io
import json
import subprocess
import urllib.error
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

from bridge import usage
from bridge.providers import free_cloud
from bridge.providers.claude_cli import ClaudeCliProvider
from bridge.providers.free_cloud import FreeCloudProvider
from bridge.providers.ollama import OllamaProvider
from bridge.providers.paid import PaidProvider


def resp(body, headers=None, status=200):
    r = MagicMock()
    r.status = status
    r.read.return_value = body if isinstance(body, bytes) else json.dumps(body).encode()
    r.headers = headers or {}
    r.__enter__.return_value = r
    return r


def http_err(code, body=b"{}", headers=None):
    return urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(body))


OLLAMA_OK = {"message": {"content": " hi "}}
CHAT_OK = {"choices": [{"message": {"content": "yo"}}]}
UO = "urllib.request.urlopen"


class OllamaTests(TestCase):
    def test_happy_and_payload(self):
        with patch(UO, return_value=resp(OLLAMA_OK)) as m:
            a = OllamaProvider("m").complete("p", system="s")
        self.assertTrue(a.ok)
        self.assertEqual(a.text, "hi")
        body = json.loads(m.call_args[0][0].data)
        self.assertIs(body["think"], False)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["keep_alive"], "5m")

    def test_timeout(self):
        with patch(UO, side_effect=TimeoutError("timed out")):
            a = OllamaProvider("m").complete("p")
        self.assertEqual((a.ok, a.error), (False, "timeout"))

    def test_malformed(self):
        with patch(UO, return_value=resp(b"not json")):
            self.assertEqual(OllamaProvider("m").complete("p").error, "bad_response")

    def test_fallback_on_not_found(self):
        with patch(UO, side_effect=[http_err(404, b'{"error":"model not found"}'), resp(OLLAMA_OK)]):
            a = OllamaProvider("m", fallback="f").complete("p")
        self.assertTrue(a.ok)
        self.assertEqual(a.model, "f")

    def test_no_fallback_fails(self):
        with patch(UO, side_effect=http_err(404)):
            self.assertFalse(OllamaProvider("m").complete("p").ok)

    def test_up(self):
        with patch(UO, return_value=resp(b"{}")):
            self.assertTrue(OllamaProvider("m").up())
        with patch(UO, side_effect=OSError):
            self.assertFalse(OllamaProvider("m").up())


def proc(out, rc=0, err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class ClaudeCliTests(TestCase):
    def run_p(self, **kw):
        with patch("subprocess.run", **kw) as m:
            a = ClaudeCliProvider("haiku", cwd="~").complete("p", system="s", timeout=5)
        return a, m

    def test_happy(self):
        a, m = self.run_p(return_value=proc(json.dumps({"result": " ok ", "is_error": False})))
        self.assertEqual((a.ok, a.text), (True, "ok"))
        cmd = m.call_args[0][0]
        self.assertIn("--append-system-prompt", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep,Glob")
        self.assertIn("--strict-mcp-config", cmd)  # no Gmail/Drive connectors
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "default")  # never auto-approve
        self.assertNotIn("~", m.call_args[1]["cwd"])

    def test_timeout(self):
        a, _ = self.run_p(side_effect=subprocess.TimeoutExpired("claude", 5))
        self.assertEqual(a.error, "timeout")

    def test_missing_cli(self):
        a, _ = self.run_p(side_effect=FileNotFoundError)
        self.assertEqual(a.error, "cli_unavailable")

    def test_pro_limit(self):
        out = json.dumps({"result": "Claude AI usage limit reached|1700000000", "is_error": True})
        a, _ = self.run_p(return_value=proc(out, 1))
        self.assertEqual((a.ok, a.error), (False, "pro_limit"))

    def test_pro_limit_in_stderr(self):
        a, _ = self.run_p(return_value=proc("", 1, "5-hour limit reached"))
        self.assertEqual(a.error, "pro_limit")

    def test_malformed(self):
        a, _ = self.run_p(return_value=proc("garbage"))
        self.assertEqual(a.error, "bad_response")


ENTRIES = [{"name": "groq", "base_url": "https://g/v1", "model": "gm", "key_env": "G"},
           {"name": "openrouter", "base_url": "https://o/v1", "model": "om", "key_env": "O"}]


class FreeCloudTests(TestCase):
    def setUp(self):
        free_cloud.QUOTA.clear()

    def test_happy_records_quota(self):
        with patch(UO, return_value=resp(CHAT_OK, {"x-ratelimit-remaining-requests": "99"})) as m:
            a = FreeCloudProvider(ENTRIES, {"G": "k", "O": "k"}).complete("p")
        self.assertEqual((a.ok, a.provider, a.text), (True, "groq", "yo"))
        self.assertEqual(free_cloud.QUOTA["groq"]["remaining"], "99")
        self.assertEqual(m.call_count, 1)

    def test_429_goes_to_next(self):
        with patch(UO, side_effect=[http_err(429, headers={"x-ratelimit-remaining-requests": "0"}), resp(CHAT_OK)]):
            a = FreeCloudProvider(ENTRIES, {"G": "k", "O": "k"}).complete("p")
        self.assertEqual(a.provider, "openrouter")
        self.assertEqual(free_cloud.QUOTA["groq"]["remaining"], "0")

    def test_5xx_and_timeout_then_fail(self):
        with patch(UO, side_effect=[http_err(503), TimeoutError("timed out")]):
            a = FreeCloudProvider(ENTRIES, {"G": "k", "O": "k"}).complete("p")
        self.assertEqual((a.ok, a.error), (False, "openrouter:timeout"))

    def test_missing_key_skipped(self):
        with patch(UO, return_value=resp(CHAT_OK)) as m:
            a = FreeCloudProvider(ENTRIES, {"G": "", "O": "k"}).complete("p")
        self.assertEqual(a.provider, "openrouter")
        self.assertEqual(m.call_count, 1)

    def test_no_keys(self):
        with patch(UO) as m:
            a = FreeCloudProvider(ENTRIES, {}).complete("p")
        self.assertEqual(a.error, "no_key")
        m.assert_not_called()

    def test_malformed_json_next(self):
        with patch(UO, side_effect=[resp(b"nope"), resp(CHAT_OK)]):
            a = FreeCloudProvider(ENTRIES, {"G": "k", "O": "k"}).complete("p")
        self.assertEqual(a.provider, "openrouter")

    def test_error_has_no_secret(self):
        with patch(UO, side_effect=http_err(401)):
            a = FreeCloudProvider(ENTRIES, {"G": "SECRET", "O": "SECRET"}).complete("p")
        self.assertNotIn("SECRET", a.error)


class PaidTests(TestCase):
    def test_disabled_and_unconfigured(self):
        self.assertEqual(PaidProvider({"paid_enabled": False}).complete("p").error, "paid_disabled")
        a = PaidProvider({"paid_enabled": True}).complete("p")
        self.assertEqual((a.ok, a.error), (False, "not configured"))


CCU = {"daily": [{"modelBreakdowns": [
    {"modelName": "claude-opus-5-5", "inputTokens": 1, "outputTokens": 2, "cacheCreationTokens": 3, "cacheReadTokens": 4},
    {"modelName": "claude-haiku-5-5", "inputTokens": 5, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0}]}]}


class UsageTests(TestCase):
    def setUp(self):
        usage._CCUSAGE.update(ts=0.0, val=None)
        free_cloud.QUOTA.clear()

    def test_ccusage_parse_and_cache(self):
        with patch("subprocess.run", return_value=proc(json.dumps(CCU))) as m:
            v = usage.claude_tokens()
            usage.claude_tokens()
        self.assertEqual(v["models"], {"claude-opus-5-5": 10, "claude-haiku-5-5": 5})
        self.assertEqual(v["total"], 15)
        self.assertEqual(m.call_count, 1)

    def test_ccusage_failure_unknown(self):
        for kw in ({"side_effect": FileNotFoundError}, {"return_value": proc("junk")},
                   {"side_effect": subprocess.TimeoutExpired("ccusage", 20)}):
            with patch("subprocess.run", **kw):
                self.assertEqual(usage.claude_tokens()["source"], "unknown")

    def test_unknown_path(self):
        with patch.object(usage, "_read", return_value={}), patch.object(usage, "claude_tokens",
                                                                          return_value={"source": "unknown"}):
            u = usage.get_usage({"tier4_providers": ENTRIES})
        self.assertEqual(u["claude_pro"]["source"], "unknown")
        self.assertIsNone(u["claude_pro"]["session_pct"])
        self.assertEqual(u["jev_usd_month"], {"value": None, "source": "unknown"})
        self.assertEqual(u["free_cloud"]["groq"]["source"], "unknown")
        self.assertEqual(u["brightdata"]["source"], "unknown")

    def test_known_values(self):
        raw = {"rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": 1800000000},
                               "seven_day": {"used_percentage": 7, "resets_at": 1800500000}},
               "brightdata_pct": 12, "jev_usd_month": 0.3}
        free_cloud.QUOTA["groq"] = {"remaining": "5", "ts": 1}
        with patch.object(usage, "_read", return_value=raw), patch.object(usage, "claude_tokens",
                                                                           return_value={"source": "ccusage"}):
            u = usage.get_usage({})
        self.assertEqual((u["claude_pro"]["session_pct"], u["claude_pro"]["week_pct"]), (42, 7))
        self.assertEqual(u["claude_pro"]["source"], "statusline")
        self.assertEqual(u["brightdata"]["pct"], 12)
        self.assertEqual(u["jev_usd_month"]["value"], 0.3)
        self.assertEqual(u["free_cloud"]["groq"]["remaining"], "5")


if __name__ == "__main__":
    main()

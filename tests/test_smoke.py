import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from bridge.config import load_config, load_env
from bridge.providers import Answer
from bridge.server import make_server


class ConfigTests(unittest.TestCase):
    def test_config_loads_defaults(self):
        cfg = load_config()
        self.assertEqual(cfg["port"], 8777)
        self.assertEqual(cfg["cascade"], ["T2", "T4", "T3"])
        self.assertFalse(cfg["paid_enabled"])

    def test_env_parser_handles_comments_blank_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# comment\n\nA=1\nB = two \nC=\"quoted\"\nnoequals\n")
            env = load_env(p)
            self.assertEqual(env, {"A": "1", "B": "two", "C": "quoted"})
            self.assertEqual(load_env(Path(d) / "missing.env"), {})


class AnswerTests(unittest.TestCase):
    def test_answer_constructs(self):
        a = Answer(text="hi", provider="ollama", model="m", ok=True, error=None, latency_ms=5)
        self.assertTrue(a.ok)
        self.assertIsNone(a.error)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_index_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Keystone", body)

    def test_unknown_path_404(self):
        status, _ = self.get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

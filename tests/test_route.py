import json
import os
import tempfile
import unittest
from pathlib import Path

from bridge import tier1
from bridge.config import load_config
from bridge.log import Log, normalise
from bridge.providers import Answer
from bridge.route import Router, parse_verdict


class FakeProvider:
    def __init__(self, name, ok=True, error=None, text=None):
        self.name, self.ok, self.error, self.text, self.calls = name, ok, error, text, 0

    def complete(self, prompt, system=None, timeout=60):
        self.calls += 1
        return Answer(self.text or f"{self.name} says hi", self.name, f"{self.name}-model", self.ok,
                      None if self.ok else (self.error or "boom"), 3)


class FakeChecker:
    def __init__(self, verdicts):
        self.verdicts, self.prompts = list(verdicts), []

    def complete(self, prompt, system=None, timeout=60):
        self.prompts.append(prompt)
        return Answer(self.verdicts.pop(0) if self.verdicts else "PASS", "ollama", "check", True, None, 1)


class FakeJev:
    def __init__(self, choice=None, p=0.0, usd=0.0001):
        self.out, self.calls = (choice, p, usd), 0

    def decide(self, text):
        self.calls += 1
        return self.out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "r.db")
        self.cfg = load_config()
        self.p = {t: FakeProvider(t) for t in ("T2", "T3", "T4", "T5")}
        self.usage = {"session_pct": 10}
        self.lookups = {"priorities": lambda: ["ship bridge", "renew passport"], "usage": lambda: [],
                        "vault_search": lambda term: f"found {term}"}

    def tearDown(self):
        self.tmp.cleanup()

    def router(self, jev=None, checker=None, **cfg):
        self.cfg.update(cfg)
        self.checker = checker or FakeChecker([])
        self.jev = jev or FakeJev()
        return Router(self.cfg, self.p, self.checker, self.jev, self.lookups, lambda: self.usage, self.log)

    def tiers(self, out):
        return [s["tier"] for s in out["path"]]


class ForceModes(Base):
    def test_force_tier_skips_cache_tier1_jev(self):
        out = self.router().ask("my priorities?", mode="tier", tier="T3")
        self.assertEqual((out["final_tier"], self.jev.calls), ("T3", 0))
        self.assertIsNone(out["path"][0]["check"])

    def test_force_model_picks_tier(self):
        self.assertEqual(self.router().ask("hi", mode="model", model="sonnet")["final_tier"], "T3")
        self.assertEqual(self.router().ask("hi", mode="model", model="qwen3.5:9b")["final_tier"], "T2")
        self.assertEqual(self.router().ask("hi", mode="model", model="llama-3.3-70b-versatile")["final_tier"], "T4")

    def test_force_model_uses_factory(self):
        r = self.router()
        special = FakeProvider("special")
        r.model_factory = lambda m: ("T3", special)
        out = r.ask("hi", mode="model", model="opus")
        self.assertEqual((out["provider"], special.calls), ("special", 1))


class RepeatCache(Base):
    def test_hit_on_confirmed_and_miss_otherwise(self):
        rid = self.log.insert(text="Explain  Monads?", mode="auto", final_tier="T3", path=[])
        r = self.router(jev=FakeJev("T2", 0.99))
        self.assertEqual(r.ask("explain monads")["final_tier"], "T2")  # not confirmed yet -> Jev
        self.log.set_feedback(rid, "up")
        out = r.ask("explain monads")
        self.assertEqual((out["final_tier"], self.jev.calls), ("T3", 1))  # cache hit, Jev not called again

    def test_night_label_confirms_and_wins(self):
        rid = self.log.insert(text="explain monads", mode="auto", final_tier="T3", path=[])
        self.log.set_night_label(rid, "T2")
        self.assertEqual(self.log.recent_confirmed(normalise("Explain monads!")), "T2")
        self.assertIsNone(self.log.recent_confirmed("something else"))


class Tier1(Base):
    def test_match_keys(self):
        self.assertEqual(tier1.match("what are my priorities today"), "priorities")
        self.assertEqual(tier1.match("anything in my inbox"), "inbox")
        self.assertEqual(tier1.match("show my usage"), "usage")
        self.assertEqual(tier1.match("what did Sarah say about the offer?"), "vault_search:Sarah")
        self.assertIsNone(tier1.match("write me a haiku"))

    def test_lookup_answers_without_jev(self):
        out = self.router().ask("what are my priorities")
        self.assertEqual((out["final_tier"], out["answer"], self.jev.calls),
                         ("T1", "- ship bridge\n- renew passport", 0))
        self.assertIn("found Sarah", self.router().ask("what did Sarah say")["answer"])
        self.assertEqual(self.router().ask("show my usage")["answer"], "Nothing found.")

    def test_missing_lookup_falls_through(self):
        out = self.router(jev=FakeJev("T2", 0.95)).ask("check my inbox")  # no inbox lookup wired
        self.assertEqual(out["final_tier"], "T2")
        self.assertFalse(out["path"][0]["ok"])


class JevAndCascade(Base):
    def test_jev_sure_routes_without_check(self):
        out = self.router(jev=FakeJev("T3", 0.95)).ask("plan my week")
        self.assertEqual((self.tiers(out), out["path"][0]["check"]), (["T3"], None))
        self.assertEqual((out["jev_choice"], out["jev_p"]), ("T3", 0.95))

    def test_jev_unsure_cascades_in_config_order(self):
        ch = FakeChecker(["FAIL: vague", "FAIL: wrong", "PASS"])
        out = self.router(jev=FakeJev("T3", 0.5), checker=ch).ask("explain x")
        self.assertEqual(self.tiers(out), ["T2", "T4", "T3"])
        self.assertEqual(out["final_tier"], "T3")
        out = self.router(jev=FakeJev("T2", 0.5), checker=FakeChecker(["FAIL: no", "PASS"]),
                          cascade=["T4", "T2", "T3"]).ask("explain y")
        self.assertEqual(self.tiers(out), ["T4", "T2"])

    def test_pass_stops_cascade(self):
        out = self.router(checker=FakeChecker(["PASS"])).ask("explain x")
        self.assertEqual((self.tiers(out), out["path"][0]["check"]), (["T2"], "PASS"))
        self.assertEqual(self.p["T4"].calls, 0)

    def test_error_moves_to_next(self):
        self.p["T2"] = FakeProvider("T2", ok=False, error="ollama down")
        out = self.router(checker=FakeChecker(["PASS"])).ask("explain x")
        self.assertEqual((self.tiers(out), out["final_tier"]), (["T2", "T4"], "T4"))
        self.assertIsNone(out["path"][0]["check"])  # no check on an error

    def test_malformed_verdict_is_fail(self):
        for bad in ["pass", "Looks good! PASS", "FAIL", "FAIL:", "", "PASS\nbecause"]:
            self.assertTrue(parse_verdict(bad).startswith("FAIL"), bad)
        self.assertEqual(parse_verdict("<think>hmm</think>\nPASS"), "PASS")
        out = self.router(checker=FakeChecker(["yes PASS", "PASS"])).ask("explain x")
        self.assertEqual(out["path"][0]["check"], "FAIL: malformed verdict")
        self.assertEqual(out["final_tier"], "T4")

    def test_jev_error_is_unsure(self):
        out = self.router(jev=FakeJev(None, 0.0, 0.0), checker=FakeChecker(["PASS"])).ask("explain x")
        self.assertEqual(self.tiers(out), ["T2"])
        self.assertEqual(out["path"][0]["check"], "PASS")

    def test_all_checks_fail_returns_strongest_answer(self):
        out = self.router(checker=FakeChecker(["FAIL: a", "FAIL: b", "FAIL: c"])).ask("explain x")
        self.assertEqual((out["ok"], out["final_tier"]), (True, "T3"))


class Guards(Base):
    def test_high_stakes_skips_jev_and_cascade(self):
        out = self.router(jev=FakeJev("T2", 0.99)).ask("review this contract clause")
        self.assertEqual((self.tiers(out), self.jev.calls), (["T3"], 0))

    def test_pro_spill_by_usage(self):
        self.usage = {"session_pct": 85}
        out = self.router(jev=FakeJev("T3", 0.99)).ask("plan my week")
        self.assertEqual(out["final_tier"], "T4")
        self.assertEqual(self.p["T3"].calls, 0)

    def test_unknown_usage_does_not_spill(self):
        self.usage = {"source": "unknown"}
        self.assertEqual(self.router(jev=FakeJev("T3", 0.99)).ask("plan my week")["final_tier"], "T3")

    def test_pro_spill_by_pro_limit_error(self):
        self.p["T3"] = FakeProvider("T3", ok=False, error="pro_limit")
        out = self.router(jev=FakeJev("T3", 0.99)).ask("plan my week")
        self.assertEqual((self.tiers(out), out["final_tier"]), (["T3", "T4"], "T4"))

    def test_privacy_skips_t4(self):
        ch = FakeChecker(["FAIL: thin", "PASS"])
        out = self.router(checker=ch).ask("summarise my salary history")
        self.assertEqual(self.tiers(out), ["T2", "T4", "T3"])
        self.assertEqual((out["path"][1]["error"], self.p["T4"].calls), ("skipped: private request", 0))
        self.assertEqual(out["final_tier"], "T3")

    def test_privacy_beats_spill(self):
        self.usage = {"session_pct": 99}
        out = self.router(jev=FakeJev("T3", 0.99)).ask("what's in my vault about rust")
        self.assertEqual((out["final_tier"], self.p["T4"].calls), ("T3", 0))

    def test_forced_t4_private_is_refused(self):
        out = self.router().ask("my email to Bob", mode="tier", tier="T4")
        self.assertFalse(out["ok"])
        self.assertEqual(self.p["T4"].calls, 0)

    def test_paid_gate(self):
        self.router(checker=FakeChecker(["FAIL: a", "FAIL: b", "FAIL: c"]), cascade=["T2", "T5"]).ask("explain x")
        self.assertEqual(self.p["T5"].calls, 0)  # unforced, even when listed
        out = self.router().ask("explain x", mode="tier", tier="T5")
        self.assertFalse(out["ok"])  # forced but paid off
        self.assertEqual(self.p["T5"].calls, 0)
        out = self.router(paid_enabled=True).ask("explain x", mode="tier", tier="T5")
        self.assertEqual((out["final_tier"], self.p["T5"].calls), ("T5", 1))


class EscalateAndLog(Base):
    def test_escalate_one_rung_up_and_links_parent(self):
        r = self.router(jev=FakeJev("T2", 0.99))
        first = r.ask("explain x")
        self.assertEqual(first["final_tier"], "T2")
        up = r.escalate(first["id"])
        self.assertEqual(up["final_tier"], "T4")  # ladder T2 -> T4 -> T3
        self.assertEqual(self.log.get(up["id"])["parent_id"], first["id"])
        self.assertEqual(self.log.get(first["id"])["feedback"], "escalated")
        self.assertEqual(r.escalate(up["id"])["final_tier"], "T3")

    def test_escalate_private_skips_t4_and_top_fails_cleanly(self):
        r = self.router(jev=FakeJev("T2", 0.99))
        first = r.ask("my salary question")
        self.assertEqual(r.escalate(first["id"])["final_tier"], "T3")
        top = r.ask("explain x", mode="tier", tier="T3")
        self.assertFalse(r.escalate(top["id"])["ok"])  # T5 off
        self.assertFalse(r.escalate("nope")["ok"])

    def test_log_row_written(self):
        out = self.router(jev=FakeJev("T2", 0.99, 0.0002)).ask("explain x")
        row = self.log.get(out["id"])
        self.assertEqual((row["text"], row["mode"], row["final_tier"], row["jev_choice"], row["jev_p"]),
                         ("explain x", "auto", "T2", "T2", 0.99))
        self.assertEqual(row["path"][0]["tier"], "T2")
        self.assertEqual(set(row["path"][0]), {"tier", "provider", "model", "ok", "check", "ms", "error"})
        self.log.set_feedback(out["id"], "up")
        self.assertEqual(self.log.get(out["id"])["feedback"], "up")
        stats = self.log.stats()
        self.assertAlmostEqual(stats["jev_usd_month"], 0.0002)
        self.assertEqual(stats["ollama_calls_today"], 1)

    def test_all_fail_returns_clear_answer(self):
        for t in self.p:
            self.p[t] = FakeProvider(t, ok=False, error="down")
        out = self.router().ask("explain x")
        self.assertFalse(out["ok"])
        self.assertIn("no tier could answer", out["answer"])
        self.assertIsNotNone(out["id"])

    def test_provider_raising_never_escapes(self):
        class Boom:
            def complete(self, *a, **k):
                raise RuntimeError("x")
        self.p["T2"] = Boom()
        out = self.router(checker=FakeChecker(["PASS"])).ask("explain x")
        self.assertEqual(out["final_tier"], "T4")


class JevTierOffline(unittest.TestCase):
    def test_offline_mock_and_seed_copy(self):
        from bridge.jevtier import JevTier
        os.environ["AOS_OFFLINE"] = "1"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "rulebook.json"
            j = JevTier(str(path), 0.9)
            self.assertEqual(set(json.loads(path.read_text())["criteria"]), {"T1", "T2", "T3"})
            choice, p, usd = j.decide("write me a cover letter")
            self.assertIn(choice, {"T1", "T2", "T3"})
            self.assertTrue(0.5 <= p <= 1.0)
            path.write_text("not json")
            self.assertEqual(j.decide("x"), (None, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()

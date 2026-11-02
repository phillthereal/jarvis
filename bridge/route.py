"""Routing engine: SPEC "Routing" steps 1-9. Providers, checker, Jev, lookups, usage and log are injected."""
import re
import time

from bridge import tier1
from bridge.log import normalise

LADDER = ["T1", "T2", "T4", "T3", "T5"]  # weakest -> strongest; escalate = next rung (T4 free cloud sits below Pro)
CHECK_SYSTEM = ("You grade an assistant's answer. Reply with exactly `PASS` if it correctly and fully answers the "
                "question, otherwise exactly `FAIL: <short reason>`. No other text.")

# Requests that look like "do X" get ACTION_SYSTEM (answering only, never the checker). See bridge/actions.py.
ACTION_RE = re.compile(r"\b(mark|set|tick)\b.*\b(done|status|task)\b"
                       r"|\b(add|put|schedule|book)\b.*\b(calendar|event|meeting|reminder)\b"
                       r"|\b(draft|reply|write)\b.*\b(email|mail|reply)\b", re.I | re.S)
ACTION_SYSTEM = """You cannot act directly. To propose an action, include one fenced block like:
```jarvis-action
{"type": "<type>", ...fields}
```
Types: notion_task_update {task: exact task title (or page_id), done: true/false and/or status: text};
calendar_add {title, start: "YYYY-MM-DDTHH:MM" local, end (same format) or duration_min 5-1440, notes?};
email_draft {to: one email address, subject, body} (saves a draft only; nothing is sent).
Filip must approve every action before it runs. Never claim an action was done; say it is proposed.
Today is {today}."""


def action_system(text):
    """ACTION_SYSTEM for action-intent requests, else None (no system prompt, as before)."""
    if not ACTION_RE.search(text or ""):
        return None
    return ACTION_SYSTEM.replace("{today}", time.strftime("%A %Y-%m-%d %H:%M"))


def parse_verdict(text):
    """'PASS' or 'FAIL: <reason>'. Anything that is not exactly one of those is a FAIL."""
    v = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    if v == "PASS":
        return "PASS"
    if re.fullmatch(r"FAIL:\s*\S.*", v, re.S):
        return v
    return "FAIL: malformed verdict"


class Router:
    def __init__(self, cfg, providers, checker, jev, lookups, usage_fn, log, model_factory=None):
        """providers: {"T2": P, "T3": P, "T4": P, "T5": P}. model_factory(model) -> (tier, Provider) is optional,
        for mode="model"; without it the model name only picks the tier."""
        self.cfg, self.providers, self.checker, self.jev = cfg, providers, checker, jev
        self.lookups, self.usage_fn, self.log, self.model_factory = lookups, usage_fn, log, model_factory

    # ---- helpers
    def _private(self, text):
        low = text.lower()
        return any(p in low for p in self.cfg.get("private_patterns", [])) or tier1.match(text) is not None

    def _high_stakes(self, text):
        low = text.lower()
        return any(p in low for p in self.cfg.get("high_stakes", []))

    def _spill(self):
        try:
            pct = (self.usage_fn() or {}).get("session_pct")
            return isinstance(pct, (int, float)) and pct >= self.cfg.get("pro_spill_pct", 80)
        except Exception:  # noqa: BLE001 - unknown usage never spills
            return False

    def _tier_for_model(self, model):
        m = model.lower()
        if any(n in m for n in ("sonnet", "haiku", "opus", "claude")):
            return "T3"
        if m in (self.cfg.get("ollama_model", ""), self.cfg.get("ollama_fallback", "")):
            return "T2"
        if any(m == p.get("model", "").lower() for p in self.cfg.get("tier4_providers", [])):
            return "T4"
        return "T3"

    def _check(self, text, ans):
        prompt = f"Question:\n<<<\n{text}\n>>>\n\nAnswer:\n<<<\n{ans.text}\n>>>"
        try:
            v = self.checker.complete(prompt, system=CHECK_SYSTEM)
            return parse_verdict(v.text) if v.ok else f"FAIL: check error ({v.error})"
        except Exception as exc:  # noqa: BLE001
            return f"FAIL: check error ({type(exc).__name__})"

    def _run(self, st, chain, check, forced=False, provider_override=None):
        """Try tiers in order, applying Pro guard (7), privacy (7b) and the paid gate (8). Returns the first good
        Answer, else the last ok-but-failed-check Answer (the strongest one we got), else None."""
        fallback = None
        queue = list(chain)
        while queue:
            tier = queue.pop(0)
            if tier == "T3" and st["spill"] and not st["private"]:
                tier = "T4"  # privacy wins over quota: a private request stays on T3
            if tier in st["tried"]:
                continue
            skip = ("skipped: private request" if tier == "T4" and st["private"] else
                    "skipped: paid tier off or not forced"
                    if tier == "T5" and not (self.cfg.get("paid_enabled") and forced) else None)
            if skip:
                st["tried"].add(tier)
                st["path"].append(dict(tier=tier, provider=None, model=None, ok=False, check=None, ms=0, error=skip))
                continue
            st["tried"].add(tier)
            if tier == "T1":
                ans = tier1.answer(st["t1"], self.lookups) if st["t1"] else None
            else:
                p = provider_override or self.providers.get(tier)
                ans = None
                if p is not None:
                    try:
                        sysp = st.get("system")
                        ans = p.complete(st["text"], system=sysp) if sysp else p.complete(st["text"])
                    except Exception as exc:  # noqa: BLE001 - providers should not raise; guard anyway
                        st["path"].append(dict(tier=tier, provider=None, model=None, ok=False, check=None, ms=0,
                                               error=f"provider raised {type(exc).__name__}"))
                        continue
            if ans is None:
                st["path"].append(dict(tier=tier, provider=None, model=None, ok=False, check=None, ms=0,
                                       error="not available"))
                continue
            verdict = self._check(st["text"], ans) if (check and ans.ok) else None
            st["path"].append(dict(tier=tier, provider=ans.provider, model=ans.model, ok=ans.ok, check=verdict,
                                   ms=ans.latency_ms, error=ans.error))
            if not ans.ok:
                if tier == "T3" and "pro_limit" in (ans.error or ""):
                    st["spill"] = True
                    queue.insert(0, "T4")
                continue
            if verdict is None or verdict == "PASS":
                return tier, ans
            fallback = (tier, ans)
        return fallback

    def _finish(self, st, mode, result, t0, parent_id=None):
        if result:
            tier, ans = result
            out = dict(ok=True, answer=ans.text, final_tier=tier, provider=ans.provider, model=ans.model, error=None)
        else:
            errs = "; ".join(f"{s['tier']}: {s['error'] or s['check']}" for s in st["path"]) or "no tier available"
            out = dict(ok=False, answer=f"Sorry, no tier could answer this ({errs}).", final_tier=None,
                       provider=None, model=None, error="all_failed")
        out.update(path=st["path"], ms=int((time.perf_counter() - t0) * 1000),
                   jev_choice=st["jev"][0], jev_p=st["jev"][1])
        try:
            out["id"] = self.log.insert(text=st["text"], mode=mode, final_tier=out["final_tier"],
                                        provider=out["provider"], model=out["model"], jev_choice=st["jev"][0],
                                        jev_p=st["jev"][1], jev_usd=st["jev"][2], path=st["path"],
                                        answer=out["answer"], parent_id=parent_id)
        except Exception:  # noqa: BLE001 - a log failure must not lose the answer
            out["id"] = None
        return out

    # ---- public
    def ask(self, text, mode="auto", tier=None, model=None):
        t0 = time.perf_counter()
        st = dict(text=text, path=[], tried=set(), spill=self._spill(), private=self._private(text),
                  t1=tier1.match(text), jev=(None, None, 0.0), system=action_system(text))
        cascade = [t for t in self.cfg.get("cascade", ["T2", "T4", "T3"]) if t != "T5"]
        try:
            # 1. forced tier / model: skips 2-4 and the cascade; 7, 7b and 8 still apply
            if mode == "tier" and tier:
                return self._finish(st, mode, self._run(st, [tier], check=False, forced=True), t0)
            if mode == "model" and model:
                prov = None
                if self.model_factory:
                    tier, prov = self.model_factory(model)
                tier = tier or self._tier_for_model(model)
                return self._finish(st, mode, self._run(st, [tier], False, True, prov), t0)
            # 2. repeat cache
            cached = self.log.recent_confirmed(normalise(text))
            if cached:
                r = self._run(st, [cached], check=False)
                if r:
                    return self._finish(st, mode, r, t0)
            # 3. tier 1
            if st["t1"]:
                r = self._run(st, ["T1"], check=False)
                if r:
                    return self._finish(st, mode, r, t0)
            # 6. high stakes: no Jev, no cascade, start at T3 (T4 only as an error fallback)
            if self._high_stakes(text):
                st["private"] = True  # high-stakes text never goes to third-party free clouds
                chain = ["T3"] + [t for t in cascade if t not in ("T2", "T3")]
                return self._finish(st, mode, self._run(st, chain, check=False), t0)
            # 4. Jev
            choice, p, usd = self.jev.decide(text)
            st["jev"] = (choice, p, usd)
            if choice and p >= self.cfg.get("jev_threshold", 0.9) and (choice != "T1" or st["t1"]):
                r = self._run(st, [choice], check=False)
                if r:
                    return self._finish(st, mode, r, t0)
            # 5. cascade, every answer checked locally
            return self._finish(st, mode, self._run(st, cascade, check=True), t0)
        except Exception as exc:  # noqa: BLE001 - never raise to the caller
            st["path"].append(dict(tier=None, provider=None, model=None, ok=False, check=None, ms=0,
                                   error=f"router error {type(exc).__name__}"))
            return self._finish(st, mode, None, t0)

    def escalate(self, request_id):
        """Rerun one rung above the previous final tier (LADDER), linked by parent_id. Counts as forced."""
        t0 = time.perf_counter()
        row = self.log.get(request_id)
        if not row:
            return dict(ok=False, id=None, answer="Unknown request id.", final_tier=None, provider=None, model=None,
                        path=[], ms=0, error="not_found", jev_choice=None, jev_p=None)
        text = row["text"]
        self.log.set_feedback(request_id, "escalated")
        st = dict(text=text, path=[], tried=set(), spill=self._spill(), private=self._private(text),
                  t1=tier1.match(text), jev=(None, None, 0.0), system=action_system(text))
        prev = row["final_tier"] if row["final_tier"] in LADDER else "T1"
        st["tried"].update(LADDER[:LADDER.index(prev) + 1])  # never land at or below the old tier
        chain = LADDER[LADDER.index(prev) + 1:]
        # first rung that survives the guards answers; later rungs only if it errors
        return self._finish(st, "escalate", self._run(st, chain, check=False, forced=True), t0,
                            parent_id=request_id)

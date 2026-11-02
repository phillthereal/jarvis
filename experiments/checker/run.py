"""Checker experiment. Run from repo root: python3 experiments/checker/run.py  (stdlib only, local Ollama)."""
import json, os, statistics, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from bridge.route import CHECK_SYSTEM, parse_verdict
from bridge.providers.ollama import OllamaProvider

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_V2 = ("You are a strict fact-checker grading an assistant's answer to a question. Check each of these: "
            "(1) the answer addresses exactly the question asked, not a related or different one; "
            "(2) every factual claim is true, and no invented names, papers, laws, dates or figures; "
            "(3) it is complete, not cut off mid-sentence; "
            "(4) it actually answers instead of refusing or dodging a harmless request. "
            "If ANY check fails, or you are unsure, the answer fails. "
            "Reply with exactly `PASS` if all four hold, otherwise exactly `FAIL: <short reason>`. No other text.")
PROMPTS = {"base": CHECK_SYSTEM, "strict": CHECK_V2}


def run(model, pname, cases):
    p, rows = OllamaProvider(model), []
    for c in cases:
        prompt = f"Question:\n<<<\n{c['question']}\n>>>\n\nAnswer:\n<<<\n{c['answer']}\n>>>"  # == Router._check
        a = p.complete(prompt, system=PROMPTS[pname], timeout=120)
        v = parse_verdict(a.text) if a.ok else f"FAIL: check error ({a.error})"
        rows.append(dict(id=c["id"], label=c["label"], kind=c["kind"], verdict=v, raw=a.text, ms=a.latency_ms, ok=a.ok))
        print(model, pname, c["id"], c["label"], v[:40], a.latency_ms, flush=True)
    return rows


def stats(rows):
    good = [r for r in rows if r["label"] == "good"]; bad = [r for r in rows if r["label"] == "bad"]
    bp = [r for r in bad if r["verdict"] == "PASS"]; gf = [r for r in good if r["verdict"] != "PASS"]
    return dict(acc=(len(rows) - len(bp) - len(gf)) / len(rows), bp=len(bp), nb=len(bad), gf=len(gf), ng=len(good),
                med=statistics.median(r["ms"] for r in rows), errs=sum(not r["ok"] for r in rows),
                malformed=sum(r["verdict"] == "FAIL: malformed verdict" for r in rows))


def main():
    cases = [json.loads(l) for l in open(os.path.join(HERE, "cases.jsonl"))]
    byid = {c["id"]: c for c in cases}
    cfg = json.load(open(os.path.join(HERE, "..", "..", "config.json")))
    plan = [(cfg["check_model"], "base"), ("qwen2.5:7b", "base")]
    res = {}
    while plan:
        m, pn = plan.pop(0)
        res[f"{m}|{pn}"] = run(m, pn, cases)
        if pn == "base" and stats(res[f"{m}|{pn}"])["bp"] / 20 > 0.10 and not any(k.endswith("|strict") for k in res):
            plan.insert(0, (m, "strict"))  # ONE variant, on the first model that fails the bar
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    out = ["# Checker experiment results", "", "Production check (CHECK_SYSTEM + parse_verdict, Router._check prompt format), 40 hand-written cases (20 good / 20 bad).", "",
           "| model | prompt | accuracy | bad passed (dangerous) | good failed (wasted) | median ms | malformed | errors |", "|---|---|---|---|---|---|---|---|"]
    for k, rows in res.items():
        s = stats(rows); m, pn = k.split("|")
        out.append(f"| {m} | {pn} | {s['acc']:.0%} | {s['bp']}/{s['nb']} = {s['bp']/s['nb']:.0%} | {s['gf']}/{s['ng']} = {s['gf']/s['ng']:.0%} | {s['med']:.0f} | {s['malformed']} | {s['errs']} |")
    for k, rows in res.items():
        s = stats(rows)
        tp = s["ng"] - s["gf"]
        out += ["", f"## {k}", "", "| truth \\ verdict | PASS | FAIL |", "|---|---|---|",
                f"| good | {tp} | {s['gf']} |", f"| bad | {s['bp']} | {s['nb']-s['bp']} |", "", "Worst misses (bad answers passed first, then good failed):", ""]
        miss = [r for r in rows if r["label"] == "bad" and r["verdict"] == "PASS"] + [r for r in rows if r["label"] == "good" and r["verdict"] != "PASS"]
        for r in miss[:5]:
            c = byid[r["id"]]
            out.append(f"- #{r['id']} ({r['label']}, {r['kind']}) Q: {c['question']} | A: {c['answer'][:90]} | verdict: {r['verdict'][:80]}")
        if not miss: out.append("- none")
    open(os.path.join(HERE, "RESULTS.md"), "w").write("\n".join(out) + "\n")


main()

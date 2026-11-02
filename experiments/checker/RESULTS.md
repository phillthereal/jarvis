# Checker experiment results

Production check (CHECK_SYSTEM + parse_verdict, Router._check prompt format), 40 hand-written cases (20 good / 20 bad).

| model | prompt | accuracy | bad passed (dangerous) | good failed (wasted) | median ms | malformed | errors |
|---|---|---|---|---|---|---|---|
| qwen3.5:9b | base | 100% | 0/20 = 0% | 0/20 = 0% | 5654 | 0 | 0 |
| qwen2.5:7b | base | 95% | 1/20 = 5% | 1/20 = 5% | 1546 | 0 | 0 |

## qwen3.5:9b|base

| truth \ verdict | PASS | FAIL |
|---|---|---|
| good | 20 | 0 |
| bad | 0 | 20 |

Worst misses (bad answers passed first, then good failed):

- none

## qwen2.5:7b|base

| truth \ verdict | PASS | FAIL |
|---|---|---|
| good | 19 | 1 |
| bad | 1 | 19 |

Worst misses (bad answers passed first, then good failed):

- #24 (bad, wrong-fact) Q: What does CIS mean for UK subcontractors? | A: CIS stands for Certified Insurance Statement, a document subcontractors show to prove they | verdict: PASS
- #14 (good, ai-news) Q: Summarise what an AI agent is in one sentence. | A: An AI agent is a system where a language model decides which actions or tools to use in a  | verdict: FAIL: Simplification needed

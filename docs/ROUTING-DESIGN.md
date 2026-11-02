# Agentic OS — routing design (locked 2026-11-01)

## Constraints
- Only paid service: **Jev** (TypeSafe, ~$0.04/M input tokens). No other paid API by default.
- Claude plan: **Pro** (5-hour window + weekly cap, shared with Filip's own Claude Code use).
- Hardware: Apple M4, 16 GB. Ollama installed, `qwen2.5:7b` pulled.
- Location: UK, so the Gemini free tier is out (its terms require paid services for UK users).

## Tiers
| Tier | Who answers | Cost |
|---|---|---|
| 1 | No AI: rules + saved data (vault, digest) | free |
| Jev | Sorts each request to a tier, returns confidence | paid (pennies) |
| 2 | Local Ollama | free |
| 3 | Claude Code on Pro (`claude -p`), Sonnet/Haiku by default, Opus when needed | plan |
| 4 | Free cloud: Groq → OpenRouter free (GitHub Models only if confirmed alive) | free |
| 5 | Paid APIs | **off by default**, explicit switch |

Dashboard picker: Auto / force tier / force model. Each tier has a fallback list.
When Pro usage runs low, Tier 3 work spills to Tier 4.

## "Answer now, learn tonight"
Live:
1. Obvious repeat (near-identical past request) → reuse stored decision.
2. Jev confident (p ≥ 0.9, to be re-calibrated on dashboard traffic) → route.
3. Jev unsure → cascade: cheapest likely tier, local model checks the answer, escalate on fail.
4. High-stakes (e.g. ACTION_NEEDED email) → straight to a stronger tier, no cascade.
5. Errors / 👎 / "escalate" button → move up a tier, log as a lesson.

Nightly (Opus on Pro, while idle):
6. Review all unsure cases + a random sample of confident ones (catches confident-wrong).
7. Write a candidate Jev rulebook; promote only with 0 misses on held-out data across multiple splits, and Filip's approval.
8. Spot repeated request types → propose Tier 1 shortcuts / skills.
9. Morning note in the vault: what was learned, what changed, what needs approval.

Reuses: `~/Ai Workload` Jev adapter, rulebook, `jev_loop.py` (teacher = Claude via file handshake, $0 API).

## Rejected (and why)
- Live Opus judge on every unsure request: adds latency, competes with Filip's Pro usage, never catches confident mistakes.
- Two-model agreement: failed the 4-split robustness check (Oct 2026).
- User corrections as main teacher: 0 corrections in 3,299 email decisions.

## First experiment once built
Is the local 7B model a good enough answer-checker for step 3?

## Email chain (decided 2026-11-01)
v1 leaves n8n untouched (gpt-4o-mini, pennies/month). Phase 2: replay saved emails through
Groq / local tiers offline; switch n8n to call the bridge only if protected classes show 0 misses
across multiple splits. Then OpenAI can be dropped entirely.

## Toolkit
Use (already connected): Notion, Outlook (ms365), Gmail, Notion Calendar, Google Drive,
scheduled-tasks, AI router MCP server, playwright-cli.
Download: Obsidian app, ccusage (real Pro session/week % for the usage meter), free Groq + OpenRouter
keys, a newer 7-8B Ollama model (pick at build time). Later: faster-whisper, kokoro-onnx.
Build (skills): /plan-today, /inbox-brief, /morning-intel (free RSS: HN, arXiv, lab blogs, gh trending),
/night-school (the nightly Opus learning loop), /vault-ingest (raw→wiki), /vault-lint.
Build (MCP): extend the existing router MCP server into the bridge's MCP (route, read/write vault).
Add (free allowances that stop at the cap instead of billing):
- Bright Data (plugin already installed): 5,000 requests/month free; after that requests fail rather than charge.
  Morning-intel fallback for sites RSS can't reach (X, YouTube, blocked pages). Filip creates the account + key.
- Apify (MCP already connected): $5/month credit, blocked rather than billed when used up. Specific actors
  (e.g. YouTube transcripts, Reddit) for morning intel / research skills.
- Obsidian MCP (cyanheads/obsidian-mcp-server via the Local REST API plugin): for interactive Claude Code
  sessions (search, tags, frontmatter edits). The bridge still reads/writes files directly, so nothing
  breaks when Obsidian is closed. Review its source before installing (it gets write access to the vault).
Usage guard: the bridge counts calls to each capped tool and routes to free RSS once ~80% of the month's allowance is used.
Skip: creative-media connectors (Canva, Kling, Higgsfield).
Rule: background skills get read-only connectors; anything that sends or posts waits for Filip.

## Still open
- Other dashboard widgets (Filip to decide later).

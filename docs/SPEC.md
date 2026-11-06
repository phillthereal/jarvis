# Agentic OS ("Keystone") v1 — spec

Routing decisions and their reasons: `docs/ROUTING-DESIGN.md` (locked). This file is the build contract.

## Goals (v1)
1. A local dashboard (one page) for asking things, seeing today's state, and running skills.
2. A bridge that routes each request through the 5-tier ladder at ~£0 (only Jev is paid).
3. An Obsidian vault as shared memory: every answer, report and brief lands there as markdown.
4. A nightly learning loop ("night school") where Opus improves Jev's routing from logged traffic.

## Non-goals (v1)
Voice, Obsidian plugin, Codex mode, mobile layout polish, multi-user, any public exposure,
changes to the live n8n email chain, sending/posting anything on Filip's behalf.

## Stack
- Python 3.13 stdlib only for the bridge (`http.server`, `sqlite3`, `urllib`, `subprocess`, `json`).
- Reuse (import, never modify): `~/Ai Workload` package `router` → `router.adapters.typesafe.JevClient`,
  `router.rulebook.Rulebook`. Installed with `python3 -m pip install --user -e "~/Ai Workload"` (location override: `AOS_AI_WORKLOAD`).
- Frontend: static `web/index.html` + `web/app.js` + `web/style.css`. No framework, no build step.
- Tests: stdlib `unittest`, all network/subprocess mocked. `AOS_OFFLINE=1` forces mocks everywhere.
- Ollama at `http://127.0.0.1:11434`; Claude Code CLI `claude` (2.1.310) for Tier 3 and skills.

## Locations
- Code: `~/agentic-os` (NOT ~/Desktop: macOS blocks launchd jobs from reading Desktop).
- Vault: `~/Claude+Obsidian` (override: `AOS_VAULT`). Secrets: `~/agentic-os/.env` (chmod 600, gitignored).
- Runtime data: `~/agentic-os/data/` (gitignored): `requests.db`, `usage.json`, `night/`.

## Architecture
```
web/ (dashboard) ──HTTP──> bridge/server.py ──> bridge/route.py ──> tiers
                                  │                    │            ├ tier1.py   rules + saved data
                                  │                    │            ├ jev        (router.JevClient + data/rulebook.json)
                                  │                    │            ├ providers.ollama        (Tier 2)
                                  │                    │            ├ providers.claude_cli    (Tier 3, claude -p)
                                  │                    │            ├ providers.free_cloud    (Tier 4: Groq → OpenRouter)
                                  │                    │            └ providers.paid          (Tier 5, disabled unless config)
                                  │                    └──> bridge/log.py (SQLite requests + feedback)
                                  ├──> bridge/widgets.py (inbox / plan / intel / weekly / system)
                                  └──> bridge/jobs.py (background skill runs via claude -p, reports → vault)
night/ (night school, run by launchd 03:00) ──> reads requests.db, writes proposals + morning note to vault
```

### Provider interface (every tier client implements this)
`complete(prompt: str, system: str | None = None, timeout: float = 60) -> Answer`
`Answer = dataclass(text, provider, model, ok: bool, error: str | None, latency_ms: int)`.
Never raises on network/HTTP errors: returns `ok=False` with a short, secret-free error.

### Routing (bridge/route.py) — see ROUTING-DESIGN.md "Answer now, learn tonight"
1. Mode `force_tier` / `force_model` from the request skips steps 2-4.
2. Repeat cache: normalised text exact match against the last 30 days of requests whose final tier
   was confirmed (👍 or night-school label) → reuse that tier.
3. Tier 1 intents (regex, no AI): priorities/directives, inbox, usage, "what did X say" vault grep.
4. Jev: choices `T1 | T2 | T3` with confidence. Sure = p ≥ `jev_threshold` (config, default 0.9).
   Sure → that tier. Unsure → cascade.
5. Cascade order (config `cascade`, default `["T2", "T4", "T3"]`, i.e. protect Pro): answer at each step, then the
   local check model grades it (`PASS`/`FAIL` + reason, strict format). FAIL or error → next step.
6. High-stakes (regex list in config, e.g. contract, payment, legal, medical, "send", "email to") → skip the
   cascade, start at T3.
7. Pro guard: if usage session% ≥ `pro_spill_pct` (default 80) or unknown-and-recent-429, T3 is replaced by T4.
7b. Privacy: requests carrying vault/email/Notion context or matching `private_patterns` never go to T4
   (third-party free clouds); they stay on T1/T2/T3. The local check model always runs on T2 (no cloud quota).
8. T5 only when `paid_enabled: true` in config AND the request forces it. Default false.
9. Every request logs: id, ts, text, mode, path taken (each step: tier, provider, model, ok, check verdict, ms),
   final tier, jev choice + p, feedback (null / up / down / escalated). Escalate button = rerun one tier up.

### Config (`config.json`, committed; secrets only in .env)
`jev_threshold, cascade, pro_spill_pct, paid_enabled, ollama_model (default "qwen3.5:9b", fallback "qwen2.5:7b"), private_patterns,
check_model, tier3_model ("sonnet"), tier4_providers ([{name, base_url, model, key_env}]), high_stakes, port (8777)`.

### Bridge HTTP API (127.0.0.1:8777 only)
Auth: `GET /` sets an HttpOnly SameSite=Strict cookie with a random per-start token; every `/api/*` needs it.
Reject: bad Host (not 127.0.0.1/localhost:8777), any Origin other than own, non-JSON POST (415), body > 256 KB.
| Method | Path | Returns |
|---|---|---|
| GET | `/api/status` | tiers health (ollama up, keys present, jev key present, paid_enabled), usage `{session_pct, week_pct, resets_at, source}` or `source:"unknown"` |
| POST | `/api/ask` `{text, mode:"auto"\|"tier"\|"model", tier?, model?}` | `{id, answer, final_tier, provider, model, path[], ms}`; answer also appended to vault `outputs/conversations/YYYY-MM-DD.md` |
| POST | `/api/feedback` `{id, verdict:"up"\|"down"\|"escalate"}` | escalate returns a new answer like `/api/ask` |
| GET | `/api/widgets/inbox` | Notion Email Tasks open items + last-run counts; `{configured:false}` without token |
| GET | `/api/widgets/plan` | top-3 directives from vault `wiki/directives.md` + due follow-ups + today's Apple Calendar events |
| GET | `/api/usage` | all providers: Claude Pro session/week % (statusline `rate_limits`), Claude tokens per model (ccusage), Jev $ this month, Groq/OpenRouter remaining (rate-limit headers), Ollama calls, Bright Data/Apify % of free cap |
| GET | `/api/widgets/intel` | latest `outputs/intel/*.md` headline list + path |
| POST | `/api/skills/{name}/run` | starts background job → `{job_id}` |
| GET | `/api/jobs/{job_id}` | `{state, started, finished, report_path, error}` |
| GET | `/api/night` | latest morning note summary + pending proposals |
| POST | `/api/night/approve` `{proposal_id}` | applies an approved rulebook / shortcut |

### Vault layout (`~/Claude+Obsidian`)
`CLAUDE.md` (the map + rules for agents), `raw/` (captures, `raw/notion/` sync), `wiki/` (articles,
`wiki/directives.md`), `outputs/{conversations,briefs,intel,plans,night-school}/`, `library/<Category>/` (filed
documents + sidecar notes; `_review/`, `_duplicates/`), `.claude/skills/<skill>/SKILL.md`,
`.obsidian/app.json` with `.claude` excluded from search/graph.

### Skills (in vault `.claude/skills/`, run headless via `claude -p` with cwd = vault)
`/plan-today`, `/inbox-brief`, `/morning-intel`, `/night-school`, `/vault-ingest`, `/vault-lint`.
Headless runs use `--allowedTools` limited to Read, Grep, Glob, Write/Edit inside the vault, and the
skill's own scripts; no network tools except where the skill needs them (morning-intel fetch script).
Untrusted text (emails, scraped pages, RSS) is fenced and summarised, never obeyed.

### Morning intel sources
Free first: RSS/Atom via stdlib (Hacker News front page, arXiv cs.AI/cs.CL new, lab blogs with feeds).
Bright Data (`BRIGHTDATA_API_KEY`, zone `WEB_UNLOCKER_ZONE`) and Apify only as fallback for sources without
feeds. `data/usage.json` counts calls per month; at 80% of the free cap (Bright Data 5,000 req, Apify $5) stop
using that tool until next month.

### Night school (night/)
Nightly via launchd (`StartCalendarInterval` 22:00, runs on wake if missed):
1. Export last day's unsure + escalated + 👎 requests, plus a random 10% of confident ones (max 40 total).
2. Opus labels the right tier with a one-line reason, via `claude -p --model opus` + file handshake
   (pattern: `~/Ai Workload/jev_loop.py --teacher manual`). Hard cap: one run per night, ≤ 40 cases.
3. Propose ONE rulebook edit; gate on accumulated labelled data: ≥ 3 chronological/random splits,
   promote only if 0 misses on every held-out split and agreement does not drop. Leak guard as in jev_loop.
4. Count repeated request patterns (≥ 3 in 7 days) → propose a Tier 1 shortcut (regex + data source).
5. Write `outputs/night-school/YYYY-MM-DD.md` (learned / changed / needs approval). Nothing applies without
   `/api/night/approve`.

## Definition of done (MVP)
- `python3 -m unittest` green offline; `python3 -m bridge` starts; dashboard loads at http://127.0.0.1:8777.
- An ask in auto mode routes and logs; force tier works; 👍/👎/escalate work; answers land in the vault.
- Missing keys/services degrade visibly (tier shown as off in status) instead of crashing.
- Widgets render real data where configured, a clear "connect X" state where not.
- Skills run headless and write reports to the vault; launchd plists written (loaded only after Filip's OK).
- Night school runs end to end on synthetic requests offline and produces a morning note + gated proposal.

### Response shapes (fixed by the dashboard, task 8 — the bridge must return these)
- `/api/status`: `{tiers:{t1,jev,t2,t3,t4,t5:{state:"up"|"degraded"|"off", reason?}}}`
- `/api/usage`: `{claude:{session_pct, week_pct, session_resets_at, week_resets_at}, tokens_today:[{model,tokens}],
  jev_usd_month, groq_remaining, openrouter_remaining, ollama_calls_today, brightdata_pct, apify_pct,
  unknown_reasons:{<field>: "why"}}` — null = unknown.
- `/api/widgets/plan`: `{directives:[{text,done}], events:[{time,title}], calendar?:"denied"|"unavailable"}`
- `/api/widgets/inbox`: `{configured, need_action, items:[{title,from}], error?}`
- `/api/widgets/intel`: `{headlines:[{title}], last_run, path}` or `{empty:true}`
- `/api/night`: `{last_run, learned, pending:[{id,summary}]}`
- `/api/ask` and escalate: `{id, answer, final_tier, provider, model, ms, saved, path:[{tier,provider,model,p?,ok,verdict?,ms,error?}]}`
- `POST /api/skills/{name}/run` body `{}` → `{job_id}`; `/api/jobs/{id}` state `"running"|"done"|"error"`.

## v2 additions
- `GET /api/health` -> `{jobs:[{job,last_run,ok,detail}]}`, one per `launchd/com.filip.aos-*.plist`. ok=false on a non-zero last exit code, or a scheduled slot missed by > 2 h; KeepAlive jobs (bridge) must be running. Offline: `{jobs:[]}`.
- Vault backup: local git repo in the vault (no remote), nightly job `com.filip.aos-vault-backup` at 23:30 runs `scripts/backup_vault.sh` (commit only if changed). Vault `.gitignore` excludes `.obsidian/plugins/*/data.json`, `.obsidian/workspace*`, `.trash/`.
- `/api/status` gains top-level `tts_voice` (from config; preferred browser voice name for read-aloud, may be null).
- **Actions with approval** (`bridge/actions.py`). Table `actions` in `requests.db`: `id INTEGER PK, type, payload
  (JSON), summary, status (pending|approved|rejected|done|failed), created, decided, result (JSON)`.
  - Proposal: requests matching the action-intent regex (mark/set/tick … done/status/task; add/put/schedule/book …
    calendar/event/meeting/reminder; draft/reply/write … email/mail/reply) are answered with `ACTION_SYSTEM`
    (route.py; never sent to the checker; other requests keep no system prompt). The answer may contain up to 3
    fenced ` ```keystone-action ` JSON blocks. The bridge strips every block from the shown/saved answer, validates
    each against its type schema (unknown type or key → rejected, not stored) and stores valid ones as `pending`
    with a bridge-written summary. T1 answers are never parsed. Nothing executes without `approve`.
  - `notion_task_update`: `{task: title ≤200 | page_id: Notion id, done?: bool, status?: str ≤50}`, at least one of
    done/status. `task` is resolved at proposal time to exactly one Email Tasks page (case-insensitive exact title).
    Execute: GET the page, refuse unless its parent DB is `NOTION_EMAIL_TASKS_DB`; map `done` → the checkbox
    property (no checkbox: a done-like status option), `status` → the status/select property (must be an existing
    option); PATCH the page. Result `"updated <title>"`.
  - `calendar_add`: `{title ≤200, start "YYYY-MM-DDTHH:MM" local, end same format | duration_min 5..1440,
    notes? ≤2000}`; end after start; start within the next 365 days. Execute: KeystoneCalendar.app
    `--args add --no-prompt <title> <start> <end> [notes]` → `OK <id>` / `ERR <reason>`.
  - `email_draft`: `{to: one address, subject ≤200 one line, body ≤20000}`. Execute: write
    `<vault>/outputs/drafts/<YYYY-MM-DD>-<slug>.md` (frontmatter type/to/subject/created; never overwrites, adds
    -2, -3) → result `{path, mailto}`; the mailto URL stays under 1800 chars (body cut with "… (full draft in
    vault)"). **Never sends; no email API.**
  - `/api/ask` and escalate gain `actions:[{id,type,summary}]` and `action_errors:[str]`; the vault conversation
    gets the clean answer plus `Proposed action #id: summary — needs approval` lines.
  - `GET /api/actions` → `{pending:[{id,type,summary,payload,created}], recent:[{id,type,summary,status,result,decided}]}`
    (recent = last 5 decided). `POST /api/actions/<id>/approve` | `/reject` (body `{}`) → 200 with the updated
    action; 409 if it is not pending (atomic `status='pending'` guard, so an action executes at most once); 404
    unknown. Executor errors are recorded as `failed` with a secret-free message.
- **New widgets** (all GET, cookie-authed, read-only):
  - `/api/widgets/weekly` -> `{asked_by_tier:{T1..T5:n}, asked_total, skills_run:[{name,count}], briefs, night_learned}`, last 7 days. Asked = rows in `requests.db` by `final_tier` (escalation children included). Skills run = finished-ok runs in `data/jobs.json` (newest 50 jobs kept, so a very busy week can undercount). Briefs = `.md` files modified in the window under vault `outputs/{briefs,plans,intel}`. Night learned = sum of "N of M exported cases labelled" in `outputs/night-school/YYYY-MM-DD.md` of the window.
  - `/api/widgets/system` -> `{ollama:{up,models}, last_backup: iso|null, jobs:[health list], keys:{groq,openrouter}}`. Ollama `/api/tags`; backup = `git -C <vault> log -1 --format=%cI`; keys are presence booleans only.
- **Skill `weekly-review`** (vault `.claude/skills/weekly-review/SKILL.md`, allow-listed in `bridge/jobs.py` and `scripts/run_skill.sh`): reads vault `outputs/` of the last 7 days, writes `outputs/reviews/YYYY-Www.md` (done, asked most, open loops, 3 suggestions).

## Document library
Engine: `bridge/library.py`. All routes need the cookie and Host/Origin checks.
- `POST /api/library/upload` is the one non-JSON body. `Content-Type: application/octet-stream`, raw bytes (max 25 MB,
  streamed to disk; 413 above, 415 for another content type or an extension outside pdf png jpg jpeg heic tiff txt
  md csv doc docx rtf odt, 400 for empty/short). Headers: `X-Filename` (percent-encoded; path stripped,
  extension kept), optional `X-Description` (percent-encoded, cut to 500 chars). The file goes to the first `library_inbox_dirs` entry under a hidden temp
  name, then `<stem>.keystone.json` `{description}` is written, then the file is linked into place
  (never overwrites: " (2)"…). -> `{"ok": true, "name": "<final file name>"}`. Filing happens when the watcher
  (`launchd/com.filip.aos-library.plist`, `WatchPaths` on both inbox dirs, runs `python3 -m bridge.library scan`)
  fires; `scan` re-passes every 3 s (max 10 passes) while it skipped files younger than 3 s.
- `GET /api/library` -> `{recent[<=8 filed rows], review[rows], duplicates[{id, original_name}], upcoming[{id, title,
  kind: renews|expires, date, days}], total}` (total = filed documents). A row is `{id, original_name, path,
  status, fields{category, title, date, provider, amount, reference, renews, expires, summary, confidence,
  reason?}, note_path, created, decided}`. A review row with `fields.reason == "processing"` is still being read
  (the dashboard hides it). `upcoming` covers -30..+90 days.
- `POST /api/library/<id>/file` `{category, title?, date?}` -> 200 filed row, 400 bad value, 404, 409
  (not in review).
- `POST /api/library/<id>/remind` `{kind?: "renews"|"expires"}` (default: renews, else expires) -> proposes a
  `calendar_add` through `app.actions.propose` ("Renew: <title>" / "Expires: <title>", 09:00 local 14 days before
  the date, or tomorrow 09:00 if that is past, 15 min, notes = vault-relative note path). 200 = the action
  `{id, type, summary}` (pending until approved); 404 unknown; 400 not filed / no such date / propose rejected it.
- Ask lookups: `vault_search` also scans `library/` (the sidecar notes).

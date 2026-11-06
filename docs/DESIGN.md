# Dashboard design (approved layout 2026-11-01)

One page, three columns at ≥1100px (left 1fr · centre 1.5fr · right 1fr), single column below 900px.
Own design, inspired by a "command centre" feel. Not a copy of any product.

## Look
- Dark only for v1. Tokens on `:root`: `--bg #0b0d12`, `--panel #12151d`, `--panel-2 #171b25`, `--line #232836`,
  `--text #e6e8ee`, `--muted #8a90a2`, `--faint #5a6072`, `--accent #7c8cff` (indigo), tier colours
  `--t1 #5ad1a0` (green), `--t2 #63b3ff` (blue), `--t3 #c4a3ff` (violet), `--t4 #f2c46d` (amber), `--t5 #ff7a7a` (red).
- Type: body `Inter, system-ui` 14px/1.55; labels, chips, numbers `"JetBrains Mono", ui-monospace` 11px,
  uppercase tracking .08em for section labels only. Load both from Google Fonts with system fallback.
- Panels: `--panel`, 1px `--line` border, 10px radius, 14px padding, 12px gaps. No shadows, no gradients
  except the core canvas glow.
- Focus rings: 2px `--accent` outline offset 2px. All controls keyboard reachable. Text contrast ≥ 4.5:1.

## Header (full width)
Left: "KEYSTONE" wordmark (mono, 18px, letter-spacing .2em) + "v2" faint + a health dot (8px, `--t5` red, 8px left margin, vertically centred; hidden unless a background job has `ok:false`; aria-label/title list job and detail; from `/api/health`, polled with `/api/status`). Centre: tier health strip
(chips T1 · JEV · T2 · T3 · T4 · T5; green dot = up, amber = no key / degraded, grey = off) from `/api/status`.
Right: clock HH:MM (big, mono) + date (faint).

## Left column
1. **Usage** panel (from `/api/usage`): two big numbers "5-hour %" and "week %" for Claude Pro with reset time,
   thin bar under each (colour amber ≥ 70, red ≥ 90). Below, a compact list: Claude tokens today by model,
   Jev $ this month, Groq/OpenRouter requests left, Ollama calls today, Bright Data/Apify % of free cap.
   Unknown values show "—" with a tooltip saying why.
2. **Directives · top 3** (`/api/widgets/plan`): checkboxes (read-only display in v1) + today's calendar events
   under a faint "Today" label (time · title). No-permission state: "Allow calendar access to show events".
3. **Weekly review** (`/api/widgets/weekly`): big mono "N" + "asks this week", thin stacked bar of asks by tier in
   `--t1..--t5` with a mono 11px text legend ("T1 12 · T2 30 · …") so colour is not the only cue; `.kv` rows Skills run,
   Briefs written, Night-school learned; outline button "Write weekly review" runs the `weekly-review` skill through
   the Skills code path (spinner, poll, "Report ready" link), then reloads Weekly.
4. **System** (`/api/widgets/system`, refreshed every 60s): `.kv` list. Local model "up · N models" (green dot) / "down"
   (red dot); Last backup relative with absolute in the title, "never" in amber; one row per job (name without `aos-`):
   "ok" faint, or the detail in red with a red dot; Cloud keys "Groq ✓ · OpenRouter —". Never shows secrets.

## Centre column
1. **Core**: canvas 100% wide × 260px. ~500 drifting points with faint connecting lines within 70px, slow
   rotation; colour = accent at rest; on request in flight it pulses and tints to the tier colour answering.
   `prefers-reduced-motion`: static frame, no animation. Label under core: last route summary in mono.
2. **Ask bar**: text input (placeholder "Ask or give a task…"), mode select (Auto · Tier 1-5 · Model…), Send
   button (accent fill — the only filled button on the page). Enter sends; Escape clears (see Esc priority). Disabled-looking
   state while in flight but stays focusable; shows "Thinking…" in the core label.
   **Controls row** under the input: outline-chip toggles "Read aloud" (speaker icon) and "Pause to send"
   (`aria-pressed`, persisted in localStorage `aos.voice` / `aos.pauseSend`, both default off), and a right-aligned
   mono status ("Speaking · Esc to stop" / "Sending in 2.5s · any key cancels"). Read aloud speaks each new
   answer (not errors/old ones) sentence by sentence, capped ~600 chars, code blocks replaced by "code block on
   screen". Voice pick: `tts_voice` from `/api/status` → en-GB Premium/Enhanced → en-GB Daniel → any en-GB → default;
   toggle hidden if `speechSynthesis` is missing. Pause to send: 2.5s after the last keystroke, submits like Send.
   **Esc priority**: stop speaking → else cancel countdown → else clear the input.
2b. **Pending actions** (`/api/actions`), between the Ask bar and the answers. `hidden` when nothing is pending
   and nothing was decided this session. Same amber tint as the Night school pending panel; label
   "Pending actions · N" (N = pending). Each item: mono type chip (NOTION / CALENDAR / DRAFT), the bridge summary,
   a `<pre>` with the pretty-printed payload (mono 11px, max-height 160px, scrolls, textContent only), then
   Approve (outline, `--accent` border; Send stays the only filled button) and Reject (text button). Both disable
   while deciding; afterwards a status line replaces them: Done / Rejected / Failed: <error> (red). A done draft
   shows "Open in mail app" (the mailto link) and the draft path in faint mono. Refreshed on load, after every
   answer and after each decision. Answer cards with proposals show a faint "Proposed N action(s) — review above".
3. **Answer card** (latest on top, previous ones collapse to one line each, max 10 kept on screen):
   chip "T2 · qwen3.5:9b" in tier colour, path line in mono faint ("jev T2 0.94 → answered → check pass · 2.1s"),
   answer text (preserve line breaks, render links as text, never HTML from the model), actions 👍 👎 Escalate
   (icon buttons with aria-labels) + "Saved to vault" faint on the right. Errors render inline in the card in red
   text with what to do next.

## Right column
0. **Library** (top of the column, above Skills; `/api/library`). Drop zone: `<label>` wrapping a visually hidden
   `<input type=file multiple>`, dashed 1px `--line`, 10px radius, 88px tall, "Drop documents here" + "or choose
   files" (underlined, muted). Drag-over: `--accent` border + faint accent tint; focus-within shows the ring. Under it
   one row: text input "Describe it (optional)". Status line (mono 11px, faint,
   `aria-live`): "Reading 2 documents…" -> uploads each file (octet-stream + headers), polls `/api/library` every 3 s
   (max 3 min) until each new name is filed / needs a look / duplicate -> "Filed 1 · 1 needs a look" for 8 s. 413/415
   show inline in red with what to do. Then: one mono chip "Documents N" (total filed); "Needs a look · N" (amber,
   only if N>0) rows = name + reason (faint) + category select + outline "File" (no pre-picked guess:
   placeholders until chosen); "Coming up" rows `date · Renews|Expires · title`, red + "(overdue)" when
   past, text button "Remind me" -> POST remind, reloads Pending actions, becomes "Reminder proposed"; "Recently
   filed" last 5 as `Category · title` links (`obsidian://open?path=<absolute note path>`). Server text is
   always `textContent`. Send stays the only filled button.
1. **Skills**: 2×2 grid of outline buttons (Plan today, Inbox brief, Morning intel, Vault ingest) + "Vault lint"
   text link. Click → POST run → button shows a spinner and "Running…"; poll `/api/jobs/{id}` every 3s; done →
   "Report ready" link (opens `obsidian://open?path=<absolute report path>`).
2. **Inbox** (`/api/widgets/inbox`): "N need action" label + up to 5 items. `configured:false` → "Connect Notion
   to show your inbox" + one line on adding `NOTION_TOKEN`.
3. **Morning intel**: headline list (max 5) + time of last run; empty → "Runs daily at 06:30".
4. **Night school** (`/api/night`): amber-tinted panel when proposals are pending: "Learned N routes · M changes
   need your OK" + Review button opening an inline list with Approve per proposal; otherwise a faint
   "Last run 22:00 · nothing pending".

## Behaviour
- Poll `/api/status` and `/api/usage` every 60s; widgets on load and after relevant actions.
- All fetches same-origin with credentials; a 401 shows a full-width banner "Reload the page to reconnect".
- Never insert server/model text with innerHTML; use textContent.

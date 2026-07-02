# Sentinel — PRD
### A memory layer for test & eval harnesses, built on Cognee
*Hackathon: WeMakeDevs x Cognee — "The Hangover Part AI: Where's My Context?"*

---

## 1. One-liner

Sentinel gives your CI a memory. It sits downstream of any test or eval harness (pytest, Jest, Playwright, promptfoo, Inspect, whatever), ingests every run's results into Cognee, and answers the question no dashboard answers: **"have we seen this failure before, and what fixed it?"**

## 2. Problem

Every CI run starts from zero.

- A test fails today with a stack trace. Someone spends 20–40 minutes debugging, discovers it's a race condition in the retry logic, fixes it, moves on.
- Three weeks later a *different* test, in a *different* file, fails with a near-identical root cause. Nobody remembers the first incident. The investigation starts over.
- Flaky tests get "known flaky" tribal knowledge that lives in Slack threads and one engineer's head, not in the system.
- Existing flaky-test tools (BuildPulse, TestDino, Datadog Test Visibility) are excellent at *detecting* instability — flake rate, quarantine, trend charts — but they store history as a flat time-series. None of them reason over *why* something failed or connect it to a *resolution*. They tell you a test is flaky; they don't tell you the story of that test.
- The same gap exists one layer up, in LLM/agent eval harnesses (promptfoo, DeepEval, LangSmith): production failures are supposed to become regression tests, but nothing automatically links a new eval failure back to a semantically similar past one and its fix.

This is a **context/memory problem**, not a detection problem — which is exactly Cognee's lane.

## 3. Goals (hackathon scope)

- Demonstrate deep, non-trivial use of **all four** Cognee lifecycle verbs: `remember`, `recall`, `improve` (memify), `forget`.
- Show a visually compelling "before/after": a failing test with zero context → the same failure with a full recalled history and suggested fix.
- Work against a real, existing harness's output format (not a toy schema) — JUnit XML for code tests, and/or promptfoo JSON for eval harnesses — so the demo reads as "this plugs into what you already use," not "this replaces your tooling."
- Ship something judge-able live: CLI or small web UI + a graph visualization of the memory Cognee has built.

## 4. Non-goals

- Not building a test runner or eval runner. Sentinel never executes tests.
- Not building flaky-test *detection* statistics (flake rate, quarantine automation) — that's BuildPulse/TestDino's job and a solved problem; duplicating it wastes hackathon time.
- Not multi-tenant, not auth, not a hosted SaaS. This is a weekend build behind a single-repo demo.
- Not trying to cover every CI provider. Pick one (GitHub Actions) and go deep.

## 5. Users / personas

| Persona | Need |
|---|---|
| Backend engineer on-call for CI failures | "Have we seen this exact stack trace before? What was the fix?" |
| Team lead doing sprint retro | "Which modules keep generating the same category of failure?" |
| AI/agent engineer running eval suites | "Is this a new failure mode, or a regression of something we already fixed?" |

## 6. Where Sentinel sits (the "harness" question)

```
[ pytest / Jest / Playwright ]     [ promptfoo / Inspect / DeepEval ]
        (test harness)                     (eval harness)
              |                                    |
              v                                    v
        JUnit XML / JSON                   JSON results / traces
              |                                    |
              +---------------→ Sentinel ←---------+
                                    |
                     (on E2E/UI failure, deepen context)
                                    v
                     Playwright / Chromium MCP
              (live DOM snapshot, console errors,
               network failures, screenshot — at
               the moment of failure)
                                    |
                                    v
                              Cognee memory
                        (remember / recall / improve / forget)
                                    |
                                    v
              [MVP] CLI / dashboard output surfacing
                    recalled history + fix suggestion
                                    |
                                    v
              [Stretch] CodeRabbit-style PR comment
              (context-assembled, verified, posted
               natively back to the pull request)
```

Sentinel is explicitly a **second-order layer**. It never touches how tests run. It only reads what a harness already emits, in the harness's own native format, via a thin adapter per harness — zero migration cost, "add a step to your CI yaml," same pitch BuildPulse uses successfully.

The browser MCP is not a second test runner. It's invoked *only after* a harness reports a failure, purely to enrich that one failure's context before it's written to memory — closer to how Chrome DevTools MCP is used for live debugging evidence than how Playwright normally drives a scripted suite.

For the hackathon, build **one harness adapter deeply** (JUnit XML — pytest, Jest w/ jest-junit, Playwright, JUnit itself all emit it) rather than several shallow ones, and pair it with the browser MCP layer for the E2E case specifically.

### 6a. Two-layer architecture: context-acquisition (primary) vs. delivery (stretch)

This project has two genuinely separable concerns, and they map to two different existing product categories worth studying:

**Layer 1 — Context acquisition (primary build target):** *What does Sentinel know about a failure?*
Right now, most of what a test harness reports is a stack trace and a pass/fail. That's thin `remember()` material. A browser MCP (Playwright MCP or Chrome DevTools MCP) lets Sentinel go get richer evidence itself when a UI/E2E test fails: a DOM accessibility snapshot at the point of failure, console errors, failed network requests, a screenshot. That turns `recall()` from "same error string as before" into "same *broken UI state* as before" — a much better demo of Cognee doing real reasoning over rich context, not string matching.

**Layer 2 — Delivery (stretch target):** *How does Sentinel tell a human?*
CodeRabbit's actual innovation isn't the LLM call, it's the context-assembly-then-verify-then-post pipeline: gather many signals, run a judge pass to drop anything ungrounded, then post a native PR comment. Applied here: once Sentinel has a solid recall result, wrap it the same way — assemble (diff + failure + recalled history), verify it's grounded in what was actually recalled (not hallucinated), then post as a PR comment instead of CLI output. This is pure polish on top of a working Layer 1 — do not start here.

**Why this order:** Layer 1 is where the actual Cognee lifecycle story lives (remember/recall/improve/forget) and where the differentiation from BuildPulse/TestDino comes from. Layer 2 is a well-understood UX pattern a judge has already seen; it makes the demo *land* better but doesn't make the underlying idea more novel. If time runs out, a working Layer 1 with plain CLI/dashboard output is still a complete, honest demo. A polished PR bot with thin, stack-trace-only memory underneath is not.

## 7. Cognee lifecycle mapping

| Verb | Trigger | What happens |
|---|---|---|
| `remember()` | After every CI run | Ingest: test name, pass/fail, full stack trace/error message, file(s) touched in the triggering diff, timestamp, run metadata. For E2E/UI failures, first enrich via the browser MCP — DOM accessibility snapshot, console errors, failed network requests, screenshot — then store all of it as linked entities in the graph (test ↔ error signature ↔ DOM/UI state ↔ file ↔ commit). |
| `recall()` | On a new failure | Query the graph for prior occurrences of a similar failure — semantic match on error message *and*, where available, similar DOM/UI state or console signature, not just exact string match — return the linked history: when it happened, what changed, how it was resolved. |
| `improve()` / memify | On resolution event (via session bridge), plus scheduled nightly pass | Engineer's "confirm same issue" action writes a session-scoped fact via `remember(..., session_id=<incident_id>)`; a subsequent `improve(dataset=..., session_ids=[<incident_id>])` bridges that session content into the permanent graph, applying `feedback_alpha`-weighted confidence updates to the relevant edges. This is Cognee's documented self-improvement pattern (session → permanent bridge), not a custom re-weighting scheme. Nightly pass also collapses duplicate error signatures into one canonical "known issue" node. |
| `forget()` | Scheduled or on module deprecation | Prune resolved-issue nodes after N stable runs; drop memory tied to deleted files/modules; decay confidence on old, unconfirmed links so stale noise doesn't pollute recall. |

This is the part of the PRD to walk through carefully in the session — `improve` and `forget` are the two verbs almost every hackathon submission will skip because they're less demo-flashy than `remember`/`recall`. Doing them for real, even simply, is likely the biggest differentiator for judging on "best use of Cognee."

## 8. Core user flow (demo script)

1. A CI run against the live demo app fails — triggered by a **deliberately engineered, reproducible flake** built into a real feature (not a random naturally-occurring flake, which can't be relied on to fire during a judged window). Sentinel's GitHub Action step parses the JUnit XML, extracts the failing test + stack trace + diff context.
2. **If it's an E2E/UI test:** Sentinel spins up the browser MCP against the app (or a saved reproduction target), grabs a DOM accessibility snapshot, console errors, and network failures at the point of failure — this is the richer context payload other tools don't capture.
3. Sentinel calls `remember()` with the combined context (stack trace + browser evidence where available).
4. Before showing anything to the user, Sentinel calls `recall()` against the new failure.
5. **If no prior match:** plain "new failure, no history" output — this is the baseline/control case, useful for showing judges the contrast.
6. **If a prior match exists:** output (CLI/dashboard for MVP; PR comment if the stretch delivery layer is built): *"This failure matches 2 prior incidents in `payments/webhook.py` (Mar 14, Apr 2) — same broken selector after a component rename, confirmed by matching DOM state. Both were resolved by [fix summary]. Confidence: high."*
7. Engineer confirms "same issue" → triggers `improve()`, strengthening that edge in the graph.
8. Live graph visualization (the money shot for the demo) shows the test/error/fix graph growing and consolidating in real time as more runs feed in.
9. A seeded "stale issue" resolves after N stable runs → `forget()` fires, node visibly prunes from the graph. Shows judges the full lifecycle, not just ingestion.
10. **If the stretch delivery layer is built:** repeat step 6's output as a native PR comment instead of CLI output, framed as a context-assemble → verify (drop anything not actually grounded in the recalled data) → post pipeline, same shape as CodeRabbit's pipeline but for failure memory instead of code review.

## 9. Competitive landscape

**Flaky-test / test-observability tools:**
| Tool | What it does | Gap Sentinel fills |
|---|---|---|
| BuildPulse | Detects flaky tests via cross-run statistical comparison, dashboards, quarantine, root-cause metadata | No semantic memory across failures; no "why + what fixed it" reasoning; flat history, not a graph |
| TestDino | AI-driven root-cause *categorization* (timing, selector instability, etc.) via ML clustering | Categorizes failure *types*, doesn't link specific incidents to specific past resolutions |
| Datadog Test Visibility / CircleCI Test Insights / Mergify Test Insights | Detection bundled into larger observability/CI platforms | Same flat-history limitation; heavy platform lock-in |

**LLM/agent eval harnesses:**
| Tool | What it does | Gap Sentinel fills |
|---|---|---|
| promptfoo | CLI/library for prompt & agent regression testing, CI-integrated | Regression sets are static files engineers maintain by hand; no automatic linking of new failures to past ones |
| DeepEval / Ragas | Metrics-focused eval frameworks (faithfulness, hallucination rate, etc.) | Same — scoring, not memory |
| LangSmith / Braintrust | Tracing + eval + dataset management, collaborative dashboards | Have datasets and traces, but not a reasoning graph connecting "this failure resembles that one" |

**Positioning statement:** *Every existing tool answers "is this test flaky / what's the score." Nothing answers "have we been here before, and what got us out."* That's the wedge, and it's squarely a memory problem, which is why Cognee is the right foundation rather than a generic vector DB bolt-on.

## 10. Success metrics (for hackathon judging, not production KPIs)

The hackathon's actual judging criteria, verbatim from the event page — build toward these directly rather than a self-invented rubric:
1. **Depth of Cognee use** — how deeply and effectively the project leans on the memory lifecycle APIs and the hybrid graph-vector layer. (This is why Section 12a's `improve(session_ids=...)` pattern matters more than a hand-rolled re-weighting scheme — using the documented mechanism *is* the signal being judged.)
2. **Polish/intuitiveness** — is the project pleasant and easy to use, something people would actually adopt.
3. **Clarity of presentation** — do the demo, README, and submission clearly communicate problem → solution → impact.

Sentinel-specific translations of the above:
- Judge can watch `remember → recall → improve → forget` all fire during a live demo, not just be described in slides.
- Recall demonstrably finds a *semantic* match (different stack trace wording, same underlying cause) — not just exact string match, which would undercut the "why Cognee" story.
- Graph visualization is legible and tells a story in under 60 seconds of screen time.
- README and demo narration explicitly name the problem (CI has no memory), the mechanism (Cognee lifecycle), and the outcome (faster root-causing), in that order — matching criterion 3 directly.

### Prize track decision — **resolved: Best Use of Cognee Cloud** (Section 14 #5)

The hackathon has two separate tracks with different prizes: Best Use of Open Source (self-hosted) and Best Use of Cognee Cloud (managed). Team has locked in Cognee Cloud — all `.env`, Section 12, and Section 13 guidance below assumes the managed backend (API/MCP card credentials), zero self-hosted infra to keep alive during the demo.

**Side quest, independent of Sentinel:** Cognee's own GitHub repo pays $100 per accepted PR fixing a listed issue (max 5 per person), open now, not gated on the hackathon start. Worth a team member picking off in downtime if someone's blocked waiting on another piece.

## 11. Phased scope (for the discussion session)

**Must-have for demo:**
- JUnit XML adapter, running against a real live Python/pytest repo (Section 14 #3)
- One deliberately engineered, reproducible flake built into a real feature of that repo — the live trigger for the demo (Section 14 #1)
- `remember` + `recall` fully working — historical context via ~15–20 seeded JSONL records (Section 12a), the *triggering* failure itself live
- One clear before/after moment

**Should-have:**
- `improve` triggered by a manual "confirm same issue" action
- Graph visualization panel

**Cut list if time-constrained:**
- `forget` can be simulated/scripted rather than fully scheduled — still counts for demo purposes if narrated honestly
- GitHub PR bot integration — CLI output alone is fine for demo; PR commenting is a nice-to-have polish item
- Second adapter (promptfoo) — only add if JUnit path is solid with time to spare

## 12. Build-stack decisions: leverage existing Cognee ecosystem, don't hand-roll it

Cognee already ships ready integrations that map directly onto Sentinel's pieces — use them instead of custom glue wherever possible, both to save hackathon hours and because judges score "best use of Cognee" partly on using it idiomatically.

| Priority | Sentinel piece | Use this, not custom code |
|---|---|---|
| 1 | Core ingestion (`remember`/`recall`/`improve`/`forget`) | `cognee` Python SDK directly, called as a plain script from the GitHub Action — no agent framework needed for this part, it's a pipeline not a conversation. Points at Cognee **Cloud** (API/MCP card, managed backends) per the locked-in track decision (Section 10) |
| 2 | Browser MCP + Cognee in one agent context (Layer 1 enrichment) | `cognee_integration_claude` (Claude Agent SDK integration) exposes Cognee as `add_tool`/`search_tool` MCP tools — configure it alongside Playwright MCP in the same `ClaudeAgentOptions.mcp_servers`, don't write custom Cognee-calling glue inside an agent loop |
| 3 | Stretch delivery layer (PR bot) | Cognee's **n8n node** (`GRAPH_COMPLETION` search type) — a webhook → Cognee node → GitHub PR comment workflow can replace a meaningful chunk of custom bot code and may be the difference between the stretch goal being reachable or not |
| Skip | — | Claude Code plugin, Codex, OpenClaw, Dify, Hermes Agent, Cursor, VS Code, Gemini CLI, Cline. These connect *interactive coding assistants* to memory for their own cross-session recall — not relevant to Sentinel, which has no chat agent at its core. (Claude Code's plugin is fine as a personal dev-workflow nicety while building, but it's not part of what ships.) |

### 13a. Data hygiene: JSONL for flat data, graph only where relationships matter

`remember()` always runs the full cognify pipeline (LLM-based entity/relationship extraction into the graph) — expensive, and only worth it where the data has real relationships to extract. The seed set of synthetic historical failures (Section 11, must-have) is flat, list-shaped data, not naturally relational on its own. Prep it as **JSONL and batch-load it**, rather than treating each row as something needing deep graph extraction individually. Reserve the graph-building cost for what actually needs it: the links between a test, its error signature, the file/diff involved, and its eventual fix — that's the part `recall()` needs to traverse, and it's a small fraction of total ingested volume. This keeps ingestion fast and keeps the graph itself legible for the demo visualization rather than noisy.

### 13b. Skill hygiene (if any part is built as Claude Code skills)

- Keep any `skill.md` under 50 lines each, one clear purpose per skill.
- Design for auto-invocation by description, not manual "read this file by path" instructions.
- Minimal markdown — heavy formatting eats context for no retrieval benefit.
- **Watch context pollution specifically around Cognee's own auto-recall behavior.** The Claude Code Cognee plugin recalls into context on *every* prompt by default — good for a general coding assistant, risky for Sentinel if it means unrelated recalled memory silently leaks into every interaction. Scope this deliberately: use a dedicated dataset (mirroring how the plugin supports `COGNEE_SESSION_ID`/dataset scoping) rather than letting recall run unscoped over everything ingested during the hackathon.

## 13. Repo structure & where things run

No separate infrastructure to stand up — Cognee Cloud is already hosted, so this is one GitHub repo with code you write and run like any normal project. Nothing here requires local Cognee hosting.

```
your-repo/
├── .github/
│   └── workflows/
│       └── sentinel.yml            # triggers on test-suite failure in CI
├── sentinel/
│   ├── ingest.py                   # parses JUnit XML → remember() → recall()
│   ├── lifecycle.py                # scheduled improve() / forget() jobs
│   ├── browser_agent.py            # Playwright MCP + Cognee agent (Layer 1 enrichment)
│   ├── seed_data.jsonl             # synthetic historical failures for demo recall
│   ├── pr_comment.py               # [stretch] formats + posts recall result to PR
│   └── config.py                   # Cognee dataset name, env var loading
├── .env.example                    # COGNEE_BASE_URL, COGNEE_API_KEY (never commit real values)
└── (target app + its test suite — whatever repo you're demoing against)
```

### What each file is responsible for

| File | Responsibility |
|---|---|
| `ingest.py` | Entry point for a CI run. Parses the JUnit XML report, extracts failing test name + stack trace + diff/commit context. Calls `remember()` to store it. Immediately calls `recall()` against the new failure and prints/returns the matched history (or "no prior match"). This is the Must-have MVP path (Section 11) — must work standalone before anything else is built. |
| `browser_agent.py` | Only invoked when the failing test is tagged E2E/UI. Runs a small agent wiring Playwright MCP + Cognee's `add_tool`/`search_tool` (`cognee_integration_claude`) in one `ClaudeAgentOptions.mcp_servers` config. Captures DOM snapshot, console errors, network failures, screenshot at failure time, and passes that richer payload into `ingest.py`'s `remember()` call instead of a bare stack trace. |
| `lifecycle.py` | Not triggered per-run. Runs on a schedule (or manually for demo purposes): `improve()` to merge duplicate error signatures into canonical "known issue" nodes and strengthen fix-confirmation edges; `forget()` to prune resolved issues after N stable runs. This is the part most likely to get compressed to a scripted/simulated demo moment if time is short (Section 11, cut list). |
| `seed_data.jsonl` | Flat historical failure records prepared per Section 12a's JSONL guidance — bulk-loaded once via `remember()` so `recall()` has something to match against during the live demo, without individually cognifying each row as if it were relationally rich. |
| `pr_comment.py` | Stretch only. Takes a `recall()` result, verifies it's grounded in what was actually retrieved (drop anything not backed by the recalled data), formats it, posts as a GitHub PR comment via the GitHub API — or, per Section 12, this entire file could instead be replaced by an n8n workflow (webhook → Cognee node → GitHub comment) if the team prefers no-code for this piece. |
| `config.py` | Single place reading `COGNEE_BASE_URL` / `COGNEE_API_KEY` from env, and the Cognee dataset name used for scoping (per Section 12b's context-pollution note — keep Sentinel's data in its own dataset, not mixed with unrelated ingested content). |
| `sentinel.yml` | GitHub Actions workflow: runs the existing test harness as normal, then on failure runs `python sentinel/ingest.py` (and `browser_agent.py` if the failure is E2E-tagged) as a subsequent step, using repo secrets for the Cognee credentials. |

### Local dev flow (before any CI wiring)

1. `cp .env.example .env`, fill in `COGNEE_BASE_URL` + `COGNEE_API_KEY` from the `API/MCP` card on platform.cognee.ai.
2. Run `ingest.py` locally against a sample/fake JUnit XML file — confirm `remember()` and `recall()` work against Cognee Cloud before touching CI at all.
3. Bulk-load `seed_data.jsonl` once, locally, so `recall()` has history to find.
4. Build and test `browser_agent.py` locally against a running instance of the target app, independent of CI.
5. Only once both scripts work standalone: write `sentinel.yml` and move credentials into GitHub Actions secrets.

## 14. Open questions for the working session

1. ~~Do we seed synthetic historical failure data, or try to generate a real flaky/broken repo to fail against live?~~ **Resolved: live repo, real failures.** To avoid the demo depending on naturally-occurring flakiness (which is non-deterministic by definition — that's what "flaky" means), engineer one **deliberate, reproducible flake** into a real feature of the demo app (e.g. an actual race condition or timing dependency) rather than hoping an organic flake fires during the judged window. Historical seed data (Section 12a, JSONL) is still used to give `recall()` prior incidents to find — the live element is the triggering failure itself, not the entire history.
2. ~~How do we do semantic match for `recall`?~~ **Resolved: lean fully on Cognee's built-in retrieval.** No stack-trace preprocessing/normalization — feed raw error text and let Cognee's auto-routed search (semantic similarity + graph traversal) handle matching. Simpler build, and it's a better demonstration of Cognee doing the semantic work rather than us doing it for it.
3. Single demo repo (Python/pytest) or split effort across a JS repo too, for adapter breadth? **No strong preference from the team yet — defaulting to single Python/pytest repo**, matching the JUnit XML adapter already locked in Section 6. A second adapter is scope, not signal the judges are scoring; revisit only if the primary path is solid with time to spare.
4. Who owns the graph-visualization piece vs. the ingestion pipeline vs. the CI integration — three fairly separable workstreams, good for parallelizing across the team.
5. ~~Best Use of Open Source vs. Best Use of Cognee Cloud?~~ **Resolved: Best Use of Cognee Cloud.** `.env` config, Section 12/13, and all setup guidance should assume the managed Cloud backend (API/MCP card credentials), not self-hosted.
6. Stretch delivery layer: n8n workflow or custom `pr_comment.py` (Section 12)? Depends on team's comfort with no-code vs. wanting full control/demo-ability of the code itself.
# SEO Master Bot v2 — Consolidated Audit Report v2.0

**Date:** 2026-02-27
**Agents:** 19 completed (+ 8 supplementary deep-dive runs)
**Codebase:** ~61K lines Python, 28.5K lines tests, 254 files
**Stack:** Python 3.14, Aiogram 3.25, Supabase PostgreSQL 17, Upstash Redis, OpenRouter

---

## Executive Summary

| Severity | Raw (19 agents) | After Dedup | Description |
|----------|-----------------|-------------|-------------|
| CRITICAL | 28 | **25** | Blocks launch or causes data/money loss |
| HIGH | 67 | **55** | Serious UX/business/security issues |
| MEDIUM | 98 | ~85 | Suboptimal but functional |
| LOW | 83 | ~70 | Cosmetic, minor improvements |

**Top 5 systemic issues:**
1. **Auto-publish pipeline is crippled** -- skips ALL web research, cluster context, image settings (Agent 14)
2. **Social pipeline fully built but unreachable** from Dashboard (Agents 3, 6, 9, 11, 19)
3. **No retry/429 handling in ANY of 16 external integrations** -- single failure = lost publish (Agent 4)
4. **152-ФЗ compliance gap** -- no privacy policy, no data deletion, no cross-border transfer consent (Agent 17)
5. **DRY violations: ~2500 lines** -- InaccessibleMessage guard 176x, readiness files 80% identical (Agent 11)

---

## CRITICAL Findings (25 unique, deduplicated)

### C1. Auto-publish skips ALL web research
**Agent:** 14 | **File:** `services/publish.py:360-405`
**Impact:** Auto-published articles have dramatically lower quality -- no competitor analysis, no PAA FAQ, no research data, no dynamic word count, no LSI keywords.
**Fix:** Share `PreviewService._gather_websearch_data()` with `PublishService._generate_article_parallel()`.
**Effort:** 4h | **Priority:** P0

### C2. Auto-publish skips cluster context
**Agent:** 14 | **File:** `services/publish.py:395-400`
**Impact:** All auto-published articles miss secondary phrases, volume/difficulty data. SEO quality score tanks.
**Fix:** After keyword rotation, find matching cluster from `category.keywords` and pass to `generate()`.
**Effort:** 2h | **Priority:** P0

### C3. SimHash content uniqueness NOT implemented
**Agent:** 14 | **File:** `services/` (entire)
**Impact:** Content cannibalization undetected. Same articles published repeatedly for different keywords.
**Fix:** Implement simhash computation, store in `publication_logs.content_hash`, warn at Hamming <= 3.
**Effort:** 8h | **Priority:** P1

### C4. Referral system completely non-functional
**Agents:** 13 | **File:** `routers/start.py`, `bot/middlewares/auth.py:59-66`
**Impact:** `referrer_id` is parsed from `/start ref_XXX` but AuthMiddleware creates UserCreate WITHOUT referrer_id. Referral bonuses never trigger.
**Fix:** Pass referrer_id to UserCreate in AuthMiddleware. Add anti-fraud checks (no self-referral, daily cap).
**Effort:** 2h | **Priority:** P0

### C5. No ChatType.PRIVATE filter -- bot responds in groups
**Agents:** 16 | **File:** `bot/main.py`, `routers/__init__.py`
**Impact:** If added to a group: data leaks, FSM conflicts, unauthorized access, auto-registration of group members.
**Fix:** Add `ChatTypeFilter("private")` to all routers or as outer middleware.
**Effort:** 1h | **Priority:** P0

### C6. Dashboard missing inline buttons for new users
**Agent:** 19 | **File:** `routers/start.py:303-308`
**Impact:** New users see only reply keyboard, no inline CTA buttons. Broken onboarding.
**Fix:** Send two messages: reply keyboard setup + Dashboard with inline buttons.
**Effort:** 1h | **Priority:** P0

### C7. No Privacy Policy or data processing consent (152-ФЗ)
**Agents:** 17 | **File:** N/A
**Impact:** Bot collects names, telegram_id, credentials, passes data to 8+ foreign services (OpenRouter, Firecrawl, DataForSEO, Serper, Supabase, Upstash, Telegraph, YooKassa). Штраф до 6 млн руб.
**Fix:** Privacy policy page + consent at /start + `/privacy` command.
**Effort:** 16h | **Priority:** P0 (legal)

### C8. No data deletion mechanism (right to erasure, 152-ФЗ ст.21)
**Agents:** 17 | **File:** N/A
**Impact:** Users cannot delete their data. FK constraints (token_expenses, payments NO ACTION) block user deletion.
**Fix:** Implement `/delete_account`: soft-delete, anonymize, CASCADE cleanup, Redis purge.
**Effort:** 8h | **Priority:** P0 (legal)

### C9. SENTRY_DSN empty -- errors not tracked
**Agent:** 10 | **File:** Railway env vars
**Impact:** All `sentry_sdk.capture_exception()` calls are no-op. Production errors invisible.
**Fix:** Set SENTRY_DSN in Railway variables. 0 code changes.
**Effort:** 5min | **Priority:** P0

### C10. No HTTP 429 handling in ANY of 16 integrations
**Agent:** 4 | **Files:** All `services/external/*.py`, `services/publishers/*.py`
**Impact:** Rate-limited responses from OpenRouter/DataForSEO/Firecrawl/Serper/WP/VK/Pinterest cause hard failures.
**Fix:** Add retry-after logic to each HTTP client.
**Effort:** 8h | **Priority:** P1

### C11. No retry for ANY publisher (WP, Telegram, VK, Pinterest)
**Agent:** 4 | **Files:** `services/publishers/*.py`
**Impact:** Single network error = lost publication. Auto-publish: tokens charged, AI cost spent ($0.30), but publish failed.
**Fix:** Add retry with exponential backoff (1-2 attempts, 1-3s delay). Don't retry 4xx except 429.
**Effort:** 6h | **Priority:** P1

### C12. OpenRouter: `GenerationRequest.max_retries=2` declared but NEVER used
**Agent:** 4 | **File:** `services/ai/orchestrator.py:231`
**Impact:** Misleading code -- looks like retry is implemented, but it's not. No retry on network errors.
**Fix:** Implement retry logic in `_do_generate()` using `request.max_retries`.
**Effort:** 4h | **Priority:** P1

### C13. Fernet key not validated at startup
**Agent:** 2 | **File:** `bot/config.py:59-60`
**Impact:** If FERNET_KEY is empty/invalid, bot starts "successfully" but ALL platform operations crash at first credential access.
**Fix:** Add `@field_validator("FERNET_KEY")` with `Fernet(key)` validation.
**Effort:** 30min | **Priority:** P0

### C14. Telegraph content leak after cancel+refund
**Agent:** 13 | **File:** `routers/publishing/pipeline/generation.py:835-867`
**Impact:** User generates article, copies Telegraph URL, cancels for full refund. Content stays live. Repeat = infinite free articles.
**Fix:** Delete Telegraph page and Storage images in `cancel_refund` handler BEFORE refund.
**Effort:** 2h | **Priority:** P0

### C15. No Stars refund handler -- financial loss
**Agent:** 16 | **File:** `routers/payments.py`
**Impact:** When Telegram processes Stars refund, user keeps both refunded Stars AND credited tokens.
**Fix:** Add `@router.message(F.refund_star_payment)` handler to debit tokens.
**Effort:** 4h | **Priority:** P1

### C16. Cross-border data transfer without consent (152-ФЗ ст.12)
**Agent:** 17 | **File:** Entire system
**Impact:** All third-party services are foreign (US, China). Company data (name, specialization, keywords) sent to OpenRouter/DeepSeek/Anthropic/Google without disclosure.
**Fix:** Include full list of processors in Privacy Policy. Notify Роскомнадзор.
**Effort:** 8h | **Priority:** P0 (legal)

### C17. Profile forecast underestimates 8x for WP users
**Agent:** 15 | **File:** `services/tokens.py:246`
**Impact:** `avg_cost_per_post = 40` but articles cost ~320. Users see "80 tok/week" when reality is 640.
**Fix:** Differentiate by `platform_type`: 320 for wordpress, 40 for social.
**Effort:** 2h | **Priority:** P1

### C18. cost_usd always returns 0.0
**Agent:** 15 | **File:** `services/ai/orchestrator.py:388`
**Impact:** Cannot track real API costs. Blind to provider price changes. P&L impossible.
**Fix:** Implement OpenRouter `/api/v1/generation?id=` cost lookup.
**Effort:** 8h | **Priority:** P1

### C19. N+1: Sequential DataForSEO calls (up to 20 sequential HTTP requests)
**Agent:** 12 | **File:** `services/keywords.py:176-183`
**Impact:** User waits 60-120s for keyword generation.
**Fix:** `asyncio.gather()` for all seeds within a location.
**Effort:** 2h | **Priority:** P1

### C20. N+1: Sequential DB queries in get_profile_stats()
**Agent:** 12 | **File:** `services/tokens.py:230-241`
**Impact:** 2N DB queries per profile view (N = number of projects).
**Fix:** Batch query `get_categories_by_projects(project_ids)`.
**Effort:** 2h | **Priority:** P1

### C21. Scheduler router 0% test coverage (924 lines)
**Agent:** 18 | **File:** `routers/publishing/scheduler.py`
**Impact:** Key auto-publish configuration code completely untested.
**Fix:** Create `test_scheduler.py` with handler tests.
**Effort:** 16h | **Priority:** P1

### C22. KeywordService 28% coverage
**Agent:** 18 | **File:** `services/keywords.py`
**Impact:** Core data-first keyword pipeline untested. No E03 fallback test.
**Fix:** Test `generate()`, DataForSEO mocks, cluster flow.
**Effort:** 8h | **Priority:** P1

### C23. PreviewService 36% coverage
**Agent:** 18 | **File:** `services/preview.py`
**Impact:** Article generation pipeline largely untested.
**Fix:** Test `generate_article()` with mocked orchestrator/firecrawl/serper.
**Effort:** 8h | **Priority:** P1

### C24. InaccessibleMessage check missing in 14 callback handlers
**Agent:** 16 | **Files:** `connections.py`, `schedules.py`, `profile.py`, `admin/prompts.py`, pipeline handlers
**Impact:** AttributeError or TelegramBadRequest on messages >48h. Users see "Бот не отвечает".
**Fix:** Add `AccessibleMessage` filter to affected routers or use `safe_edit_text()` consistently.
**Effort:** 2h | **Priority:** P1

### C25. "Retry" after generation error -- stale cost estimate
**Agent:** 19 | **File:** `routers/publishing/pipeline/generation.py:380-391`
**Impact:** Retry doesn't re-read image_count. If changed between attempts, wrong charge.
**Fix:** Re-read `image_count` and recalculate cost at retry start.
**Effort:** 1h | **Priority:** P1

---

## HIGH Findings (55 unique -- top 30 listed)

### H1. Social pipeline fully implemented but blocked by `pipeline:social:soon`
**Agents:** 3, 6, 9, 11, 19 | **Fix:** Change `dashboard_kb()` callback to `pipeline:social:start`. **30min**

### H2. Social pipeline resume destroys checkpoint
**Agent:** 3 | **File:** `routers/start.py:575-599` | **Fix:** Implement proper `_route_social_to_step()`. **4h**

### H3. Exit protection doesn't cover generating/publishing states
**Agent:** 3 | **Fix:** Intercept "Меню"/"Отмена" during generation with "Подождите..." **2h**

### H4. `nav:scheduler` button has no handler (dead button)
**Agent:** 6 | **File:** `keyboards/pipeline.py:434` | **Fix:** Add handler or include project_id. **1h**

### H5. Auto-publish errors don't notify users
**Agent:** 19 | **File:** `services/publish.py:306` | **Fix:** Set `notify=user.notify_publications`. **5min**

### H6. "More articles" drops custom image_count
**Agent:** 19 | **File:** `generation.py:984-989` | **Fix:** Add `image_count=_get_image_count(cat)`. **30min**

### H7. Cross-post handlers not implemented -- dead states
**Agent:** 3 | **Fix:** Implement or remove cross-post buttons. **2h (remove) / 16h (implement)**

### H8. Credential decryption failure returns silent `{}` instead of error
**Agent:** 2 | **File:** `db/credential_manager.py:35-51`
**Impact:** If FERNET_KEY changes (e.g., backup restore), ALL connections silently "lose" credentials.
**Fix:** Log CRITICAL + Sentry alert on `InvalidToken`, raise AppError.
**Effort:** 1h

### H9. QStash signing keys not validated at startup
**Agent:** 2 | **File:** `api/__init__.py:29-62`
**Impact:** If signing keys empty, webhook verification behavior undefined.
**Fix:** Validate non-empty at startup. **30min**

### H10. Pinterest OAuth state lacks CSRF protection (no server-side check)
**Agent:** 2 | **File:** `api/oauth.py:32-49`
**Impact:** Attacker can craft URL with arbitrary `state=user_id:project_id`.
**Fix:** Store random state in Redis (TTL 10min), verify on callback. **2h**

### H11. No CORS/CSP security headers on aiohttp API
**Agent:** 2 | **File:** `bot/main.py:307-314`
**Impact:** Pinterest OAuth callback returns HTML without security headers.
**Fix:** Add security headers middleware. **1h**

### H12. Health endpoint exposes diagnostics without auth
**Agent:** 2 | **File:** `api/health.py:20-89`
**Impact:** Anyone can discover internal architecture (db, redis, openrouter, qstash status).
**Fix:** Require Bearer token for detailed health check. **1h**

### H13. publish_handler doesn't check schedule.enabled
**Agent:** 7 | **File:** `api/publish.py:67-120`
**Impact:** User disables schedule -> QStash cron already queued -> next trigger publishes anyway.
**Fix:** Add early return if `not schedule["enabled"]`. **30min**

### H14. Referral bonus unlimited -- no daily cap, no total cap
**Agent:** 13 | **File:** `routers/payments/processing.py:118-146`
**Impact:** 10 fake accounts x bonus per payment = 1500 free tokens/month.
**Fix:** Daily cap (10/day), lifetime cap (5000), anti-sybil checks. **4h**

### H15. No rate limit on expensive AI generations (manual pipeline)
**Agent:** 13 | **Files:** `routers/publishing/pipeline/*/core.py`
**Impact:** User with 5000 tokens can launch 15 parallel $0.30 generations = $4.50/min API cost.
**Fix:** Per-user rate limit: max 3 articles per 10 minutes. **4h**

### H16. YooKassa webhook no idempotency -- double credit possible
**Agent:** 13 | **File:** `api/yookassa.py:23-52`
**Impact:** Replay webhook = double token credit.
**Fix:** Check payment.id exists and status not already "succeeded" before credit. **2h**

### H17. No limit on projects/categories per user (DoS)
**Agent:** 13 | **Fix:** `MAX_PROJECTS_PER_USER = 20`, `MAX_CATEGORIES = 50`. **2h**

### H18. Quality scorer returns None on exception -- bypasses quality gates
**Agent:** 14 | **File:** `services/ai/articles.py:838-856` | **Fix:** Only catch ImportError. **1h**

### H19. Image pipeline incomplete: no negative prompts, no Pillow post-processing
**Agent:** 14 | **Fix:** Implement per spec. **16h**

### H20. Outline H1 vs Article no-H1 contradiction
**Agent:** 14 | **Fix:** Rename `h1` to `title` in outline schema. **1h**

### H21. `platform_rules/` module fully implemented but never used
**Agent:** 14 | **Fix:** Wire into publish flow. **2h**

### H22. Auto-publish doesn't pass `image_settings` to generation
**Agent:** 14 | **File:** `services/publish.py:382` | **Fix:** Add `image_settings`. **30min**

### H23. Routers bypass Service Layer for write operations (150+ instances)
**Agent:** 8 | **Fix:** Extract write ops to services. Phased migration. **40h**

### H24. N+1 in weekly_digest -- 2N DB queries for N users
**Agent:** 12 | **Fix:** SQL aggregation `GROUP BY user_id`. **2h**

### H25. Social post auto-publish charges for non-existent image
**Agent:** 15 | **Fix:** Call `estimate_social_post_cost(images_count=0)`. **30min**

### H26. Stars pricing illusion -- bot receives ~25% of nominal
**Agent:** 15 | **Fix:** Raise Stars amounts or document as intentional. **2h**

### H27. 15 edge cases have zero test coverage
**Agent:** 18 | **Fix:** 1 test per edge case, priority E03/E06/E13/E43/E44. **16h**

### H28. MessageNotModified not caught in ~15 handlers
**Agent:** 16 | **Fix:** Use `safe_edit_text()` everywhere or add global error handler. **2h**

### H29. TelegramForbiddenError (blocked bot) not handled in 4 notification paths
**Agent:** 16 | **Files:** `api/publish.py`, `api/cleanup.py`, `bot/main.py`, `admin/dashboard.py`
**Fix:** Catch specifically, flag user as blocked. **2h**

### H30. No user agreement (оферта) for selling tokens
**Agent:** 17 | **Fix:** Create public offer, link from /start and tariff screen. **8h**

---

## Systemic Issues (cross-cutting)

### S1. DRY violations: ~2500 lines duplicated code
**Agent:** 11 | Key offenders:
- InaccessibleMessage guard: **176 copies** (~530 lines) -> AccessibleMessage filter
- Article/social readiness handlers: **~800 lines** identical -> extract common module
- Ownership check (project/category): **51 copies** (~255 lines) -> `get_owned()` helper
- TokenService construction: **33 copies** -> inject via `dp.workflow_data`
- Platform type strings: **266 occurrences** in 49 files without constants

### S2. No retry/resilience in external integrations
**Agent:** 4 | 0 of 16 integrations handle 429. Only DataForSEO has retry (but only for timeout/connect errors, not 429/5xx). Publishers have zero retry.

### S3. `select("*")` everywhere (37 occurrences)
**Agent:** 12 | Loads encrypted credentials when only `platform_type` needed.

### S4. No content moderation for auto-published content
**Agents:** 17 | AI can generate offensive/illegal content published without human review. Auto-publish through QStash has zero safety checks beyond AI model built-in filters.

### S5. Branding CSS stripped by nh3 -- entire feature is no-op
**Agent:** 14 | `render_markdown()` generates `<style>` block, `sanitize_html()` strips it.
**Fix:** Add `"style"` to NH3_TAGS or use inline styles. **4h**

### S6. Inconsistent DI pattern
**Agent:** 8 | Some services via `dp.workflow_data` (singleton), others created per-handler (TokenService 33x, connections 25x).

---

## Quick Wins (< 2h each, high impact)

| # | Fix | Effort | Impact |
|---|-----|--------|--------|
| 1 | Set SENTRY_DSN in Railway | 5min | C9 -- error tracking |
| 2 | Validate FERNET_KEY at startup | 30min | C13 -- startup safety |
| 3 | Change `pipeline:social:soon` -> `pipeline:social:start` | 30min | H1 -- unblock social |
| 4 | Fix referral `referrer_id` save in AuthMiddleware | 1h | C4 -- referral system |
| 5 | Add `ChatType.PRIVATE` filter | 1h | C5 -- security |
| 6 | Fix new user dashboard (2 messages) | 1h | C6 -- onboarding |
| 7 | Set `notify=user.notify_publications` in publish error | 5min | H5 -- silent failures |
| 8 | Add `image_count` to "more articles" | 30min | H6 -- wrong charge |
| 9 | Check `schedule.enabled` in publish_handler | 30min | H13 -- phantom publishes |
| 10 | Fix social post cost `images_count=0` | 30min | H25 -- overcharge |
| 11 | Add `image_settings` to auto-publish | 30min | H22 -- image quality |
| 12 | Delete Telegraph on cancel_refund | 2h | C14 -- content leak |
| 13 | Validate QStash signing keys at startup | 30min | H9 -- webhook security |
| 14 | Require Bearer token for /health details | 1h | H12 -- info disclosure |

**Total quick wins: ~10h for 14 fixes across 8 CRITICAL + 6 HIGH issues.**

---

## Roadmap (recommended fix order)

### Sprint 1: Launch Blockers (1-2 days) — DONE (PR #77)
- [x] C9: Set SENTRY_DSN (5min) — Railway env var set
- [x] C13: Validate FERNET_KEY at startup (30min) — field_validator in config.py
- [x] C4: Fix referral save (1h) — _parse_referrer_id + DB save in start.py
- [x] C5: ChatType.PRIVATE filter (1h) — root router filter in routers/__init__.py
- [x] C6: New user dashboard buttons (1h) — two-message pattern in start.py
- [x] C14: Telegraph cleanup on cancel (2h) — Telegraph + Storage cleanup in generation.py
- [ ] C15: Stars refund handler (4h) — **moved to Sprint 2**
- [x] H1: Unblock social pipeline (30min) — pipeline:social:start in inline.py
- [x] H5: Auto-publish error notifications (5min) — notify flag in publish.py
- [x] H13: Check schedule.enabled (30min) — schedule check in publish.py
- [x] H22: Auto-publish image_settings (30min) — full dict passthrough in publish.py
- [x] H25: Social post cost fix (30min) — images_count=0 in scheduler.py

### Sprint 2: Auto-Publish Quality + Resilience (2-3 days)
- [ ] C1+C2: Add research + cluster to auto-publish (6h)
- [ ] C10+C11: Retry + 429 handling for publishers (14h)
- [ ] C12: Implement max_retries in orchestrator (4h)
- [ ] C15: Stars refund handler (4h) — moved from Sprint 1
- [ ] C17: Profile forecast fix (2h)
- [ ] C25: Retry stale cost re-read (1h)
- [ ] H18: Quality scorer None bypass (1h)
- [ ] H20: Outline H1->title rename (1h)
- [ ] CR-77a: cancel_refund race condition — Redis NX lock (CodeRabbit Critical)
- [ ] CR-77b: Refactor referral to UsersService.link_referrer (CodeRabbit nitpick)
- [ ] CR-77c: Pass schedule object through publish pipeline (avoid 3x DB load)

### Sprint 3: Security & Compliance (3-4 days)
- [ ] C7+C16: Privacy Policy + consent + cross-border disclosure (16h)
- [ ] C8: Data deletion mechanism (8h)
- [ ] H10: Pinterest OAuth CSRF protection (2h)
- [ ] H11: Security headers middleware (1h)
- [ ] H14: Referral limits + anti-fraud (4h)
- [ ] H15: Generation rate limits (4h)
- [ ] H16: YooKassa idempotency (2h)
- [ ] H17: Project/category limits (2h)
- [ ] H30: User agreement (оферта) (8h)

### Sprint 4: Performance (2-3 days)
- [ ] C19: Parallelize DataForSEO calls (2h)
- [ ] C20: Batch profile stats queries (2h)
- [ ] H24: Batch digest queries (2h)
- [ ] S3: Replace `select("*")` (8h)
- [ ] S5: Fix branding CSS stripping (4h)

### Sprint 5: Test Coverage (3-5 days)
- [ ] C21: Scheduler router tests (16h)
- [ ] C22: KeywordService tests (8h)
- [ ] C23: PreviewService tests (8h)
- [ ] H27: 15 missing edge case tests (16h)

### Sprint 6: Architecture & DRY (5-7 days)
- [ ] S1: InaccessibleMessage filter (2h, saves 530 lines)
- [ ] S1: Extract readiness common module (8h, saves 800 lines)
- [ ] S1: Ownership helper + bot/constants.py (4h)
- [ ] H23: Extract write ops to services (40h)
- [ ] S6: Consistent DI via workflow_data (8h)

### Deferred (v3 or post-launch)
- C3: SimHash implementation (8h)
- C18: OpenRouter cost tracking (8h)
- H19: Full image pipeline (16h)
- S4: Content moderation for auto-publish (16h)
- Cross-posting implementation (F6.4)

---

## Agent Summary Table

| # | Agent | Scope | C | H | M | L | Top finding |
|---|-------|-------|---|---|---|---|-------------|
| 1 | Financial integrity | Balance, refunds, payments | 0 | 0 | 4 | 6 | Mature architecture, no critical issues |
| 2 | Security | Auth, encryption, injection | 2 | 5 | 8 | 7 | Fernet not validated, health no auth |
| 3 | FSM & Pipeline | 16 FSMs, transitions | 1 | 4 | 6 | 4 | Cross-post dead states |
| 4 | External integrations | 16 APIs resilience | 4 | 6 | 7 | 6 | No retry/429 in any integration |
| 5 | Data model & DB | 13 tables, indices | 0 | 0 | 3 | 4 | Schema solid, all 13 tables match spec |
| 6 | Navigation & callbacks | Buttons, handlers, UX | 0 | 3 | 3 | 4 | Dead nav:scheduler button |
| 7 | Scheduler & QStash | Auto-publish lifecycle | 1 | 4 | 5 | 4 | schedule.enabled not checked |
| 8 | Architecture | Layers, DI, error handling | 1 | 3 | 10 | 6 | 150+ router-level writes bypass services |
| 9 | Spec compliance | 8 specs vs code | 0 | 1 | 2 | 4 | Social pipeline stub |
| 10 | Prod-readiness | Deploy, monitoring, scale | 1 | 2 | 4 | 6 | SENTRY_DSN empty |
| 11 | DRY & consistency | Duplication, naming | 1 | 4 | 6 | 4 | InaccessibleMessage 176x, readiness 800 lines |
| 12 | Performance | N+1, caching, indices | 3 | 6 | 7 | 4 | 20 sequential DataForSEO calls |
| 13 | Anti-fraud | Abuse scenarios | 1 | 4 | 4 | 3 | Telegraph content leak on cancel |
| 14 | AI pipeline & content | Multi-step, quality | 3 | 5 | 7 | 5 | Auto-publish skips research |
| 15 | Economics & unit-econ | P&L, pricing, margins | 2 | 5 | 4 | 2 | Forecast 8x underestimate |
| 16 | Telegram edge cases | Bot API, payments | 1 | 3 | 4 | 4 | No Stars refund handler |
| 17 | Compliance & 152-ФЗ | Privacy, moderation | 2 | 3 | 4 | 4 | No Privacy Policy, no data deletion |
| 18 | Test coverage | pytest, mocks, E2E | 3 | 5 | 5 | 4 | Scheduler 0% coverage |
| 19 | E2E walkthrough | User journey trace | 2 | 4 | 5 | 4 | Dashboard no inline buttons |
| | **TOTAL (raw)** | | **28** | **67** | **98** | **83** |

### Supplementary deep-dive runs (8 agents resumed)
Additional findings from resumed agents (merged into main report above):
- Agent 2+: Authorization/ownership deep-dive (+6M, +3L)
- Agent 4+: Auto-publish lifecycle (+2C, +4H, +6M)
- Agent 7+: Publish handler checks, TOCTOU in publish.py (+2C, +4H)
- Agent 11+: Quantified DRY: 176x guards, 266x platform strings, 54x callback parsing
- Agent 13+: Telegraph leak, YooKassa metadata trust (+2C, +4H)
- Agent 16+: Stars refund, 48h edit limit, TelegramForbiddenError in 4 paths (+2C, +5H)
- Agent 17+: Cross-border transfer, YMYL in social posts, prompt injection (+3C, +3H)

---

## Positive Findings

1. **Financial architecture: mature** -- RPC charge/refund/credit atomic, CAS fallback, symmetric operations (Agent 1: 0 CRITICAL)
2. **DB schema: solid** -- All 13 tables match spec, CASCADE chains correct, all FK indexed, covering index for rotation (Agent 5: 0 CRITICAL)
3. **Services layer: ZERO Aiogram dependencies** -- fully decoupled, web-ready
4. **No SQL injection** -- all queries parameterized via PostgREST (113 `html.escape()` calls in 16 files)
5. **No bare `except: pass`** -- all 75 exception blocks have logging
6. **Ownership checks in 95%+ handlers** -- callback_data tampering protected
7. **QStash signatures verified** -- all 4 webhook handlers protected
8. **nh3 HTML sanitization** -- XSS prevented before publishing (articles + social posts)
9. **Structured logging** -- structlog JSON with correlation_id everywhere
10. **Fernet encryption** -- credentials encrypted in DB, decrypt only in repository layer
11. **All 16 FSM StatesGroup match spec exactly** -- 0 state count mismatches
12. **Tests: 1673 passed, 0 failed** -- stable, no flaky tests
13. **API coverage 95.4%** -- payment/webhook handlers well tested
14. **All dependencies have permissive licenses** (pymorphy3 is MIT, not LGPL)
15. **Graceful shutdown implemented** -- SIGTERM -> drain -> refund active generations
16. **Parallel article generation** -- text + images via asyncio.gather (96s -> 56s)
17. **BaseRepository pattern** -- common CRUD helpers, no copy-paste in DB layer
18. **Publisher ABC interface** -- 4 publishers follow clean contract
19. **Rate limiting: 2 levels** -- middleware (anti-flood) + service (per-action)
20. **SecretStr for all API keys** -- never leaked in repr/logs

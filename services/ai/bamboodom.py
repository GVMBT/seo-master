"""AI article generation for bamboodom.ru blog (Session 4A).

Architecture rationale:
- Bypasses `PromptEngine` (DB-backed) — bamboodom uses a self-contained YAML
  loaded directly from disk, because our prompt shape (JSON blocks, not
  Markdown/HTML) is incompatible with the existing prompt contract.
- Bypasses `AIOrchestrator` — we use a minimal httpx-based OpenRouter client
  because we need tight control over JSON parsing + retry on malformed output.
  Reusing the orchestrator would require a prompt registered in DB + a
  retry strategy that doesn't match our needs.
- Keeps `ArticleService`, `PromptEngine`, `ContentValidator` untouched (per
  side B directive in SESSION_4A_ANSWERS.md).

Flow:
    context = await _load_context(redis)              # blog_context + codes
    prompt = _build_messages(material, keyword, ctx)
    raw = await _call_openrouter(prompt, MODEL_CHAIN)  # with 1 JSON-retry
    draft = _parse_draft(raw)                          # strict validation
    issues = validator.validate(draft, forbidden)      # regex layers 1+2
    if issues: retry once (auto). still issues → manual.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import sentry_sdk
import structlog
import yaml

from integrations.bamboodom import BamboodomClient

log = structlog.get_logger()

# Model chains for bamboodom pipeline. Production pays premium for quality
# (article) and uses Haiku for cheap validation checks (layer 3 in 4B).
_MODEL_CHAIN_ARTICLE: tuple[str, ...] = (
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-opus-4-6",
)
_MODEL_CHAIN_VALIDATE: tuple[str, ...] = (
    "anthropic/claude-haiku-4-5",
    "deepseek/deepseek-v3.2",
)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_GENERATION_TIMEOUT = 120.0  # seconds — article generation can take ~30-60s
_MAX_JSON_RETRIES = 1  # strict JSON parse retry budget (per side B §Б1)
_MAX_VALIDATION_RETRIES = 1  # auto-retry on regex violation (per §В2)

# Prompt template file — loaded once into module-level cache.
_PROMPT_PATH = Path(__file__).parent / "prompts" / "bamboodom_article_v1.yaml"
_KNOWLEDGE_BASE_PATH = Path(__file__).parent.parent.parent / "docs" / "bamboodom" / "knowledge_base.md"

MaterialCategory = Literal["wpc", "flex", "reiki", "profiles"]

# Block types the server accepts (we use a safe subset in 4A).
_ALLOWED_BLOCK_TYPES: frozenset[str] = frozenset({"h2", "p", "list", "product", "callout", "cta"})

# How many article codes to show the model per material. Too few — model
# picks wrong article; too many — prompt bloats. 30 per material works.
_CODES_SAMPLE_SIZE = 30


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BamboodomArticleDraft:
    """Validated draft — what gets shown in FSM preview and published via API."""

    title: str
    excerpt: str
    blocks: list[dict[str, Any]]
    seo: dict[str, str] = field(default_factory=dict)

    def to_publish_payload(self) -> dict[str, Any]:
        """Shape the draft for blog_publish."""
        payload: dict[str, Any] = {
            "title": self.title,
            "excerpt": self.excerpt,
            # In sandbox mode we want instant preview (no draft gate). When we
            # move to production in 4B this flag flips back to True.
            "draft": False,
            "blocks": self.blocks,
        }
        if self.seo:
            payload["seo"] = self.seo
        return payload


@dataclass(slots=True)
class ValidationIssue:
    kind: Literal["forbidden_claim", "price_in_text", "bad_block_type", "bad_article"]
    detail: str
    block_index: int | None = None


@dataclass(slots=True)
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


# ---------------------------------------------------------------------------
# Validator — regex layers 1 (forbidden_claims) + 2 (prices). Layer 3 in 4B.
# ---------------------------------------------------------------------------


class BamboodomValidator:
    """Regex-based content checks. Mirrors side B expectations from SESSION_4A_ANSWERS."""

    # Prices: "2500 руб", "от 1000 ₽", "около 500 р.", "~750 RUB". Any integer
    # close to a currency marker is suspect — product-block is the only legal
    # way to mention prices.
    _PRICE_RE = re.compile(
        r"\b\d{2,6}\s*(?:руб\.?|₽|RUB|р\.)\b",
        flags=re.IGNORECASE,
    )

    def __init__(self, forbidden_claims: list[str]) -> None:
        # Normalize all forbidden claims to lowercase for case-insensitive match.
        self._forbidden = [c.strip().lower() for c in forbidden_claims if c and c.strip()]

    def validate(  # noqa: C901  — tight regex-by-block check; splitting up harms readability
        self,
        draft: BamboodomArticleDraft,
        *,
        valid_article_codes: frozenset[str] | None = None,
    ) -> ValidationResult:
        """Run all regex checks on a draft. Returns a list of issues."""
        result = ValidationResult()

        for idx, block in enumerate(draft.blocks):
            btype = block.get("type")

            # Block type whitelist
            if btype not in _ALLOWED_BLOCK_TYPES:
                result.issues.append(
                    ValidationIssue(
                        kind="bad_block_type",
                        detail=f"Block #{idx} has type={btype!r}, allowed: {sorted(_ALLOWED_BLOCK_TYPES)}",
                        block_index=idx,
                    )
                )
                continue

            # Product-block: article must be in known codes
            if btype == "product":
                article = str(block.get("article", "")).strip()
                if valid_article_codes is not None and article and article not in valid_article_codes:
                    result.issues.append(
                        ValidationIssue(
                            kind="bad_article",
                            detail=f"Unknown article code {article!r} in block #{idx}",
                            block_index=idx,
                        )
                    )
                continue  # don't check text content on product blocks

            # CTA-block: href is required
            if btype == "cta":
                href = str(block.get("href", "")).strip()
                if not href:
                    result.issues.append(
                        ValidationIssue(
                            kind="bad_block_type",
                            detail=f"CTA block #{idx} missing href",
                            block_index=idx,
                        )
                    )

            # Gather text content from block (may be in text/title/items).
            text_parts: list[str] = []
            for field_name in ("text", "title"):
                v = block.get(field_name)
                if isinstance(v, str):
                    text_parts.append(v)
            items = block.get("items")
            if isinstance(items, list):
                text_parts.extend(str(i) for i in items if isinstance(i, (str, int)))
            combined = "\n".join(text_parts).strip()
            if not combined:
                continue

            # Check forbidden claims (case-insensitive substring match)
            lowered = combined.lower()
            for claim in self._forbidden:
                if claim and claim in lowered:
                    result.issues.append(
                        ValidationIssue(
                            kind="forbidden_claim",
                            detail=f"Forbidden phrase {claim!r} in block #{idx}",
                            block_index=idx,
                        )
                    )

            # Check price-like patterns
            for m in self._PRICE_RE.finditer(combined):
                result.issues.append(
                    ValidationIssue(
                        kind="price_in_text",
                        detail=f"Price-like token {m.group(0)!r} in block #{idx} — use product-block",
                        block_index=idx,
                    )
                )

        # Sanity-check title/excerpt against forbidden claims too
        title_low = draft.title.lower()
        excerpt_low = draft.excerpt.lower()
        for claim in self._forbidden:
            if claim and (claim in title_low or claim in excerpt_low):
                result.issues.append(
                    ValidationIssue(
                        kind="forbidden_claim",
                        detail=f"Forbidden phrase {claim!r} in title/excerpt",
                    )
                )

        return result


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BamboodomGenerationError(Exception):
    """Raised when AI generation fails after all retries / fallbacks."""


class BamboodomArticleService:
    """Generates blog articles for bamboodom.ru using Claude Sonnet via OpenRouter.

    NOT thread-safe (holds no mutable state). Cheap to construct per-call.
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        openrouter_api_key: str,
        bamboodom_client: BamboodomClient,
    ) -> None:
        self._http = http_client
        self._api_key = openrouter_api_key
        self._bamboodom = bamboodom_client

    # ----- public API -------------------------------------------------

    async def generate_and_validate(
        self,
        *,
        material: MaterialCategory,
        keyword: str,
        current_date_iso: str,
    ) -> tuple[BamboodomArticleDraft, ValidationResult]:
        """High-level: fetch context → generate draft → validate → (auto-retry once).

        Returns the final draft + validation result. Caller decides what to do
        with residual issues (show to operator, publish anyway, etc).
        """
        # 1. Load cached context (falls back to fresh fetch if cache is cold)
        context, codes = await self._load_context()
        valid_codes = _collect_valid_codes(codes)
        forbidden = list(getattr(context, "forbidden_claims", None) or [])

        validator = BamboodomValidator(forbidden)
        system, user = self._build_messages(
            material=material,
            keyword=keyword,
            current_date=current_date_iso,
            context_obj=context,
            codes_obj=codes,
        )

        draft: BamboodomArticleDraft | None = None
        validation_issues: list[str] = []

        for attempt in range(_MAX_VALIDATION_RETRIES + 1):
            messages = self._augment_messages_after_validation(system, user, validation_issues)
            raw_reply = await self._call_with_json_retry(messages)
            draft = _parse_draft(raw_reply)

            result = validator.validate(draft, valid_article_codes=valid_codes)
            if result.ok:
                log.info(
                    "bamboodom_ai_generate_ok",
                    material=material,
                    keyword=keyword,
                    blocks=len(draft.blocks),
                    attempt=attempt,
                )
                return draft, result

            # Failed validation — log every attempt (per §В2 guidance).
            log.warning(
                "bamboodom_ai_validation_failed",
                material=material,
                keyword=keyword,
                attempt=attempt,
                issues=[i.detail for i in result.issues],
            )
            sentry_sdk.capture_message(
                "bamboodom AI validation failed",
                level="warning",
                extras={
                    "material": material,
                    "keyword": keyword,
                    "attempt": attempt,
                    "issues": [i.detail for i in result.issues],
                },
            )

            if attempt >= _MAX_VALIDATION_RETRIES:
                # Give up — return last draft + issues; operator decides.
                return draft, result

            # Accumulate issues for next attempt's prompt augmentation.
            validation_issues.extend(i.detail for i in result.issues)

        # Unreachable (loop always returns), but keep type-checker happy.
        if draft is None:  # pragma: no cover
            raise BamboodomGenerationError("no draft produced")
        return draft, validator.validate(draft, valid_article_codes=valid_codes)

    # ----- internals --------------------------------------------------

    async def _load_context(self):
        """Fetch blog_context + blog_article_codes (uses Session 2A cache)."""
        ctx_resp, _ = await self._bamboodom.get_context(force_refresh=False)
        codes_resp, _ = await self._bamboodom.get_article_codes(force_refresh=False)
        return ctx_resp, codes_resp

    def _build_messages(
        self,
        *,
        material: MaterialCategory,
        keyword: str,
        current_date: str,
        context_obj: Any,
        codes_obj: Any,
    ) -> tuple[str, str]:
        """Render the YAML prompt template with live context."""
        template = _load_prompt_template()
        kb_text = _load_knowledge_base()
        forbidden_lines = (
            "\n".join(f"- {c}" for c in (getattr(context_obj, "forbidden_claims", None) or [])) or "(из knowledge base)"
        )
        codes_sample = _format_codes_sample(codes_obj, material)

        def _fill(text: str) -> str:
            return (
                text.replace("<<knowledge_base>>", kb_text)
                .replace("<<forbidden_claims_list>>", forbidden_lines)
                .replace("<<material_category>>", material)
                .replace("<<keyword>>", keyword)
                .replace("<<current_date>>", current_date)
                .replace("<<article_codes_sample>>", codes_sample)
            )

        return _fill(template["system"]), _fill(template["user"])

    @staticmethod
    def _augment_messages_after_validation(
        system: str,
        user: str,
        prior_issues: list[str],
    ) -> list[dict[str, str]]:
        """Inject previous validation feedback into the user turn."""
        if not prior_issues:
            return [{"role": "system", "content": system}, {"role": "user", "content": user}]

        feedback = (
            "\n\nПРЕДЫДУЩИЙ ОТВЕТ НЕ ПРОШЁЛ ВАЛИДАЦИЮ:\n"
            + "\n".join(f"- {issue}" for issue in prior_issues)
            + "\n\nИсправь и верни новую версию строго в формате JSON без обёрток."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user + feedback},
        ]

    async def _call_with_json_retry(self, messages: list[dict[str, str]]) -> str:
        """Call OpenRouter; on invalid JSON reply — retry once with strict prompt."""
        raw = await self._call_openrouter(messages, _MODEL_CHAIN_ARTICLE)
        try:
            _parse_draft(raw)  # purely validates the JSON; discard result
            return raw
        except BamboodomGenerationError:
            log.warning("bamboodom_ai_json_invalid_first_try", reply_preview=raw[:300])
            # Retry with a stricter nudge.
            strict_messages = [
                *messages,
                {
                    "role": "assistant",
                    "content": raw[:4000],  # truncate very long replies for the history
                },
                {
                    "role": "user",
                    "content": (
                        "Твой ответ не был валидным JSON. Верни ТОЛЬКО JSON-объект "
                        '{"title":...,"excerpt":...,"blocks":[...]}, без markdown, '
                        "без обёрток ``` и без пояснений до или после."
                    ),
                },
            ]
            return await self._call_openrouter(strict_messages, _MODEL_CHAIN_ARTICLE)

    async def _call_openrouter(
        self,
        messages: list[dict[str, str]],
        model_chain: tuple[str, ...],
    ) -> str:
        """POST /chat/completions with fallback across the model chain."""
        last_exc: Exception | None = None
        for model in model_chain:
            try:
                resp = await self._http.post(
                    _OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://bamboodom.ru",
                        "X-Title": "SEO Master Bamboodom",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": 8000,
                        "temperature": 0.6,
                    },
                    timeout=_GENERATION_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                log.info(
                    "bamboodom_ai_call_ok",
                    model=model,
                    usage=data.get("usage"),
                )
                return content  # type: ignore[no-any-return]
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                log.warning("bamboodom_ai_call_failed", model=model, error=str(exc))
                last_exc = exc
                continue

        raise BamboodomGenerationError(f"All models failed: {[m for m in model_chain]}; last: {last_exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_prompt_template() -> dict[str, str]:
    """Load the YAML prompt. Raises on missing file or malformed YAML."""
    if not _PROMPT_PATH.exists():
        raise BamboodomGenerationError(f"prompt template not found: {_PROMPT_PATH}")
    with _PROMPT_PATH.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict) or "system" not in raw or "user" not in raw:
        raise BamboodomGenerationError(f"prompt template has unexpected shape: {_PROMPT_PATH}")
    return {"system": raw["system"], "user": raw["user"]}


def _load_knowledge_base() -> str:
    """Load the markdown knowledge base for inline injection into the prompt."""
    if not _KNOWLEDGE_BASE_PATH.exists():
        # Non-fatal — we can still generate, just without company context.
        log.warning("bamboodom_kb_missing", path=str(_KNOWLEDGE_BASE_PATH))
        return "(knowledge base not available)"
    return _KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")


def _collect_valid_codes(codes_obj: Any) -> frozenset[str]:
    """Flatten category-wise code lists into a single lookup set."""
    out: set[str] = set()
    for category_name, count in codes_obj.categories().items():
        # categories() returns only counts; access the raw list via getattr/extras
        raw_list = getattr(codes_obj, category_name, None)
        if isinstance(raw_list, list):
            out.update(str(c) for c in raw_list if isinstance(c, str))
        else:
            extras = getattr(codes_obj, "__pydantic_extra__", None) or {}
            extra_list = extras.get(category_name)
            if isinstance(extra_list, list):
                out.update(str(c) for c in extra_list if isinstance(c, str))
        _ = count  # unused, kept for clarity
    return frozenset(out)


def _format_codes_sample(codes_obj: Any, material: MaterialCategory) -> str:
    """Format a trimmed list of codes for the material category into prompt text."""
    lines: list[str] = []
    # Always include the chosen material's codes prominently.
    own_codes = getattr(codes_obj, material, None) or []
    if not isinstance(own_codes, list):
        extras = getattr(codes_obj, "__pydantic_extra__", None) or {}
        own_codes = extras.get(material, []) if isinstance(extras, dict) else []
    if isinstance(own_codes, list) and own_codes:
        sample = own_codes[:_CODES_SAMPLE_SIZE]
        lines.append(f"Основная категория ({material}): {', '.join(sample)}")
        if len(own_codes) > len(sample):
            lines.append(f"…всего {len(own_codes)} артикулов этой категории")

    # If material is accessory (profiles/reiki), also include some WPC codes
    # — per prompt guidance they should not appear alone.
    if material in ("profiles", "reiki"):
        wpc = getattr(codes_obj, "wpc", None) or []
        if isinstance(wpc, list) and wpc:
            lines.append(f"Сопутствующие WPC: {', '.join(wpc[:10])}…")

    return "\n".join(lines) if lines else "(список временно недоступен)"


def _parse_draft(raw_reply: str) -> BamboodomArticleDraft:
    """Strict JSON parse + shape validation. Raises BamboodomGenerationError."""
    # Models sometimes wrap JSON in ```json ... ``` or add a prose preamble.
    # Try to recover the first {...} block as a last resort.
    candidate = raw_reply.strip()
    if candidate.startswith("```"):
        # Strip fenced code block header + trailing fence
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```\s*$", "", candidate)
    # Find first top-level {...}
    first_brace = candidate.find("{")
    last_brace = candidate.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = candidate[first_brace : last_brace + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise BamboodomGenerationError(f"invalid JSON from model: {exc}") from exc

    if not isinstance(parsed, dict):
        raise BamboodomGenerationError(f"model returned {type(parsed).__name__}, expected object")
    title = parsed.get("title")
    excerpt = parsed.get("excerpt")
    blocks = parsed.get("blocks")
    if not isinstance(title, str) or not title.strip():
        raise BamboodomGenerationError("missing/empty title in model response")
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise BamboodomGenerationError("missing/empty excerpt in model response")
    if not isinstance(blocks, list) or not blocks:
        raise BamboodomGenerationError("missing/empty blocks in model response")
    # Coerce blocks to list[dict]
    cleaned_blocks: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict) or "type" not in block:
            raise BamboodomGenerationError(f"block #{idx} is not a dict or missing 'type': {block!r}")
        cleaned_blocks.append(block)

    # Optional: seo block (meta_title / meta_description)
    seo_raw = parsed.get("seo")
    seo: dict[str, str] = {}
    if isinstance(seo_raw, dict):
        meta_title = seo_raw.get("meta_title")
        meta_description = seo_raw.get("meta_description")
        if isinstance(meta_title, str) and meta_title.strip():
            seo["meta_title"] = meta_title.strip()[:80]
        if isinstance(meta_description, str) and meta_description.strip():
            seo["meta_description"] = meta_description.strip()[:200]

    return BamboodomArticleDraft(
        title=title.strip(),
        excerpt=excerpt.strip(),
        blocks=cleaned_blocks,
        seo=seo,
    )

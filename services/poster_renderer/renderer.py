"""Local deterministic poster rendering, deliberately independent of the bridge.

Trust boundary: only authenticated application code may construct these inputs.
``authorization_verifier`` MUST revalidate an application-issued receipt against
current source, identity/configuration, rights, content/layout and quote records.
It is called before reading image bytes and before returning output. A dataclass,
hash, reference, client Boolean, or successful PNG is not that authorization.
Never deserialize an HTTP/model payload into an authorization receipt directly.

Inputs are bytes, reviewed copy and a restricted layout, never a URL or path.
The font loader checks a small server-owned OS-font allowlist and actual cmap
coverage. No downloads, source image rewrites, financial arithmetic, delivery,
ima verification, visual-model review or publication are performed here.

Subset: neutral_light, 1080x1440/1920, store_poster_v1 safe template, or complete
constraint_regions. Tags remain metadata. All other nonempty poster text must
be visible. A quote must have its exact service-formatted cash in reviewed copy;
the complete service purchase plan is also rendered into separate PNG card(s).
Quotes additionally require the service's customer_visible_breakdown_sentence;
this core will not derive merchandise/fees/credits/cash text from numeric fields.
Unknown layouts/fields or overflow fail closed rather than shrink/truncate copy.
"""

from __future__ import annotations

import bisect
import hashlib
import io
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import struct
from typing import Any, Callable, Mapping
import unicodedata
import warnings


class PosterRenderError(ValueError):
    def __init__(self, code: str, message: str, text_refs: tuple[str, ...] = ()):
        super().__init__(message)
        self.code, self.text_refs = code, text_refs


@dataclass(frozen=True)
class RenderScope:
    tenant_ref: str
    store_ref: str
    actor_ref: str
    task_version_ref: str
    purpose_ref: str
    destination_ref: str
    region: str
    product_ref: str
    configuration_ref: str
    source_mode: str
    task_kind: str
    material_policy: str


@dataclass(frozen=True)
class VerifiedAsset:
    asset_id: str
    source_ref_id: str
    source_version: str
    source_snapshot_ref: str
    source_mode: str
    product_ref: str
    configuration_ref: str
    sha256: str
    width: int
    height: int
    image_bytes: bytes = field(repr=False)


@dataclass(frozen=True)
class QuoteAuthorization:
    quote_ref: str
    quote_version: str
    validation_ref: str
    validation_version: str
    purchase_plan_check_ref: str
    purchase_plan_check_version: str
    summary_sha256: str
    dependency_hash: str
    valid_until: str
    quote_status: str
    client_quote_allowed: bool


@dataclass(frozen=True)
class RenderAuthorization:
    scope: RenderScope
    receipt_ref: str
    receipt_version: str
    content_ref: str
    content_version: str
    content_check_ref: str
    content_check_version: str
    layout_ref: str
    layout_version: str
    source_check_ref: str
    source_check_version: str
    product_identity_check_ref: str
    product_identity_check_version: str
    configuration_check_ref: str
    configuration_check_version: str
    rights_check_ref: str
    rights_check_version: str
    content_sha256: str
    layout_sha256: str
    asset_metadata_sha256: str
    valid_until: str
    quote_required: bool
    ima_check_ref: str | None = None
    ima_check_version: str | None = None
    quote: QuoteAuthorization | None = None


@dataclass(frozen=True)
class PosterRequest:
    scope: RenderScope
    draft: Mapping[str, Any] = field(repr=False)
    layout: Mapping[str, Any] = field(repr=False)
    asset: VerifiedAsset = field(repr=False)
    authorization: RenderAuthorization
    customer_quote_summary: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class PNGPage:
    png_bytes: bytes = field(repr=False)
    sha256: str
    width: int
    height: int
    text_boxes: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class PosterResult:
    poster: PNGPage
    purchase_plan_pages: tuple[PNGPage, ...]
    hero_bbox: tuple[int, int, int, int]
    bindings: Mapping[str, Any]
    status: str = "rendered_pending_visual_review"
    requires_visual_review: bool = True
    export_authorized: bool = False
    competition_eligible: bool = False


_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)
_FONTS = {"headline": 58, "subtitle": 32, "benefit": 34,
          "conditions": 28, "cta": 34}
_LEVELS = (("base_price", "基准价"), ("platform_discount", "平台优惠"),
           ("identity_benefit", "身份权益"),
           ("trade_in_national_subsidy", "换新国补"))


def _fail(code: str, message: str, *refs: str) -> None:
    raise PosterRenderError(code, message, tuple(refs))


def canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("INVALID_JSON", "Input must be finite UTF-8 JSON data.")
    return hashlib.sha256(encoded).hexdigest()


def asset_metadata_hash(asset: VerifiedAsset) -> str:
    if not isinstance(asset, VerifiedAsset):
        _fail("INVALID_ASSET", "Only server-resolved asset bytes are accepted.")
    return canonical_hash({key: value for key, value in vars(asset).items()
                           if key != "image_bytes"})


def _ref(value: Any) -> None:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        _fail("MISSING_VERIFICATION", "A scoped verification reference/version is missing.")


def _digest(value: Any) -> None:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        _fail("MISSING_VERIFICATION", "A dependency SHA256 is missing.")


def _expiry(value: Any, now: datetime) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed <= now:
            raise ValueError
    except (TypeError, AttributeError, ValueError):
        _fail("EXPIRED_VERIFICATION", "Verification is expired or lacks an explicit timezone.")


def _text(value: Any, ref: str, limit: int = 5000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _fail("INVALID_TEXT", "Required reviewed text is missing or too long.", ref)
    if any(unicodedata.category(c).startswith("C") and c != "\n" for c in value):
        _fail("INVALID_TEXT", "Control and invisible formatting characters are not supported.", ref)
    return value


def _validate_receipt(req: PosterRequest, now: datetime,
                      verifier: Callable[[RenderAuthorization], bool]) -> None:
    if not isinstance(req, PosterRequest) or not isinstance(req.scope, RenderScope):
        _fail("UNTRUSTED_INPUT", "Server-built request and scope are required.")
    auth = req.authorization
    if not isinstance(auth, RenderAuthorization) or auth.scope != req.scope:
        _fail("SCOPE_MISMATCH", "Authorization does not match the current task scope.")
    for key, value in vars(req.scope).items():
        _ref(value)
    if req.scope.source_mode not in {"local_snapshot", "ima_live", "hybrid_verified"}:
        _fail("INVALID_SCOPE", "Unknown source mode.")
    if req.scope.task_kind not in {"product_intro", "marketing", "full_package"}:
        _fail("INVALID_SCOPE", "Unsupported task kind.")
    if req.scope.material_policy not in {"local_development", "competition_strict"}:
        _fail("INVALID_SCOPE", "Unknown material policy.")
    if type(auth.quote_required) is not bool:
        _fail("INVALID_SCOPE", "Quote policy must be a trusted Boolean.")
    if req.scope.task_kind in {"marketing", "full_package"} and not auth.quote_required:
        _fail("QUOTE_REQUIRED", "Formal marketing requires the verified purchase plan.")
    for key, value in vars(auth).items():
        if key.endswith(("_ref", "_version")) and not key.startswith("ima_"):
            _ref(value)
    for key in ("content_sha256", "layout_sha256", "asset_metadata_sha256"):
        _digest(getattr(auth, key))
    _expiry(auth.valid_until, now)
    if req.scope.material_policy == "competition_strict":
        if req.scope.source_mode not in {"ima_live", "hybrid_verified"}:
            _fail("IMA_SOURCE_REQUIRED", "Competition material requires actual ima verification.")
        _ref(auth.ima_check_ref)
        _ref(auth.ima_check_version)
    if canonical_hash(req.draft) != auth.content_sha256:
        _fail("CONTENT_VERSION_MISMATCH", "Copy differs from the reviewed content version.")
    if canonical_hash(req.layout) != auth.layout_sha256:
        _fail("LAYOUT_VERSION_MISMATCH", "Layout differs from the approved layout version.")
    if asset_metadata_hash(req.asset) != auth.asset_metadata_sha256:
        _fail("ASSET_VERSION_MISMATCH", "Asset metadata differs from its verified version.")
    if not callable(verifier):
        _fail("AUTHORIZATION_REQUIRED", "An application receipt verifier is required.")
    try:
        allowed = verifier(auth)
    except Exception:
        _fail("AUTHORIZATION_DENIED", "Current receipt verification failed.")
    if allowed is not True:
        _fail("AUTHORIZATION_DENIED", "Current receipt verification denied rendering.")


def _copy(req: PosterRequest) -> dict[str, tuple[str, str]]:
    d = req.draft
    if (not isinstance(d, dict) or d.get("status") != "ready" or
            d.get("blockers") not in (None, []) or d.get("open_questions") not in (None, [])):
        _fail("CONTENT_NOT_READY", "Only a reviewed poster candidate can be rendered.")
    c = d.get("content")
    keys = {"type", "headline", "subtitle", "benefits", "activity", "store",
            "legal_or_condition_text", "cta", "tags"}
    if not isinstance(c, dict) or set(c) - keys or c.get("type") != "poster":
        _fail("INVALID_CONTENT", "Unsupported poster content fields.")
    result = {}
    for key, kind in (("headline", "headline"), ("subtitle", "subtitle")):
        result["content." + key] = (_text(c.get(key), "content." + key), kind)
    benefits = c.get("benefits")
    if not isinstance(benefits, list) or not 1 <= len(benefits) <= 3:
        _fail("BENEFIT_LIMIT", "A poster must contain one to three benefits.")
    benefit_ids = set()
    for i, benefit in enumerate(benefits):
        if not isinstance(benefit, dict) or set(benefit) - {"benefit_id", "text", "claim_ids"}:
            _fail("INVALID_CONTENT", "Unsupported benefit fields.")
        _ref(benefit.get("benefit_id"))
        if benefit["benefit_id"] in benefit_ids:
            _fail("INVALID_CONTENT", "Duplicate benefit identity.")
        benefit_ids.add(benefit["benefit_id"])
        ref = "content.benefits." + str(i) + ".text"
        result[ref] = (_text(benefit.get("text"), ref), "benefit")
    for key in ("activity", "store", "legal_or_condition_text"):
        if c.get(key) is not None and c.get(key) != "":
            result["content." + key] = (_text(c[key], "content." + key), "conditions")
    result["content.cta"] = (_text(c.get("cta"), "content.cta"), "cta")
    plan = d.get("image_plan")
    if not isinstance(plan, list) or len(plan) != 1 or not isinstance(plan[0], dict):
        _fail("HERO_REQUIRED", "Exactly one verified hero asset is required.")
    item = plan[0]
    if set(item) - {"asset_id", "source_ref_id", "position", "caption", "purpose"}:
        _fail("INVALID_ASSET", "Paths, URLs and unsupported image fields are forbidden.")
    if (item.get("asset_id") != req.asset.asset_id or
            item.get("source_ref_id") != req.asset.source_ref_id or
            item.get("position") != "hero"):
        _fail("ASSET_SCOPE_MISMATCH", "Hero does not match the authorized asset/source.")
    result["image_plan.0.caption"] = (_text(item.get("caption"), "image_plan.0.caption", 500), "conditions")
    return result


def _quote_lines(req: PosterRequest, texts: Mapping[str, tuple[str, str]], now: datetime):
    qauth, summary = req.authorization.quote, req.customer_quote_summary
    if not req.authorization.quote_required:
        if qauth is not None or summary is not None or req.draft.get("purchase_plan") is not None:
            _fail("UNEXPECTED_QUOTE", "No-quote preview must not carry a purchase plan.")
        return []
    if not isinstance(qauth, QuoteAuthorization) or not isinstance(summary, dict):
        _fail("QUOTE_REQUIRED", "A service-verified customer summary is required.")
    for key, value in vars(qauth).items():
        if key.endswith(("_ref", "_version")):
            _ref(value)
    _digest(qauth.summary_sha256)
    _digest(qauth.dependency_hash)
    _expiry(qauth.valid_until, now)
    _expiry(summary.get("valid_until"), now)
    if qauth.quote_status != "VALID_OPTIMAL" or qauth.client_quote_allowed is not True:
        _fail("QUOTE_NOT_VALIDATED", "A current authorized independently validated quote is required.")
    if (canonical_hash(summary) != qauth.summary_sha256 or
            summary.get("quote_ref") != qauth.quote_ref or
            summary.get("quote_version") != qauth.quote_version or
            summary.get("dependency_hash") != qauth.dependency_hash or
            summary.get("product_ref") != req.scope.product_ref):
        _fail("QUOTE_VERSION_MISMATCH", "Quote summary does not match its receipt/SKU.")
    cash = _text(summary.get("formatted_customer_payable"), "quote.formatted_customer_payable", 300)
    if not any(cash in value[0] for value in texts.values()):
        _fail("QUOTE_NOT_VISIBLE", "The exact service-formatted cash must appear in reviewed poster copy.")
    p, binding = summary.get("customer_purchase_plan"), req.draft.get("purchase_plan")
    if not isinstance(p, dict) or not isinstance(binding, dict):
        _fail("PURCHASE_PLAN_REQUIRED", "The complete verified purchase plan and binding are required.")
    for key in ("plan_ref", "plan_version", "quote_ref", "quote_version"):
        _ref(p.get(key))
        if binding.get(key) != p[key]:
            _fail("PLAN_VERSION_MISMATCH", "Poster purchase-plan binding differs from the service plan.")
    if (p["quote_ref"] != qauth.quote_ref or p["quote_version"] != qauth.quote_version or
            p.get("selected_product_ref") != req.scope.product_ref or
            binding.get("display_mode") != "attached_card"):
        _fail("PLAN_VERSION_MISMATCH", "Plan must bind the current quote/SKU and attached card.")
    coverage = p.get("comparison_coverage")
    if (not isinstance(coverage, dict) or coverage.get("same_sku_complete") is not True or
            type(coverage.get("expected_sku_count")) is not int or
            coverage["expected_sku_count"] < 1 or
            type(coverage.get("validated_sku_count")) is not int or
            coverage["validated_sku_count"] != coverage["expected_sku_count"]):
        _fail("PLAN_COMPARISON_INCOMPLETE", "Plan comparison is incomplete.")
    rows = p.get("level_rows")
    if not isinstance(rows, list) or len(rows) != 4:
        _fail("PLAN_LEVELS_INCOMPLETE", "All four service-defined levels are required.")
    if any(not isinstance(row, dict) or not isinstance(row.get("level_id"), str) for row in rows):
        _fail("PLAN_LEVELS_INCOMPLETE", "Invalid four-level row identity.")
    by_id = {row["level_id"]: row for row in rows}
    if set(by_id) != {key for key, _ in _LEVELS}:
        _fail("PLAN_LEVELS_INCOMPLETE", "Unknown or duplicate price levels.")
    lines = [("quote.formatted_customer_payable", cash, "headline"),
             ("purchase_plan.platform_summary", _text(binding.get("platform_summary"),
                                                       "purchase_plan.platform_summary"), "conditions"),
             ("quote.customer_visible_breakdown_sentence",
              _text(summary.get("customer_visible_breakdown_sentence"),
                    "quote.customer_visible_breakdown_sentence"), "conditions")]
    for key, name in _LEVELS:
        row = by_id[key]
        if row.get("display_name") != name or row.get("applicability") not in {
                "applicable", "not_applicable", "excluded_mutual_exclusion"}:
            _fail("PLAN_LEVELS_INCOMPLETE", "Unknown levels/eligibility must not appear as a valid plan.")
        lines.append(("plan.level_rows." + key + ".display_name", name, "subtitle"))
        lines.append(("plan.level_rows." + key + ".reason", _text(row.get("reason"), key), "conditions"))
        if row.get("formatted_summary") is not None:
            lines.append(("plan.level_rows." + key + ".formatted_summary",
                          _text(row["formatted_summary"], key), "conditions"))
    comparisons = p.get("comparison_rows")
    if not isinstance(comparisons, list) or not 1 <= len(comparisons) <= 30:
        _fail("PLAN_COMPARISON_INCOMPLETE", "Service comparison sentences are required.")
    for i, row in enumerate(comparisons):
        ref = "plan.comparison_rows." + str(i) + ".comparison_sentence"
        if not isinstance(row, dict):
            _fail("PLAN_COMPARISON_INCOMPLETE", "Invalid comparison row.")
        lines.append((ref, _text(row.get("comparison_sentence"), ref), "conditions"))
    for key in ("optimal_scope_sentence", "resource_usage_sentence", "conditions_sentence", "valid_until_display"):
        lines.append(("plan." + key, _text(p.get(key), "plan." + key), "conditions"))
    return lines


def _font_cmaps(data: bytes):
    """Read actual Unicode glyph mappings, not tofu width/bounding-box guesses."""
    def u16(pos): return struct.unpack_from(">H", data, pos)[0]
    def u32(pos): return struct.unpack_from(">I", data, pos)[0]
    base = u32(12) if data[:4] == b"ttcf" else 0
    tables = {}
    for i in range(u16(base + 4)):
        pos = base + 12 + i * 16
        tables[data[pos:pos + 4]] = (u32(pos + 8), u32(pos + 12))
    offset, length = tables[b"cmap"]
    if offset + length > len(data): raise ValueError("Invalid cmap bounds")
    mappings = []
    for i in range(u16(offset + 2)):
        pos = offset + 4 + i * 8
        platform, encoding, relative = struct.unpack_from(">HHI", data, pos)
        if platform != 0 and (platform != 3 or encoding not in (1, 10)): continue
        sub = offset + relative
        form = u16(sub)
        if form == 12:
            count, size = u32(sub + 12), u32(sub + 4)
            if count > 100000 or sub + size > offset + length or size < 16 + count * 12:
                raise ValueError("Invalid format-12 cmap")
            groups = [struct.unpack_from(">III", data, sub + 16 + j * 12) for j in range(count)]
            starts = [g[0] for g in groups]
            def lookup12(cp, groups=groups, starts=starts):
                index = bisect.bisect_right(starts, cp) - 1
                if index < 0: return 0
                start, end, glyph = groups[index]
                return glyph + cp - start if cp <= end else 0
            mappings.append(lookup12)
        elif form == 4:
            size, count = u16(sub + 2), u16(sub + 6) // 2
            if count > 32768 or size < 16 + count * 8 or sub + size > offset + length:
                raise ValueError("Invalid format-4 cmap")
            endpos, startpos = sub + 14, sub + 16 + count * 2
            deltap, rangep = startpos + count * 2, startpos + count * 4
            ends = [u16(endpos + j * 2) for j in range(count)]
            starts = [u16(startpos + j * 2) for j in range(count)]
            deltas = [u16(deltap + j * 2) for j in range(count)]
            ranges = [u16(rangep + j * 2) for j in range(count)]
            def lookup4(cp, ends=ends, starts=starts, deltas=deltas, ranges=ranges,
                        rangep=rangep, bound=sub + size):
                if cp > 65535: return 0
                i = bisect.bisect_left(ends, cp)
                if i >= len(ends) or cp < starts[i]: return 0
                if ranges[i] == 0: return (cp + deltas[i]) & 65535
                pos = rangep + i * 2 + ranges[i] + (cp - starts[i]) * 2
                if pos + 2 > bound: return 0
                glyph = u16(pos)
                return ((glyph + deltas[i]) & 65535) if glyph else 0
            mappings.append(lookup4)
    return mappings


def _font_path(text: str) -> str:
    codepoints = {ord(c) for c in text if c != "\n"}
    for path in _FONT_PATHS:
        try:
            maps = _font_cmaps(Path(path).read_bytes())
            if maps and all(any(fn(cp) != 0 for fn in maps) for cp in codepoints):
                return path
        except (OSError, ValueError, KeyError, struct.error, IndexError):
            continue
    _fail("FONT_GLYPH_MISSING", "No approved local font covers every required Unicode glyph.")


def _wrap(text, font, width, ref):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for ch in paragraph:
            if font.getlength(ch) > width:
                _fail("TEXT_OVERFLOW", "A glyph exceeds its layout region.", ref)
            if line and font.getlength(line + ch) > width:
                lines.append(line)
                line = ch
            else:
                line += ch
        lines.append(line)
    return lines


def _region(ref, kind, x, y, w, h, **extra):
    return {"text_ref": ref, "kind": kind, "box_px": (x, y, w, h), **extra}


def _safe_regions(texts, width, height, font):
    x, w, y, regions = 72, width - 144, 72, []
    def add(ref, gap=16):
        nonlocal y
        text, kind = texts[ref]
        size = _FONTS[kind]
        lines = _wrap(text, font(size), w, ref)
        if kind in {"headline", "benefit"} and len(lines) > 2:
            _fail("TEXT_OVERFLOW", "Headline/benefit exceeds two lines; revise and re-review copy.", ref)
        h = math.ceil(size * 1.35) * len(lines)
        regions.append(_region(ref, kind, x, y, w, h))
        y += h + gap
    add("content.headline")
    add("content.subtitle", 24)
    y = max(y, 300)
    regions.append(_region(None, "hero", x, y, w, 420, fit="contain"))
    y += 436
    add("image_plan.0.caption", 20)
    for ref in texts:
        if ref.startswith("content.benefits."):
            add(ref)
    for ref in ("content.activity", "content.store", "content.legal_or_condition_text"):
        if ref in texts: add(ref)
    y += 8
    add("content.cta", 0)
    if y > height - 64:
        _fail("TEXT_OVERFLOW", "Copy exceeds the safe template; revise and re-review it.", *texts)
    return regions


def _regions(layout, texts, asset, font):
    if (not isinstance(layout, dict) or layout.get("status") != "ready" or layout.get("mode") != "poster" or
            layout.get("blockers") not in (None, []) or layout.get("copy_revision_requests") not in (None, [])):
        _fail("LAYOUT_NOT_READY", "A reviewed poster layout is required.")
    if set(layout) - {"status", "mode", "engine", "canvas", "template", "theme", "regions",
                      "article_positions", "copy_revision_requests", "blockers"}:
        _fail("UNSUPPORTED_LAYOUT", "Layout contains unsupported executable/path/URL fields.")
    canvas = layout.get("canvas")
    if (not isinstance(canvas, dict) or set(canvas) != {"width", "height"} or
            type(canvas.get("width")) is not int or type(canvas.get("height")) is not int or
            (canvas["width"], canvas["height"]) not in {(1080, 1440), (1080, 1920)} or
            layout.get("theme") != "neutral_light"):
        _fail("UNSUPPORTED_LAYOUT", "Canvas/theme is outside the application allowlist.")
    width, height = canvas["width"], canvas["height"]
    if layout.get("engine") == "safe_template":
        if layout.get("template") != "store_poster_v1" or layout.get("regions") not in (None, []):
            _fail("UNSUPPORTED_LAYOUT", "Unknown safe template or conflicting explicit regions.")
        regions = _safe_regions(texts, width, height, font)
    elif layout.get("engine") == "constraint_regions":
        source = layout.get("regions")
        if not isinstance(source, list) or not 1 <= len(source) <= 20:
            _fail("UNSUPPORTED_LAYOUT", "Invalid constrained regions.")
        regions, ids = [], set()
        for region in source:
            if not isinstance(region, dict) or set(region) - {"region_id", "kind", "text_ref", "asset_id", "box", "font_token", "align", "fit"}:
                _fail("UNSUPPORTED_LAYOUT", "Unknown region fields.")
            _ref(region.get("region_id"))
            if region["region_id"] in ids: _fail("UNSUPPORTED_LAYOUT", "Duplicate region identity.")
            ids.add(region["region_id"])
            box = region.get("box")
            if not isinstance(box, dict) or set(box) != {"x", "y", "width", "height"}:
                _fail("UNSUPPORTED_LAYOUT", "A finite normalized box is required.")
            if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1 for v in box.values()):
                _fail("UNSUPPORTED_LAYOUT", "A finite normalized box is required.")
            x, y = math.ceil(box["x"] * width), math.ceil(box["y"] * height)
            w, h = math.floor(box["width"] * width), math.floor(box["height"] * height)
            kind, ref = region.get("kind"), region.get("text_ref")
            if kind == "hero":
                if region.get("asset_id") != asset.asset_id or region.get("fit") != "contain" or ref is not None:
                    _fail("INVALID_ASSET", "Hero must contain the single authorized asset.")
            elif ref not in texts or kind != texts[ref][1] or region.get("font_token") != kind or region.get("align", "left") not in {"left", "center"}:
                _fail("UNSUPPORTED_LAYOUT", "Text must use an exact reviewed reference and approved font token.")
            regions.append(_region(ref, kind, x, y, w, h, align=region.get("align", "left")))
    else:
        _fail("UNSUPPORTED_LAYOUT", "Only safe_template and constraint_regions are supported.")
    seen = [r["text_ref"] for r in regions if r["kind"] != "hero"]
    if set(seen) != set(texts) or len(seen) != len(texts) or sum(r["kind"] == "hero" for r in regions) != 1:
        _fail("TEXT_COVERAGE_MISSING", "Every nonempty reviewed text and exactly one hero must be visible.")
    for i, region in enumerate(regions):
        x, y, w, h = region["box_px"]
        if w <= 0 or h <= 0 or x < 64 or y < 64 or x + w > width - 64 or y + h > height - 64:
            _fail("LAYOUT_OVERFLOW", "A region exceeds the 64-pixel safe area.")
        for other in regions[:i]:
            a, b, c, d = other["box_px"]
            if x < a + c and a < x + w and y < b + d and b < y + h:
                _fail("LAYOUT_OVERLAP", "Content/hero regions must not overlap.")
    return width, height, regions


def _asset_image(asset, scope, Image):
    for key in ("asset_id", "source_ref_id", "source_version", "source_snapshot_ref", "product_ref", "configuration_ref"):
        _ref(getattr(asset, key))
    if asset.product_ref != scope.product_ref or asset.configuration_ref != scope.configuration_ref or asset.source_mode != scope.source_mode:
        _fail("ASSET_SCOPE_MISMATCH", "Asset model/configuration/source scope is not the task scope.")
    if not isinstance(asset.image_bytes, bytes) or not 1 <= len(asset.image_bytes) <= 20 * 1024 * 1024:
        _fail("INVALID_ASSET", "A bounded immutable image byte payload is required.")
    if hashlib.sha256(asset.image_bytes).hexdigest() != asset.sha256:
        _fail("ASSET_BYTES_MISMATCH", "Asset bytes differ from the verified source hash.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(asset.image_bytes))
            if (image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1 or
                    image.width * image.height > 40_000_000 or
                    image.getexif().get(274, 1) != 1):
                _fail("INVALID_ASSET", "Unsupported image encoding, animation, size or orientation.")
            if type(asset.width) is not int or type(asset.height) is not int or image.size != (asset.width, asset.height):
                _fail("ASSET_DIMENSION_MISMATCH", "Decoded dimensions differ from verified metadata.")
            image.load()
            return image.convert("RGBA")
    except PosterRenderError:
        raise
    except Exception:
        _fail("INVALID_ASSET", "Asset bytes cannot be safely decoded.")


def _draw_text(draw, region, text, font, width, height):
    x, y, w, h = region["box_px"]
    size = _FONTS[region["kind"]]
    f, boxes = font(size), []
    lines = _wrap(text, f, w, region["text_ref"])
    lineheight = math.ceil(size * 1.35)
    if (region["kind"] in {"headline", "benefit"} and len(lines) > 2) or len(lines) * lineheight > h:
        _fail("TEXT_OVERFLOW", "Text does not fit its region; revise copy, not minimum font size.", region["text_ref"])
    for i, line in enumerate(lines):
        if not line: continue
        xpos = x + (w - f.getlength(line)) / 2 if region.get("align") == "center" else x
        pos = (math.ceil(xpos), y + i * lineheight)
        bbox = draw.textbbox(pos, line, font=f, anchor="lt")
        if bbox[0] < x or bbox[1] < y or bbox[2] > x + w or bbox[3] > y + h or bbox[2] > width - 64 or bbox[3] > height - 64:
            _fail("TEXT_OVERFLOW", "Actual glyph bounds exceed the approved region.", region["text_ref"])
        draw.text(pos, line, font=f, anchor="lt", fill="#172033")
        boxes.append({"text_ref": region["text_ref"], "text": line, "line_index": i,
                      "bbox": tuple(bbox), "font_size": size})
    return boxes


def _png(image, boxes):
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG", compress_level=9)
    payload = out.getvalue()
    return PNGPage(payload, hashlib.sha256(payload).hexdigest(), image.width, image.height, tuple(boxes))


def _plan_pages(lines, font, Image, ImageDraw):
    if not lines: return ()
    pages, image, boxes, y = [], None, [], 72
    for ref, text, kind in [("plan.heading", "四级组合比对与购买方案", "subtitle"), *lines]:
        size, width, height = _FONTS[kind], 1080, 1440
        wrapped = _wrap(text, font(size), width - 144, ref)
        lineheight = math.ceil(size * 1.35)
        for index, line in enumerate(wrapped):
            if image is None:
                image = Image.new("RGB", (width, height), "#FFFFFF")
                draw = ImageDraw.Draw(image)
            if y + lineheight > height - 64:
                pages.append(_png(image, boxes))
                if len(pages) >= 8: _fail("PLAN_TOO_LONG", "Purchase plan exceeds the bounded attachment size.")
                image, boxes, y = Image.new("RGB", (width, height), "#FFFFFF"), [], 72
                draw = ImageDraw.Draw(image)
            region = _region(ref, kind, 72, y, width - 144, lineheight)
            lineboxes = _draw_text(draw, region, line or " ", font, width, height)
            for box in lineboxes: box["line_index"] = index
            boxes.extend(lineboxes)
            y += lineheight
        y += 16
    if image is not None: pages.append(_png(image, boxes))
    return tuple(pages)


def render_poster(request: PosterRequest, *,
                  authorization_verifier: Callable[[RenderAuthorization], bool],
                  now: datetime | None = None) -> PosterResult:
    """Render reviewed, currently authorized bytes; never approves delivery.

    ``now`` is an application/test clock, never an HTTP/model input. Fonts and
    Pillow are optional runtime dependencies: absence blocks rendering clearly.
    A server-issued receipt and current verifier are required for fixtures too.
    """
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        _fail("INVALID_CLOCK", "An explicit timezone-aware application clock is required.")
    _validate_receipt(request, current, authorization_verifier)
    texts = _copy(request)
    quote_lines = _quote_lines(request, texts, current)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        _fail("RENDER_RUNTIME_UNAVAILABLE", "Pillow is unavailable in this Python runtime.")
    fontpath = _font_path("".join(t[0] for t in texts.values()) + "".join(t[1] for t in quote_lines) + "四级组合比对与购买方案")
    cache = {}
    def font(size):
        if size not in cache: cache[size] = ImageFont.truetype(fontpath, size, index=0)
        return cache[size]
    width, height, regions = _regions(request.layout, texts, request.asset, font)
    hero = _asset_image(request.asset, request.scope, Image)
    canvas, boxes = Image.new("RGB", (width, height), "#F5F7FA"), []
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((48, 48, width - 48, height - 48), radius=24, fill="#FFFFFF")
    hero_bbox = None
    for region in regions:
        if region["kind"] == "hero":
            x, y, w, h = region["box_px"]
            scale = min(w / hero.width, h / hero.height)
            rw, rh = max(1, math.floor(hero.width * scale)), max(1, math.floor(hero.height * scale))
            px, py = x + (w - rw) // 2, y + (h - rh) // 2
            scaled = hero.resize((rw, rh), Image.Resampling.LANCZOS)
            canvas.paste(scaled, (px, py), scaled)
            hero_bbox = (px, py, px + rw, py + rh)
        else:
            boxes.extend(_draw_text(draw, region, texts[region["text_ref"]][0], font, width, height))
    poster = _png(canvas, boxes)
    pages = _plan_pages(quote_lines, font, Image, ImageDraw)
    # A receipt can be revoked or expire while rendering; no bytes are returned then.
    _validate_receipt(request, now or datetime.now(timezone.utc), authorization_verifier)
    bindings = {"content_ref": request.authorization.content_ref,
                "content_version": request.authorization.content_version,
                "content_sha256": request.authorization.content_sha256,
                "layout_ref": request.authorization.layout_ref,
                "layout_version": request.authorization.layout_version,
                "layout_sha256": request.authorization.layout_sha256,
                "asset_id": request.asset.asset_id, "asset_sha256": request.asset.sha256,
                "source_mode": request.scope.source_mode,
                "source_snapshot_ref": request.asset.source_snapshot_ref,
                "task_version_ref": request.scope.task_version_ref,
                "quote_ref": request.authorization.quote.quote_ref if request.authorization.quote else None,
                "quote_version": request.authorization.quote.quote_version if request.authorization.quote else None,
                "quote_summary_sha256": request.authorization.quote.summary_sha256 if request.authorization.quote else None,
                "plan_ref": request.customer_quote_summary["customer_purchase_plan"]["plan_ref"] if quote_lines else None,
                "plan_version": request.customer_quote_summary["customer_purchase_plan"]["plan_version"] if quote_lines else None,
                "renderer_version": "deterministic_poster_core_1",
                "pillow_version": Image.__version__, "font_family": font(28).getname(),
                "font_sha256": hashlib.sha256(Path(fontpath).read_bytes()).hexdigest()}
    return PosterResult(poster, pages, hero_bbox, bindings)

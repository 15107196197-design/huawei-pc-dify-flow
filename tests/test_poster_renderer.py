"""Synthetic-only rendering tests; fixtures are not real authorization evidence."""

import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from services.poster_renderer import (
    PosterRenderError, RenderScope, VerifiedAsset, QuoteAuthorization,
    RenderAuthorization, PosterRequest, canonical_hash, asset_metadata_hash, render_poster,
)
from services.poster_renderer import renderer


PIL_AVAILABLE = importlib.util.find_spec("PIL") is not None
NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
FUTURE = "2099-01-01T00:00:00+00:00"


def synthetic_request(*, with_quote=False):
    """Creates colored geometric fixture bytes; never loads a product image."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (400, 200), "#DBEAFE")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 39, 199), fill="#EF4444")
    draw.rectangle((360, 0, 399, 199), fill="#22C55E")
    draw.rectangle((100, 60, 300, 140), fill="#93C5FD")
    out = io.BytesIO()
    image.save(out, format="PNG")
    payload = out.getvalue()
    scope = RenderScope("synthetic-tenant", "synthetic-store", "synthetic-actor", "task-v1",
                        "synthetic-preview", "local-preview", "CN", "synthetic-model",
                        "synthetic-config", "local_snapshot",
                        "marketing" if with_quote else "product_intro", "local_development")
    asset = VerifiedAsset("synthetic-image", "synthetic-source", "source-v1", "snapshot-v1",
                          "local_snapshot", "synthetic-model", "synthetic-config",
                          hashlib.sha256(payload).hexdigest(), 400, 200, payload)
    draft = {
        "status": "ready", "content": {
            "type": "poster", "headline": "合成排版测试", "subtitle": "这是一张无产品图片的测试卡片",
            "benefits": [{"benefit_id": "fixture-benefit", "text": "仅检查字体与版面", "claim_ids": []}],
            "activity": None, "store": None, "legal_or_condition_text": "开发夹具，不是产品宣传或报价",
            "cta": "查看测试说明", "tags": ["仅测试"]},
        "image_plan": [{"asset_id": asset.asset_id, "source_ref_id": asset.source_ref_id,
                        "position": "hero", "caption": "自生成几何图形，非产品素材", "purpose": "验证原比例放置"}],
        "purchase_plan": None, "blockers": [], "open_questions": []}
    layout = {"status": "ready", "mode": "poster", "engine": "safe_template",
              "canvas": {"width": 1080, "height": 1440}, "template": "store_poster_v1",
              "theme": "neutral_light", "regions": [], "article_positions": [],
              "copy_revision_requests": [], "blockers": []}
    summary, qauth = None, None
    if with_quote:
        cash = "合成现金值123.45元"
        draft["content"]["headline"] = cash
        draft["purchase_plan"] = {"plan_ref": "plan-fixture", "plan_version": "1",
                                  "quote_ref": "quote-fixture", "quote_version": "1",
                                  "platform_summary": "以下只展示合成服务方案，不是购买建议。",
                                  "display_mode": "attached_card"}
        plan = {
            "plan_ref": "plan-fixture", "plan_version": "1", "quote_ref": "quote-fixture", "quote_version": "1",
            "selected_product_ref": scope.product_ref,
            "level_rows": [{"level_id": key, "display_name": name, "applicability": "not_applicable",
                            "reason": "仅合成测试条件，不适用实际销售。", "formatted_summary": "原样金额标记001.2300"}
                           for key, name in renderer._LEVELS],
            "comparison_rows": [{"comparison_sentence": "方案甲本次现金123.45元；方案乙本次现金130.01元。"}],
            "comparison_coverage": {"same_sku_complete": True, "expected_sku_count": 1, "validated_sku_count": 1},
            "optimal_scope_sentence": "仅本夹具的一个合成型号与相同合成资源条件。",
            "resource_usage_sentence": "合成积分消耗111点，旧机价值222.22元；不作任何核算。",
            "conditions_sentence": "所有条件仅为合成数据。", "valid_until_display": "合成时效2099年1月1日。"}
        summary = {"quote_ref": "quote-fixture", "quote_version": "1", "product_ref": scope.product_ref,
                   "formatted_customer_payable": cash, "dependency_hash": "a" * 64,
                   "valid_until": FUTURE, "customer_purchase_plan": plan,
                   "customer_visible_breakdown_sentence": "合成商品应付200.00元，必计费用10.00元，抵付86.55元，现金123.45元。",
                   "cash_due_now_minor": 12345, "customer_payable_minor": 12345}
        qauth = QuoteAuthorization("quote-fixture", "1", "validation-fixture", "1",
                                   "plan-check-fixture", "1", canonical_hash(summary), "a" * 64,
                                   FUTURE, "VALID_OPTIMAL", True)
    auth = RenderAuthorization(
        scope=scope, receipt_ref="synthetic-receipt", receipt_version="1",
        content_ref="synthetic-content", content_version="1", content_check_ref="synthetic-content-check", content_check_version="1",
        layout_ref="synthetic-layout", layout_version="1", source_check_ref="synthetic-source-check", source_check_version="1",
        product_identity_check_ref="synthetic-model-check", product_identity_check_version="1",
        configuration_check_ref="synthetic-config-check", configuration_check_version="1",
        rights_check_ref="synthetic-rights-check", rights_check_version="1",
        content_sha256=canonical_hash(draft), layout_sha256=canonical_hash(layout),
        asset_metadata_sha256=asset_metadata_hash(asset), valid_until=FUTURE,
        quote_required=with_quote, quote=qauth)
    return PosterRequest(scope, draft, layout, asset, auth, summary)


def rebind(req, **changes):
    """Test issuer only. Production must validate actual evidence before signing."""
    req = replace(req, **changes)
    auth = replace(req.authorization, scope=req.scope, content_sha256=canonical_hash(req.draft),
                   layout_sha256=canonical_hash(req.layout), asset_metadata_sha256=asset_metadata_hash(req.asset))
    if auth.quote and req.customer_quote_summary:
        auth = replace(auth, quote=replace(auth.quote, summary_sha256=canonical_hash(req.customer_quote_summary)))
    return replace(req, authorization=auth)


class FontMappingTests(unittest.TestCase):
    def test_format4_range_offset_delta_and_zero_glyph(self):
        # CJK segment maps via glyphIdArray + idDelta; sentinel is .notdef.
        sub = (struct.pack(">HHHHHHH", 4, 34, 0, 4, 4, 1, 0) +
               struct.pack(">HHH", 0x4E00, 0xFFFF, 0) +
               struct.pack(">HHHHHHH", 0x4E00, 0xFFFF, 2, 1, 4, 0, 5))
        cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub
        data = struct.pack(">IHHHH", 0x10000, 1, 0, 0, 0) + struct.pack(">4sIII", b"cmap", 0, 28, len(cmap)) + cmap
        lookup = renderer._font_cmaps(data)[0]
        self.assertEqual(lookup(0x4E00), 7)
        self.assertEqual(lookup(0xFFFF), 0)
        self.assertEqual(lookup(0x4E01), 0)

    def test_format12_non_bmp_and_missing_glyph(self):
        # Tiny synthetic font directory with a Unicode format-12 cmap.
        sub = struct.pack(">HHIII", 12, 0, 28, 0, 1) + struct.pack(">III", 0x20000, 0x20001, 7)
        cmap = struct.pack(">HHHHI", 0, 1, 3, 10, 12) + sub
        data = struct.pack(">IHHHH", 0x10000, 1, 0, 0, 0) + struct.pack(">4sIII", b"cmap", 0, 28, len(cmap)) + cmap
        maps = renderer._font_cmaps(data)
        self.assertEqual(maps[0](0x20000), 7)
        self.assertEqual(maps[0](0x20001), 8)
        self.assertEqual(maps[0](ord("华")), 0)

    def test_notdef_width_is_not_accepted_as_cjk_coverage(self):
        with patch.object(renderer, "_FONT_PATHS", ()):
            with self.assertRaises(PosterRenderError) as caught:
                renderer._font_path("华为")
        self.assertEqual(caught.exception.code, "FONT_GLYPH_MISSING")

    def test_invalid_unicode_json_rejected(self):
        with self.assertRaises(PosterRenderError):
            canonical_hash({"x": float("nan")})


@unittest.skipUnless(PIL_AVAILABLE, "Pillow is available in the bundled workspace Python, not this interpreter")
class PosterRendererTests(unittest.TestCase):
    def setUp(self):
        self.req = synthetic_request()
        try:
            renderer._font_path("华为合成排版测试")
        except PosterRenderError:
            self.skipTest("Approved local CJK font unavailable; rendering must block in this runtime")

    def render(self, req=None, verifier=None):
        req = req or self.req
        return render_poster(req, authorization_verifier=verifier or (lambda receipt: receipt is req.authorization), now=NOW)

    def assertBlocked(self, code, req=None, verifier=None):
        with self.assertRaises(PosterRenderError) as caught:
            self.render(req, verifier)
        self.assertEqual(caught.exception.code, code)

    def test_real_png_hash_dimensions_bboxes_and_unapproved_delivery(self):
        from PIL import Image
        result = self.render()
        self.assertEqual(result.poster.png_bytes[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(hashlib.sha256(result.poster.png_bytes).hexdigest(), result.poster.sha256)
        image = Image.open(io.BytesIO(result.poster.png_bytes))
        self.assertEqual(image.size, (1080, 1440))
        self.assertFalse(result.export_authorized)
        self.assertFalse(result.competition_eligible)
        self.assertTrue(result.requires_visual_review)
        self.assertEqual(result.purchase_plan_pages, ())
        for box in result.poster.text_boxes:
            x1, y1, x2, y2 = box["bbox"]
            self.assertGreaterEqual(min(x1, y1), 64)
            self.assertLessEqual(x2, 1016)
            self.assertLessEqual(y2, 1376)
            self.assertGreaterEqual(box["font_size"], 28)

    def test_deterministic_bytes(self):
        self.assertEqual(self.render().poster.png_bytes, self.render().poster.png_bytes)

    def test_image_contain_preserves_both_edges_and_ratio(self):
        from PIL import Image
        result = self.render()
        x1, y1, x2, y2 = result.hero_bbox
        self.assertAlmostEqual((x2 - x1) / (y2 - y1), 2, places=2)
        image = Image.open(io.BytesIO(result.poster.png_bytes))
        self.assertEqual(image.getpixel((x1 + 5, (y1 + y2) // 2)), (239, 68, 68))
        self.assertEqual(image.getpixel((x2 - 5, (y1 + y2) // 2)), (34, 197, 94))

    def test_actual_glyph_coverage_rejects_unsupported_codepoint(self):
        draft = copy.deepcopy(self.req.draft)
        draft["content"]["headline"] = "合成\U0001f984"
        self.assertBlocked("FONT_GLYPH_MISSING", rebind(self.req, draft=draft))

    def test_current_authority_denied_even_with_complete_metadata(self):
        self.assertBlocked("AUTHORIZATION_DENIED", verifier=lambda _: False)

    def test_revocation_during_render_returns_no_bytes(self):
        calls = []
        def verify(_):
            calls.append(1)
            return len(calls) == 1
        self.assertBlocked("AUTHORIZATION_DENIED", verifier=verify)
        self.assertEqual(len(calls), 2)

    def test_required_source_model_config_rights_versions(self):
        for field_name in ("source_check_ref", "source_check_version", "product_identity_check_ref",
                           "product_identity_check_version", "configuration_check_ref", "configuration_check_version",
                           "rights_check_ref", "rights_check_version"):
            with self.subTest(field_name=field_name):
                req = replace(self.req, authorization=replace(self.req.authorization, **{field_name: ""}))
                self.assertBlocked("MISSING_VERIFICATION", req)

    def test_scope_tenant_store_destination_and_task_version_binding(self):
        for key in ("tenant_ref", "store_ref", "destination_ref", "task_version_ref", "product_ref", "configuration_ref"):
            with self.subTest(key=key):
                self.assertBlocked("SCOPE_MISMATCH", replace(self.req, scope=replace(self.req.scope, **{key: "different"})))

    def test_expired_and_timezone_missing_authorization(self):
        for expiry in ("2000-01-01T00:00:00+00:00", "2099-01-01T00:00:00", "not-a-date"):
            self.assertBlocked("EXPIRED_VERIFICATION", replace(self.req, authorization=replace(self.req.authorization, valid_until=expiry)))

    def test_source_model_config_assets_do_not_self_upgrade(self):
        for field_name in ("product_ref", "configuration_ref", "source_mode"):
            req = rebind(self.req, asset=replace(self.req.asset, **{field_name: "another"}))
            self.assertBlocked("ASSET_SCOPE_MISMATCH", req)

    def test_competition_does_not_accept_local_snapshot_or_missing_ima_receipt(self):
        req = rebind(self.req, scope=replace(self.req.scope, material_policy="competition_strict"))
        self.assertBlocked("IMA_SOURCE_REQUIRED", req)
        req = rebind(req, scope=replace(req.scope, source_mode="hybrid_verified"),
                     asset=replace(req.asset, source_mode="hybrid_verified"))
        self.assertBlocked("MISSING_VERIFICATION", req)

    def test_bytes_hash_and_dimensions(self):
        self.assertBlocked("ASSET_BYTES_MISMATCH", replace(self.req, asset=replace(self.req.asset, image_bytes=b"different")))
        req = rebind(self.req, asset=replace(self.req.asset, width=401))
        self.assertBlocked("ASSET_DIMENSION_MISMATCH", req)

    def test_invalid_and_animated_image_bytes_do_not_render(self):
        from PIL import Image
        invalid = b"not an image"
        req = rebind(self.req, asset=replace(self.req.asset, image_bytes=invalid,
                                            sha256=hashlib.sha256(invalid).hexdigest()))
        self.assertBlocked("INVALID_ASSET", req)
        output = io.BytesIO()
        Image.new("RGB", (400, 200), "red").save(
            output, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (400, 200), "blue")], duration=100)
        payload = output.getvalue()
        req = rebind(self.req, asset=replace(self.req.asset, image_bytes=payload,
                                            sha256=hashlib.sha256(payload).hexdigest()))
        self.assertBlocked("INVALID_ASSET", req)

    def test_reviewed_content_and_layout_hash_cannot_be_reused_after_edit(self):
        draft = copy.deepcopy(self.req.draft)
        draft["content"]["headline"] = "已改字"
        self.assertBlocked("CONTENT_VERSION_MISMATCH", replace(self.req, draft=draft))
        layout = copy.deepcopy(self.req.layout)
        layout["canvas"]["height"] = 1920
        self.assertBlocked("LAYOUT_VERSION_MISMATCH", replace(self.req, layout=layout))

    def test_rejects_arbitrary_path_url_and_raw_json_asset(self):
        for key in ("path", "url", "download_url"):
            draft = copy.deepcopy(self.req.draft)
            draft["image_plan"][0][key] = "https://example.invalid/private.png"
            self.assertBlocked("INVALID_ASSET", rebind(self.req, draft=draft))
        with self.assertRaises(PosterRenderError) as caught:
            asset_metadata_hash({"path": "/etc/passwd"})
        self.assertEqual(caught.exception.code, "INVALID_ASSET")

    def test_four_benefits_and_long_headline_block_without_shrinking(self):
        draft = copy.deepcopy(self.req.draft)
        draft["content"]["benefits"] *= 4
        self.assertBlocked("BENEFIT_LIMIT", rebind(self.req, draft=draft))
        draft = copy.deepcopy(self.req.draft)
        draft["content"]["headline"] = "长标题" * 40
        self.assertBlocked("TEXT_OVERFLOW", rebind(self.req, draft=draft))

    def test_long_conditions_not_dropped_or_shrunk(self):
        draft = copy.deepcopy(self.req.draft)
        draft["content"]["legal_or_condition_text"] = "必须完整保留的条件" * 100
        self.assertBlocked("TEXT_OVERFLOW", rebind(self.req, draft=draft))

    def test_missing_hero_or_extra_hero_blocked(self):
        for image_plan in ([], self.req.draft["image_plan"] * 2):
            draft = copy.deepcopy(self.req.draft)
            draft["image_plan"] = image_plan
            self.assertBlocked("HERO_REQUIRED", rebind(self.req, draft=draft))

    def test_unsupported_template_and_canvas_are_not_implicitly_substituted(self):
        for key, value in (("template", "unknown"), ("canvas", {"width": 4096, "height": 4096})):
            layout = copy.deepcopy(self.req.layout)
            layout[key] = value
            self.assertBlocked("UNSUPPORTED_LAYOUT", rebind(self.req, layout=layout))

    def constrained_layout(self):
        # Geometrically separate normalized boxes that cover all fixture texts.
        rows = [("content.headline", "headline", .06, .05, .88, .12),
                ("content.subtitle", "subtitle", .06, .18, .88, .08),
                (None, "hero", .1, .28, .8, .3),
                ("image_plan.0.caption", "conditions", .06, .6, .88, .07),
                ("content.benefits.0.text", "benefit", .06, .69, .88, .06),
                ("content.legal_or_condition_text", "conditions", .06, .77, .88, .07),
                ("content.cta", "cta", .06, .87, .88, .06)]
        regions = []
        for i, (ref, kind, x, y, w, h) in enumerate(rows):
            region = {"region_id": "region-" + str(i), "kind": kind,
                      "box": {"x": x, "y": y, "width": w, "height": h}}
            if ref:
                region.update(text_ref=ref, font_token=kind, align="left")
            else:
                region.update(asset_id=self.req.asset.asset_id, fit="contain")
            regions.append(region)
        return {**self.req.layout, "engine": "constraint_regions", "template": None, "regions": regions}

    def test_constraint_regions_real_render_and_complete_text_coverage(self):
        result = self.render(rebind(self.req, layout=self.constrained_layout()))
        self.assertEqual({box["text_ref"] for box in result.poster.text_boxes}, set(renderer._copy(self.req)))

    def test_constraint_overlap_margin_and_uncovered_conditions_fail(self):
        layout = self.constrained_layout()
        layout["regions"][1]["box"]["y"] = .08
        self.assertBlocked("LAYOUT_OVERLAP", rebind(self.req, layout=layout))
        layout = self.constrained_layout()
        layout["regions"][0]["box"]["x"] = 0
        self.assertBlocked("LAYOUT_OVERFLOW", rebind(self.req, layout=layout))
        layout = self.constrained_layout()
        layout["regions"].pop(5)
        self.assertBlocked("TEXT_COVERAGE_MISSING", rebind(self.req, layout=layout))

    def test_all_formal_marketing_requires_quote(self):
        req = rebind(self.req, scope=replace(self.req.scope, task_kind="marketing"))
        self.assertBlocked("QUOTE_REQUIRED", req)

    def test_quote_plan_is_rendered_verbatim_to_real_attachment_png(self):
        req = synthetic_request(with_quote=True)
        result = self.render(req)
        self.assertTrue(result.purchase_plan_pages)
        all_lines = [box["text"] for page in result.purchase_plan_pages for box in page.text_boxes]
        self.assertIn(req.customer_quote_summary["formatted_customer_payable"], all_lines)
        self.assertIn("原样金额标记001.2300", all_lines)
        joined = "".join(all_lines)
        for key, name in renderer._LEVELS:
            self.assertIn(name, joined)
        original = req.customer_quote_summary["customer_purchase_plan"]["comparison_rows"][0]["comparison_sentence"]
        self.assertIn(original, joined)
        self.assertEqual(result.bindings["quote_ref"], "quote-fixture")
        self.assertEqual(result.bindings["quote_version"], "1")
        self.assertEqual(result.bindings["plan_ref"], "plan-fixture")
        self.assertIn(req.customer_quote_summary["customer_visible_breakdown_sentence"], joined)

    def test_quote_dto_and_copy_are_not_mutated_or_reformatted(self):
        req = synthetic_request(with_quote=True)
        before_summary = copy.deepcopy(req.customer_quote_summary)
        before_draft = copy.deepcopy(req.draft)
        self.render(req)
        self.assertEqual(req.customer_quote_summary, before_summary)
        self.assertEqual(req.draft, before_draft)

    def test_missing_preformatted_financial_breakdown_blocks_instead_of_calculating(self):
        req = synthetic_request(with_quote=True)
        summary = copy.deepcopy(req.customer_quote_summary)
        summary.pop("customer_visible_breakdown_sentence")
        self.assertBlocked("INVALID_TEXT", rebind(req, customer_quote_summary=summary))

    def test_long_plan_paginates_without_losing_service_text_or_small_print(self):
        req = synthetic_request(with_quote=True)
        summary = copy.deepcopy(req.customer_quote_summary)
        sentence = "合成比较条件必须保留，现金00123.4500元不应重新计算。" * 16
        summary["customer_purchase_plan"]["comparison_rows"] = [{"comparison_sentence": sentence}]
        result = self.render(rebind(req, customer_quote_summary=summary))
        self.assertGreater(len(result.purchase_plan_pages), 1)
        ref = "plan.comparison_rows.0.comparison_sentence"
        self.assertEqual("".join(box["text"] for page in result.purchase_plan_pages for box in page.text_boxes
                                 if box["text_ref"] == ref), sentence)
        for page in result.purchase_plan_pages:
            for box in page.text_boxes:
                self.assertGreaterEqual(box["font_size"], 28)
                self.assertLessEqual(box["bbox"][3], 1376)

    def test_missing_unvalidated_expired_or_changed_quote_does_not_render(self):
        req = synthetic_request(with_quote=True)
        self.assertBlocked("QUOTE_REQUIRED", replace(req, customer_quote_summary=None))
        auth = replace(req.authorization, quote=replace(req.authorization.quote, quote_status="FEASIBLE_NOT_PROVEN"))
        self.assertBlocked("QUOTE_NOT_VALIDATED", replace(req, authorization=auth))
        auth = replace(req.authorization, quote=replace(req.authorization.quote, valid_until="2000-01-01T00:00:00+00:00"))
        self.assertBlocked("EXPIRED_VERIFICATION", replace(req, authorization=auth))
        summary = copy.deepcopy(req.customer_quote_summary)
        summary["formatted_customer_payable"] = "changed"
        self.assertBlocked("QUOTE_VERSION_MISMATCH", replace(req, customer_quote_summary=summary))

    def test_missing_four_levels_incomplete_comparison_or_plan_binding_blocks(self):
        req = synthetic_request(with_quote=True)
        summary = copy.deepcopy(req.customer_quote_summary)
        summary["customer_purchase_plan"]["level_rows"].pop()
        self.assertBlocked("PLAN_LEVELS_INCOMPLETE", rebind(req, customer_quote_summary=summary))
        summary = copy.deepcopy(req.customer_quote_summary)
        summary["customer_purchase_plan"]["comparison_coverage"]["same_sku_complete"] = False
        self.assertBlocked("PLAN_COMPARISON_INCOMPLETE", rebind(req, customer_quote_summary=summary))
        draft = copy.deepcopy(req.draft)
        draft["purchase_plan"]["quote_version"] = "other"
        self.assertBlocked("PLAN_VERSION_MISMATCH", rebind(req, draft=draft))


if __name__ == "__main__":
    unittest.main()

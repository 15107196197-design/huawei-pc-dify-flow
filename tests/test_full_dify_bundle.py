"""Offline negative contracts; no Dify import or real model/API test is claimed."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import hashlib
import time
import unittest

from services.ima_adapter.hybrid import FactReceipt

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("full_dify_bundle", ROOT / "scripts/build_full_dify_bundle.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def invoke(code, **kwargs):
    namespace = {}
    exec(code, namespace)
    return namespace["main"](**kwargs)


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def envelope(data, state="ready"):
    return encoded({"status": state, "data": data})


def task(kind="marketing"):
    return {"task_kind": kind, "product_query": "synthetic-sku", "audience": "合成用户",
            "usage_scenario": "仅用于合成合同测试", "content_channel": "moments" if kind in {"marketing", "full_package"} else None,
            "sales_platform": "synthetic-sales", "quote_required": kind != "product_intro",
            "purchase_plan_required": kind != "product_intro", "script_required": kind in {"full_package", "sales_script"},
            "recommendation_requested": False,
            "quote_inputs": {"region": None, "as_of": None, "rule_timezone": None, "currency": None, "quantity": None, "eligibility": []}}


def model_bindings():
    return {role: {"provider": "synthetic-provider", "name": "synthetic-review" if role == "fact_compliance_review" else "synthetic-text", "mode": "chat", "completion_params": {}} for role in BUILDER.MODEL_SLOTS}


def destinations():
    return [{"node_id": role, "provider": binding["provider"], "model": binding["name"]} for role, binding in model_bindings().items()]


def summary():
    value = {"quote_ref": "q-test", "quote_version": "1", "product_ref": "sku-test",
             "formatted_customer_payable": "合成测试现金值", "cash_due_now_minor": 123,
             "customer_payable_minor": 123, "valid_until": "2099-01-01T00:00:00+08:00",
             "objective_metric": "min_cash_due_now_given_verified_customer_resources",
             "customer_resource_snapshot_ref": "res-test", "customer_resource_snapshot_version": "1", "resource_use_scope_ref": "use-test"}
    value["customer_purchase_plan"] = {
        "plan_ref": "plan-test", "plan_version": "1", "quote_ref": "q-test", "quote_version": "1", "selected_product_ref": "sku-test",
        "objective_metric": value["objective_metric"], "customer_resource_snapshot_ref": "res-test", "customer_resource_snapshot_version": "1",
        "level_rows": [{"level_id": key, "display_name": name, "applicability": "applicable", "reason": "仅合成依据"} for key, name in (("base_price", "基准价"), ("platform_discount", "平台优惠"), ("identity_benefit", "身份权益"), ("trade_in_national_subsidy", "换新国补"))],
        "comparison_rows": [{"comparison_sentence": "仅合成比较，不是实际购买建议。"}],
        "comparison_coverage": {"same_sku_complete": True, "expected_sku_count": 1, "validated_sku_count": 1},
        "optimal_scope_sentence": "合成单SKU范围", "resource_usage_sentence": "合成资源说明", "conditions_sentence": "合成条件", "valid_until_display": "合成日期", "content_channel": None}
    return value


def bundle(kind="quote"):
    needed = {
        "product_intro": ["product_intro", "fact_compliance_review"],
        "quote": ["fact_compliance_review", "quote_explain"],
        "sales_script": ["fact_compliance_review", "quote_explain", "sales_demo"],
        "marketing": ["fact_compliance_review", "quote_explain", "platform_strategy", "article_write", "visual_layout", "visual_review"],
        "full_package": ["fact_compliance_review", "quote_explain", "platform_strategy", "article_write", "visual_layout", "visual_review", "sales_demo"],
    }[kind]
    return {"trusted_context": {"source_context_ref": "scope-test", "source_mode": "local_snapshot", "source_snapshot_ref": "snap-test", "competition_eligible": False},
            "task": task(kind), "evidence": {"facts": [{"fact_id": "f1", "source_ref_ids": ["s1"], "raw_text": "仅合成产品事实。"}],
            "source_refs": [{"source_ref_id": "s1", "source_title": "合成测试来源", "content_hash": "hash-test"}], "business_rules": []},
            "policy": {"llm_payload_allowed": True, "required_model_nodes": sorted(needed), "allowed_model_destinations": destinations()}, "allowed_assets": [],
            "quote_context": {"quote_status": "VALID_OPTIMAL", "client_quote_allowed": True, "validation_ref": "validate-test", "customer_quote_summary": summary()}}


def hybrid_bundle():
    value = bundle("product_intro")
    now = time.time()
    receipt = FactReceipt(relative_path="P1-产品参数库/01-鸿蒙电脑/合成型号/产品事实.md", source_context_ref="scope-test", product_ref="product-test",
        scope_hash="a" * 64, task_hash=hashlib.sha256(json.dumps(value["task"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        snapshot_ref="snap-test", sha256="b" * 64, byte_length=123, verified_at=now - 1, expires_at=now + 120, mapping_hash="c" * 64).manifest()
    value["trusted_context"].update(source_mode="hybrid_verified", ima_provenance="selected_fact_file_original_hash_matched", ima_verification=receipt)
    for row in value["evidence"]["source_refs"]:
        row.update(document_id="document_" + receipt["source_document_ref"][:24], content_hash=receipt["sha256"], ima_provenance="selected_fact_file_original_hash_matched")
    for row in value["evidence"]["facts"]:
        row.update(product_ref=receipt["product_ref"], verification_state="source_original_matched_fact_truth_not_asserted")
    return value


def explanation():
    return {"status": "ready", "customer_explanation": "合成测试现金值，仅合成合同。", "quote_ref": "q-test", "quote_version": "1",
            "purchase_plan_ref": "plan-test", "purchase_plan_version": "1", "open_items": [], "blockers": [],
            "claim_refs": [{"target": "/customer_explanation", "text": "合成测试现金值，仅合成合同。", "quote_binding": {"quote_ref": "q-test", "quote_version": "1"}}]}


def review():
    return {"findings": [{"target_ref": "/customer_explanation", "text": "合成测试现金值，仅合成合同。", "decision": "supported", "evidence_refs": [], "quote_binding": {"quote_ref": "q-test", "quote_version": "1"}}],
            "coverage": {"checked_target_refs": ["/customer_explanation"], "unmapped_claims": []}, "conflicts": [], "needs_human_review": False}


class FullBundleContracts(unittest.TestCase):
    def normalize(self, value):
        return invoke(BUILDER.NORMALIZE, text=encoded({"status": "ready", "task": value}))

    def test_bad_scene_json_does_not_reach_scope(self):
        for raw in ("{", "[]", '{"a":NaN}', '{"status":"ready","status":"needs_input"}', '```json\n{}\n```'):
            self.assertFalse(invoke(BUILDER.NORMALIZE, text=raw)["ready"])

    def test_formal_tasks_force_quote_and_purchase_plan(self):
        for kind in ("marketing", "full_package", "quote", "sales_script"):
            current = task(kind) | {"quote_required": False, "purchase_plan_required": False}
            parsed = self.normalize(current)
            self.assertTrue(parsed["ready"])
            normalized = json.loads(parsed["payload_json"])["task"]
            self.assertIs(normalized["quote_required"], True)
            self.assertIs(normalized["purchase_plan_required"], True)
        full = json.loads(self.normalize(task("full_package") | {"script_required": False})["payload_json"])["task"]
        self.assertIs(full["script_required"], True)

    def test_no_silent_intro_downgrade(self):
        for value in (task() | {"task_kind": None}, task("product_intro") | {"quote_required": True}, task() | {"content_channel": None}):
            self.assertFalse(self.normalize(value)["ready"])
        self.assertTrue(self.normalize(task("product_intro"))["ready"])

    def test_authority_and_self_verified_eligibility_are_not_accepted(self):
        current = task("product_intro") | {"tenant_id": "other", "trusted_context": {"verified": True}, "customer_quote_summary": {"customer_payable_minor": 0}}
        parsed = self.normalize(current)
        self.assertTrue(parsed["ready"])
        data = json.loads(parsed["payload_json"])["task"]
        self.assertNotIn("tenant_id", data)
        self.assertNotIn("trusted_context", data)
        current["quote_inputs"] = {"eligibility": [{"kind": "student", "claimed_status": "verified"}]}
        self.assertFalse(self.normalize(current)["ready"])

    def test_recommendation_can_preserve_missing_model_without_inventing_one(self):
        current = task() | {"product_query": None, "recommendation_requested": True}
        self.assertTrue(self.normalize(current)["ready"])
        current["recommendation_requested"] = False
        self.assertFalse(self.normalize(current)["ready"])

    def test_source_scope_needs_authenticated_proof_and_destination(self):
        for data in ({}, {"source_context_ref": "scope-test"}, {"source_context_ref": "scope-test", "source_context_proof": "proof"}):
            self.assertFalse(invoke(BUILDER.SCOPE, status_code=200, body=envelope(data), request_json=encoded({"task": task()}))["ready"])

    def evidence(self, data, state="ready", value=None):
        code = BUILDER.EVIDENCE.replace("__EXPECTED__", repr(destinations()))
        return invoke(code, status_code=200, body=envelope(data, state), task_json=encoded({"task": (value or bundle("product_intro"))["task"]}), scope_ref="scope-test")

    def test_http_200_business_needs_source_is_terminal(self):
        for state in ("needs_input", "needs_source", "conflict", "denied", "error"):
            result = self.evidence({"secret_debug": "must not be echoed"}, state)
            self.assertFalse(result["ready"])
            self.assertEqual(result["route"], state)
            self.assertNotIn("must not be echoed", encoded(result))

    def test_four_levels_pending_returns_fixed_safe_chinese_guidance(self):
        private = {"reason": "FOUR_LEVELS_PENDING", "questions": ["PRIVATE_QUESTION_MUST_NOT_LEAK"],
                   "signed_url": "PRIVATE_SIGNED_URL_MUST_NOT_LEAK", "api_key": "PRIVATE_VALUE_MUST_NOT_LEAK"}
        first = self.evidence(private, "needs_source")
        second = self.evidence({"reason": "FOUR_LEVELS_PENDING", "questions": ["DIFFERENT_PRIVATE_QUESTION"]}, "needs_source")
        self.assertFalse(first["ready"])
        self.assertEqual(first["route"], "needs_source")
        self.assertEqual(first["message"], second["message"])
        for term in ("商品型号", "销售平台", "地区", "有效期", "权益", "旧机", "暂时无法生成含价格", "基准价", "平台优惠", "身份权益", "换新国补"):
            self.assertIn(term, first["message"])
        for marker in ("PRIVATE_", "signed_url", "api_key", "questions"):
            self.assertNotIn(marker, encoded(first))
        self.assertEqual(first["payload_json"], "{}")
        self.assertEqual(first["tool_json"], "{}")

    def test_other_nonready_reasons_keep_only_original_block_code(self):
        for reason in ("FOUR_LEVELS_PENDING_EXTRA_PRIVATE", "PRIVATE_ERROR_DETAIL", None, {"nested": "PRIVATE_DATA"}):
            with self.subTest(reason=reason):
                result = self.evidence({"reason": reason, "questions": ["PRIVATE_QUESTION"]}, "needs_source")
                self.assertFalse(result["ready"])
                self.assertEqual(result["message"], "BLOCKED: EVIDENCE_NEEDS_SOURCE")
                self.assertNotIn("PRIVATE_", encoded(result))

    def guard(self, value, expected=None):
        namespace = {}
        exec(BUILDER.COMMON, namespace)
        namespace["guard_destinations"](value, destinations() if expected is None else expected)

    def test_intro_evidence_needs_only_actual_writer_and_review_grants(self):
        value = bundle("product_intro")
        needed = {"product_intro", "fact_compliance_review"}
        value["policy"]["allowed_model_destinations"] = [row for row in destinations() if row["node_id"] in needed]
        result = self.evidence({"task_bundle": value})
        self.assertTrue(result["ready"], result["message"])
        self.assertEqual(set(json.loads(result["payload_json"])["policy"]["required_model_nodes"]), needed)

    def test_required_nodes_cannot_be_empty_missing_duplicate_or_understated(self):
        for declared in (None, [], "product_intro", ["product_intro"],
                         ["product_intro", "fact_compliance_review", "fact_compliance_review"],
                         ["product_intro", "fact_compliance_review", "article_write"], ["product_intro", {}]):
            with self.subTest(declared=declared):
                value = bundle("product_intro")
                if declared is None:
                    value["policy"].pop("required_model_nodes")
                else:
                    value["policy"]["required_model_nodes"] = declared
                self.assertFalse(self.evidence({"task_bundle": value})["ready"])

    def test_required_identity_binding_cannot_disappear_from_canvas_expected_list(self):
        for expected in ([], [x for x in destinations() if x["node_id"] != "product_intro"],
                         [x for x in destinations() if x["node_id"] != "fact_compliance_review"]):
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError):
                    self.guard(bundle("product_intro"), expected)

    def test_required_provider_model_identity_must_match_grant(self):
        for key, bad in (("provider", "different-provider"), ("model", "different-model"), ("model", "")):
            with self.subTest(key=key, bad=bad):
                value = bundle("product_intro")
                grant = next(x for x in value["policy"]["allowed_model_destinations"] if x["node_id"] == "product_intro")
                grant[key] = bad
                self.assertFalse(self.evidence({"task_bundle": value})["ready"])

    def test_quote_script_and_intro_require_their_bound_task_roles_only(self):
        for kind in ("product_intro", "quote", "sales_script"):
            with self.subTest(kind=kind):
                value = bundle(kind)
                needed = set(value["policy"]["required_model_nodes"])
                value["policy"]["allowed_model_destinations"] = [x for x in destinations() if x["node_id"] in needed]
                self.guard(value)
                for role in needed:
                    missing = copy.deepcopy(value)
                    missing["policy"]["allowed_model_destinations"] = [x for x in missing["policy"]["allowed_model_destinations"] if x["node_id"] != role]
                    with self.assertRaises(ValueError):
                        self.guard(missing)

    def test_marketing_visual_review_binding_cannot_be_silently_omitted(self):
        for kind in ("marketing", "full_package"):
            with self.subTest(kind=kind):
                value = bundle(kind)
                visual = {"node_id": "visual_review", "provider": "synthetic-provider", "model": "synthetic-vision"}
                value["policy"]["allowed_model_destinations"].append(visual)
                # All known bindings/grants still fail if the required actual
                # visual binding is absent from this canvas's expected list.
                with self.assertRaises(ValueError):
                    self.guard(value)
                self.guard(value, destinations() + [visual])
                value["policy"]["required_model_nodes"].remove("visual_review")
                with self.assertRaises(ValueError):
                    self.guard(value, destinations() + [visual])

    def test_store_poster_requires_poster_writer_instead_of_article_writer(self):
        value = bundle("marketing")
        value["task"]["content_channel"] = "store_poster"
        declared = value["policy"]["required_model_nodes"]
        declared[declared.index("article_write")] = "poster_copy"
        visual = {"node_id": "visual_review", "provider": "synthetic-provider", "model": "synthetic-vision"}
        needed = set(declared)
        value["policy"]["allowed_model_destinations"] = [x for x in destinations() + [visual] if x["node_id"] in needed]
        self.guard(value, destinations() + [visual])
        value["policy"]["allowed_model_destinations"] = [x for x in value["policy"]["allowed_model_destinations"] if x["node_id"] != "poster_copy"]
        value["policy"]["allowed_model_destinations"].append(next(x for x in destinations() if x["node_id"] == "article_write"))
        with self.assertRaises(ValueError):
            self.guard(value, destinations() + [visual])

    def test_evidence_rejects_missing_model_grant(self):
        value = bundle("product_intro")
        value["policy"]["allowed_model_destinations"] = []
        self.assertFalse(self.evidence({"task_bundle": value})["ready"])

    def test_evidence_proof_stays_outside_model_payload(self):
        value = bundle("product_intro")
        value["trusted_context"]["source_context_proof"] = "private-synthetic-proof"
        response = self.evidence({"task_bundle": value})
        self.assertTrue(response["ready"])
        self.assertNotIn("private-synthetic-proof", response["payload_json"])

    def test_structured_private_fields_are_blocked_before_a_model(self):
        for key in ("source_context_proof", "raw_p4", "signed_url", "api_key"):
            value = bundle("product_intro")
            value["evidence"]["facts"][0][key] = "synthetic-private-value"
            result = self.evidence({"task_bundle": value})
            self.assertFalse(result["ready"])
            self.assertNotIn("synthetic-private-value", encoded(result))
            quoted = self.client_data()
            quoted["customer_quote_summary"][key] = "synthetic-private-value"
            self.assertFalse(self.client_result(quoted)["ready"])

    def test_scope_task_and_local_competition_claims_are_bound(self):
        for changed in ("scope", "task", "competition"):
            value = bundle("product_intro")
            if changed == "scope": value["trusted_context"]["source_context_ref"] = "different"
            if changed == "task": value["task"]["usage_scenario"] = "different"
            if changed == "competition": value["trusted_context"]["competition_eligible"] = True
            self.assertFalse(self.evidence({"task_bundle": value})["ready"])

    def client_result(self, value):
        current = bundle()
        return invoke(BUILDER.CLIENT_VIEW, status_code=200, body=envelope(value), bundle_json=encoded(current), quote_ref="q-test", quote_version="1", validation_ref="validate-test")

    def client_data(self):
        return {"quote_status": "VALID_OPTIMAL", "client_quote_allowed": True, "validation_ref": "validate-test", "customer_quote_summary": summary()}

    def test_current_quote_summary_and_plan_are_necessary(self):
        good = self.client_data()
        self.assertTrue(self.client_result(good)["ready"])
        for key in ("customer_purchase_plan", "formatted_customer_payable", "customer_resource_snapshot_ref"):
            invalid = copy.deepcopy(good)
            invalid["customer_quote_summary"].pop(key)
            self.assertFalse(self.client_result(invalid)["ready"])

    def test_valid_status_string_cannot_replace_independent_validation_or_permission(self):
        for change in ({"client_quote_allowed": False}, {"validation_ref": "stale"}, {"quote_status": "FEASIBLE_NOT_PROVEN"}):
            self.assertFalse(self.client_result(self.client_data() | change)["ready"])

    def test_quote_expiration_and_timezone_checked_at_consumption(self):
        for expired in ("2000-01-01T00:00:00+08:00", "2099-01-01T00:00:00", "not-a-date", 123):
            invalid = self.client_data()
            invalid["customer_quote_summary"]["valid_until"] = expired
            self.assertFalse(self.client_result(invalid)["ready"])

    def test_cash_objective_is_exact_and_not_merchandise_total(self):
        for key, value in (("customer_payable_minor", 124), ("cash_due_now_minor", True), ("objective_metric", "min_merchandise_total")):
            invalid = self.client_data()
            invalid["customer_quote_summary"][key] = value
            self.assertFalse(self.client_result(invalid)["ready"])

    def test_four_levels_unknown_or_omitted_cannot_be_treated_as_not_applicable(self):
        for change in ("missing", "unknown", "wrong_name", "no_reason"):
            invalid = self.client_data()
            rows = invalid["customer_quote_summary"]["customer_purchase_plan"]["level_rows"]
            if change == "missing": rows.pop()
            if change == "unknown": rows[1]["applicability"] = "unknown"
            if change == "wrong_name": rows[1]["display_name"] = "猜测优惠"
            if change == "no_reason": rows[1].pop("reason")
            self.assertFalse(self.client_result(invalid)["ready"])

    def test_coverage_holes_and_unconnected_multi_sku_are_blocked(self):
        for coverage in ({"same_sku_complete": False, "expected_sku_count": 1, "validated_sku_count": 1}, {"same_sku_complete": True, "expected_sku_count": 2, "validated_sku_count": 1}, {"same_sku_complete": True, "expected_sku_count": 2, "validated_sku_count": 2}):
            invalid = self.client_data()
            invalid["customer_quote_summary"]["customer_purchase_plan"]["comparison_coverage"] = coverage
            self.assertFalse(self.client_result(invalid)["ready"])

    def test_plan_cannot_switch_sku_version_resources_or_channel(self):
        for key, val in (("selected_product_ref", "other-sku"), ("quote_version", "stale"), ("customer_resource_snapshot_version", "other"), ("content_channel", "store_poster")):
            invalid = self.client_data()
            invalid["customer_quote_summary"]["customer_purchase_plan"][key] = val
            self.assertFalse(self.client_result(invalid)["ready"])

    def test_solve_must_be_pending_independent_validation_not_already_approved(self):
        inputs = {"status_code": 200, "bundle_json": encoded(bundle()), "request_json": encoded({"task_version_ref": "t", "purpose_ref": "p", "destination_ref": "d"})}
        pending = {"quote_status": "FEASIBLE_NOT_PROVEN", "reason": "PENDING_INDEPENDENT_VALIDATION", "quote_ref": "q", "quote_version": "1", "dependency_hash": "hash"}
        self.assertTrue(invoke(BUILDER.SOLVE, body=envelope(pending), **inputs)["ready"])
        for change in ({"quote_status": "VALID_OPTIMAL"}, {"reason": "NOT_OPTIMAL"}, {"quote_ref": "../other"}, {"quote_ref": ".."}):
            self.assertFalse(invoke(BUILDER.SOLVE, body=envelope(pending | change), **inputs)["ready"])

    def test_independent_validate_requires_current_ref_version(self):
        inputs = {"status_code": 200, "bundle_json": encoded(bundle()), "quote_ref": "q-test", "quote_version": "1", "request_json": encoded({"quote_version": "1", "purpose_ref": "p", "destination_ref": "d"})}
        good = {"quote_status": "VALID_OPTIMAL", "quote_ref": "q-test", "quote_version": "1", "validation_ref": "v"}
        self.assertTrue(invoke(BUILDER.VALIDATE, body=envelope(good), **inputs)["ready"])
        for change in ({"quote_status": "FEASIBLE_NOT_PROVEN"}, {"validation_ref": None}, {"quote_version": "stale"}):
            self.assertFalse(invoke(BUILDER.VALIDATE, body=envelope(good | change), **inputs)["ready"])

    def test_model_draft_must_bind_exact_customer_plan_and_cash_text(self):
        code = BUILDER.parse_draft("quote_explanation")
        good = explanation()
        self.assertTrue(invoke(code, text=encoded(good), bundle_json=encoded(bundle()))["ready"])
        for key, val in (("purchase_plan_ref", "other"), ("purchase_plan_version", "stale"), ("customer_explanation", "省去现金金额")):
            invalid = copy.deepcopy(good)
            invalid[key] = val
            self.assertFalse(invoke(code, text=encoded(invalid), bundle_json=encoded(bundle()))["ready"])

    def test_review_cannot_bless_unreviewed_cells_or_stale_quote(self):
        value = bundle() | {"draft": explanation(), "current_draft_kind": "quote_explanation"}
        self.assertTrue(invoke(BUILDER.REVIEW_GATE, text=encoded(review()), bundle_json=encoded(value))["ready"])
        for change in ("coverage", "binding", "uncertain", "conflict"):
            invalid = review()
            if change == "coverage": invalid["coverage"]["checked_target_refs"] = []
            if change == "binding": invalid["findings"][0]["quote_binding"]["quote_version"] = "stale"
            if change == "uncertain": invalid["findings"][0]["decision"] = "uncertain"
            if change == "conflict": invalid["conflicts"] = ["unresolved"]
            self.assertFalse(invoke(BUILDER.REVIEW_GATE, text=encoded(invalid), bundle_json=encoded(value))["ready"])

    def test_review_cannot_cover_same_location_after_price_or_other_text_is_appended(self):
        for addition in ("到手1元。", "额外的合成句子尚未审核。"):
            with self.subTest(addition=addition):
                changed = explanation()
                changed["customer_explanation"] += addition
                value = bundle() | {"draft": changed, "current_draft_kind": "quote_explanation"}
                result = invoke(BUILDER.REVIEW_GATE, text=encoded(review()), bundle_json=encoded(value))
                self.assertFalse(result["ready"])
                self.assertIn("VISIBLE_TEXT_NOT_INDEPENDENTLY_REVIEWED", result["message"])

    def test_every_finding_must_quote_nonblank_current_cell_text(self):
        value = bundle() | {"draft": explanation(), "current_draft_kind": "quote_explanation"}
        for text in (None, 123, "", "  ", "不在当前草稿中的文字。", explanation()["customer_explanation"] + "伪造追加文字。"):
            with self.subTest(text=text):
                report = review()
                # Keep a genuine full finding too: a forged additional finding
                # must not be ignored just because coverage already exists.
                report["findings"].append(copy.deepcopy(report["findings"][0]) | {"text": text})
                result = invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(value))
                self.assertFalse(result["ready"])
                self.assertIn("REVIEW_FINDING_TEXT_NOT_IN_CURRENT_CELL", result["message"])

    def test_partial_findings_cannot_jointly_replace_a_whole_cell_finding(self):
        changed = explanation()
        changed["customer_explanation"] += "另一个合成句子。"
        value = bundle() | {"draft": changed, "current_draft_kind": "quote_explanation"}
        report = review()
        report["findings"].append(copy.deepcopy(report["findings"][0]) | {"text": "另一个合成句子。"})
        result = invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(value))
        self.assertFalse(result["ready"])
        self.assertIn("VISIBLE_TEXT_NOT_INDEPENDENTLY_REVIEWED", result["message"])

    def test_exact_whole_cell_plus_current_claim_fragments_is_allowed(self):
        changed = explanation()
        changed["customer_explanation"] += "另一个合成句子。"
        value = bundle() | {"draft": changed, "current_draft_kind": "quote_explanation"}
        report = review()
        report["findings"].append(copy.deepcopy(report["findings"][0]) | {"text": changed["customer_explanation"]})
        self.assertTrue(invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(value))["ready"])

    def test_title_and_cta_require_exact_findings_even_if_claimed_body_is_reviewed(self):
        current = {"status": "ready", "blockers": [],
                   "content": {"type": "product_intro", "title": "合成介绍", "cta": "请描述合成使用场景。",
                               "blocks": [{"text": "仅合成产品事实。"}]},
                   "claims": [{"target": "/content/blocks/0/text", "text": "仅合成产品事实。",
                               "fact_ids": ["f1"], "business_rule_ids": []}]}
        value = bundle("product_intro") | {"draft": current, "current_draft_kind": "product_intro"}
        cells = {"/content/title": "合成介绍", "/content/cta": "请描述合成使用场景。",
                 "/content/blocks/0/text": "仅合成产品事实。"}
        report = {"findings": [{"target_ref": target, "text": text, "decision": "supported",
                                 "evidence_refs": ["f1"] if target.endswith("/text") else []}
                                for target, text in cells.items()],
                  "coverage": {"checked_target_refs": list(cells), "unmapped_claims": []},
                  "conflicts": [], "needs_human_review": False}
        self.assertTrue(invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(value))["ready"])
        for target in ("/content/title", "/content/cta"):
            for remove_checked in (False, True):
                with self.subTest(target=target, remove_checked=remove_checked):
                    invalid = copy.deepcopy(report)
                    invalid["findings"] = [f for f in invalid["findings"] if f["target_ref"] != target]
                    if remove_checked:
                        invalid["coverage"]["checked_target_refs"].remove(target)
                    self.assertFalse(invoke(BUILDER.REVIEW_GATE, text=encoded(invalid), bundle_json=encoded(value))["ready"])

    def test_exact_text_coverage_does_not_replace_quote_and_claim_reference_checks(self):
        value = bundle() | {"draft": explanation(), "current_draft_kind": "quote_explanation"}
        for changed in ("quote-binding", "claim-binding", "evidence-ref"):
            with self.subTest(changed=changed):
                report = review()
                if changed == "quote-binding":
                    report["findings"][0]["quote_binding"]["quote_version"] = "stale"
                elif changed == "claim-binding":
                    report["findings"][0]["quote_binding"] = None
                else:
                    report["findings"][0]["evidence_refs"] = ["forged-evidence"]
                self.assertFalse(invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(value))["ready"])

    def test_renderer_response_does_not_fake_that_a_vision_model_saw_pixels(self):
        for data in ({}, {"png_ref": "synthetic", "png_hash": "synthetic", "visual_review_passed": True}):
            result = invoke(BUILDER.RENDER, status_code=200, body=envelope(data), bundle_json=encoded(bundle()))
            self.assertFalse(result["ready"])
            self.assertIn("VISION_FILE_ADAPTER_NOT_IMPLEMENTED", result["message"])

    def test_missing_server_script_bindings_cannot_be_invented(self):
        self.assertFalse(invoke(BUILDER.SCRIPT_REQUEST, bundle_json=encoded(bundle("sales_script")), script_request_json="{}")["ready"])

    def test_marketing_cannot_finalize_without_visual_path(self):
        value = bundle("marketing")
        value["reviewed_artifacts"] = {"article": {"draft": {}, "review": {}, "content_hash": "synthetic"}}
        self.assertFalse(invoke(BUILDER.FINALIZE_REQUEST, bundle_json=encoded(value))["ready"])
        value["task"]["script_required"] = False
        self.assertFalse(invoke(BUILDER.VERIFY_REQUEST, bundle_json=encoded(value))["ready"])

    def test_finalizer_cannot_release_stale_or_unauthorized_content(self):
        request = {"content_hash": "hash", "source_snapshot_ref": "snap"}
        good = {"delivery_allowed": True, "artifact_manifest_ref": "manifest-test", "content_hash": "hash", "source_snapshot_ref": "snap", "customer_text": "仅合成最终文本"}
        result = invoke(BUILDER.FINALIZE_RESPONSE, status_code=200, body=envelope(good), request_json=encoded(request))
        self.assertTrue(result["ready"])
        for change in ({"delivery_allowed": False}, {"content_hash": "stale"}, {"source_snapshot_ref": "stale"}, {"artifact_manifest_ref": None}):
            self.assertFalse(invoke(BUILDER.FINALIZE_RESPONSE, status_code=200, body=envelope(good | change), request_json=encoded(request))["ready"])

    def test_graph_has_only_reviewed_node_types_no_llm_answer_bypass_and_exact_systems(self):
        prompts = {role: "synthetic static system: " + role for role in BUILDER.BASE.PROMPT_FILES}
        graph = BUILDER.build_graph(prompts, model_bindings())
        BUILDER.validate_graph(graph)
        nodes = {n["id"]: n for n in graph["nodes"]}
        for value in nodes.values():
            data = value["data"]
            self.assertIn(data["type"], BUILDER.ALLOWED_NODE_TYPES)
            if data["type"] == "llm":
                self.assertIn(data["prompt_template"][0]["text"], prompts.values())
                self.assertFalse(data["vision"]["enabled"])
            if data["type"] == "code":
                compile(data["code"], value["id"], "exec")
        self.assertEqual(nodes["scene_parse"]["data"]["memory"]["query_prompt_template"], "{{#sys.query#}}")
        self.assertEqual(nodes["client_view"]["data"]["method"], "get")
        self.assertIn("X-Source-Context-Proof", nodes["quote_solve"]["data"]["headers"])
        self.assertFalse(any(nodes[e["source"]]["data"]["type"] == "llm" and nodes[e["target"]]["data"]["type"] == "answer" for e in graph["edges"]))

    def test_graph_failure_branches_never_enter_writer_or_solver(self):
        graph = BUILDER.build_graph({role: role for role in BUILDER.BASE.PROMPT_FILES}, model_bindings())
        nodes = {n["id"]: n for n in graph["nodes"]}
        for edge in graph["edges"]:
            if edge["source"] == "source_failure_routes":
                self.assertIn(nodes[edge["target"]]["data"]["type"], {"answer", "variable-aggregator"})
        targets = [e["target"] for e in graph["edges"] if e["source"] == "task_routes" and e["sourceHandle"] == "marketing"]
        self.assertEqual(targets, ["marketing_scope"])
        self.assertEqual([e["target"] for e in graph["edges"] if e["source"] == "marketing_delivery_routes" and e["sourceHandle"] == "complete_package"], ["quote_solve"])
        self.assertNotIn("visual_review", nodes)  # Never pretend a text JSON call saw pixels.

    def test_bounded_native_history_is_only_for_parser_and_current_query_is_not_duplicated(self):
        graph = BUILDER.build_graph({role: role for role in BUILDER.BASE.PROMPT_FILES}, model_bindings())
        nodes = {node["id"]: node for node in graph["nodes"]}
        scene = nodes["scene_parse"]["data"]
        self.assertEqual(scene["memory"]["window"], {"enabled": True, "size": 8})
        current_occurrences = sum(message["text"].count("{{#sys.query#}}") for message in scene["prompt_template"])
        current_occurrences += scene["memory"]["query_prompt_template"].count("{{#sys.query#}}")
        self.assertEqual(current_occurrences, 1)
        self.assertEqual([message["role"] for message in scene["prompt_template"]], ["system"])
        for node in graph["nodes"]:
            if node["data"]["type"] == "llm" and node["id"] != "scene_parse":
                self.assertIsNone(node["data"]["memory"], node["id"])
        self.assertEqual(nodes["normalize"]["data"]["variables"][0]["value_selector"], ["scene_parse", "text"])
        BUILDER.validate_graph(graph)

    def test_history_intent_does_not_reuse_old_source_proof_quote_or_permissions(self):
        current = task("marketing") | {"delivery_scope": "content_only", "quote_required": False,
                    "purchase_plan_required": False, "script_required": False, "sales_platform": None,
                    "usage_scenario": "本轮明确修正的任务", "quote_ref": "old-price-reference",
                    "source_context_ref": "old-source-reference", "source_context_proof": "old-proof-value",
                    "trusted_context": {"tenant_id": "old-tenant-authority"},
                    "history": {"quote_status": "VALID_OPTIMAL", "export_allowed": True}}
        normalized = self.normalize(current)
        self.assertTrue(normalized["ready"])
        parsed = json.loads(normalized["payload_json"])
        self.assertEqual(set(parsed), {"task"})
        self.assertEqual(parsed["task"]["usage_scenario"], "本轮明确修正的任务")
        scope = {"source_context_ref": "new-source-reference", "source_context_proof": "new-proof-value",
                 "purpose_ref": "current-purpose", "destination_ref": "current-destination"}
        scoped = invoke(BUILDER.SCOPE, status_code=200, body=envelope(scope), request_json=normalized["payload_json"])
        self.assertTrue(scoped["ready"])
        self.assertEqual(scoped["scope_ref"], "new-source-reference")
        self.assertEqual(scoped["proof"], "new-proof-value")
        self.assertNotIn("new-proof-value", scoped["payload_json"])
        for marker in ("old-price-reference", "old-source-reference", "old-proof-value", "old-tenant-authority", "VALID_OPTIMAL"):
            self.assertNotIn(marker, encoded(normalized) + encoded(scoped))

    def test_missing_hard_conditions_use_bounded_fixed_questions_not_model_prose(self):
        parsed = {"status": "needs_input", "missing_fields": ["hard_requirements", "required_fact_fields", "problem", "content_goal", "quote_inputs.region", "quote_inputs.quantity"],
                  "questions": ["PRIVATE_MODEL_PROSE_AND_FALSE_PRICE_MUST_NOT_ECHO"]}
        result = invoke(BUILDER.NORMALIZE, text=encoded(parsed))
        self.assertFalse(result["ready"])
        self.assertIn("必须使用的软件、系统或外设", result["message"])
        self.assertEqual(len(result["message"].splitlines()) - 1, 3)
        self.assertNotIn("PRIVATE_MODEL_PROSE", result["message"])
        for missing, expected in (("content_goal", "了解什么或采取什么行动"), ("quote_inputs.region", "哪个地区"), ("quote_inputs.quantity", "几台或几件")):
            single = invoke(BUILDER.NORMALIZE, text=encoded(parsed | {"missing_fields": [missing]}))
            self.assertIn(expected, single["message"])

    def test_current_failure_message_precedes_all_executed_success_messages(self):
        graph = BUILDER.build_graph({role: role for role in BUILDER.BASE.PROMPT_FILES}, model_bindings())
        nodes = {n["id"]: n for n in graph["nodes"]}
        selectors = nodes["error_aggregate"]["data"]["variables"]
        parents = {key: set() for key in nodes}
        for edge in graph["edges"]:
            parents[edge["target"]].add(edge["source"])
        for failed, _ in selectors:
            earlier, pending = set(), list(parents[failed])
            while pending:
                key = pending.pop()
                if key not in earlier:
                    earlier.add(key)
                    pending.extend(parents[key])
            # Only executed ancestors exist in the variable pool. This uses the
            # upstream aggregator's first-existing-variable rule, not a join.
            pool = {(key, "message"): "" for key in earlier if nodes[key]["data"]["type"] == "code"}
            pool[(failed, "message")] = "BLOCKED: " + failed
            selected = next(pool[tuple(s)] for s in selectors if tuple(s) in pool)
            self.assertEqual(selected, "BLOCKED: " + failed)

    def test_http_transport_errors_have_safe_explicit_branch_and_no_retry(self):
        graph = BUILDER.build_graph({role: role for role in BUILDER.BASE.PROMPT_FILES}, model_bindings())
        for node in graph["nodes"]:
            if node["data"]["type"] != "http-request":
                continue
            self.assertEqual(node["data"]["error_strategy"], "fail-branch")
            self.assertFalse(node["data"]["retry_config"]["retry_enabled"])
            outgoing = [e for e in graph["edges"] if e["source"] == node["id"]]
            self.assertEqual({e["sourceHandle"] for e in outgoing}, {"source", "fail-branch"})
            self.assertTrue(any(e["target"] == "http_failure_answer" and e["sourceHandle"] == "fail-branch" for e in outgoing))

    def test_wrong_selector_or_branch_handle_is_detected(self):
        graph = BUILDER.build_graph({role: role for role in BUILDER.BASE.PROMPT_FILES}, model_bindings())
        invalid = copy.deepcopy(graph)
        next(n for n in invalid["nodes"] if n["id"] == "quote_pending")["data"]["variables"][0]["value_selector"] = ["quote_solve", "nonexistent"]
        with self.assertRaisesRegex(ValueError, "UNKNOWN_OR_NON_UPSTREAM_SELECTOR"):
            BUILDER.validate_graph(invalid)
        invalid = copy.deepcopy(graph)
        next(e for e in invalid["edges"] if e["source"] == "quote_solve")["sourceHandle"] = "success-branch"
        with self.assertRaisesRegex(ValueError, "INVALID_HTTP_FAIL_BRANCH_HANDLE"):
            BUILDER.validate_graph(invalid)

    def test_no_credentials_no_missing_model_candidate_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "bundle"
            with self.assertRaisesRegex(ValueError, "MISSING_REAL_MODEL_BINDING"):
                BUILDER.create_bundle(out, {}, False)
            self.assertFalse(out.exists())
            with self.assertRaisesRegex(ValueError, "CONFIG_MUST_NOT_CONTAIN_CREDENTIALS"):
                BUILDER.create_bundle(out, {"api_key": "synthetic-secret"}, True)
            BUILDER.create_bundle(out, {}, True)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertFalse(manifest["full_application_ready"])
            self.assertEqual(manifest["runtime_status"], "NOT_RUN")
            self.assertFalse((out / "full-workflow.candidate.yml").exists())
            with self.assertRaisesRegex(ValueError, "OUTPUT_ALREADY_EXISTS"):
                BUILDER.create_bundle(out, {}, True)

    def test_synthetic_candidate_preserves_static_systems_and_never_claims_import(self):
        config = {"models": {slot: {"provider": "synthetic-provider", "name": "synthetic-review" if slot == "MODEL_REVIEW" else "synthetic-text"} for slot in set(BUILDER.MODEL_SLOTS.values())}}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "candidate"
            BUILDER.create_bundle(out, config, False)
            dsl = json.loads((out / "full-workflow.candidate.yml").read_text())
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["import_status"], "IMPORT_NOT_RUN")
            self.assertEqual(manifest["runtime_status"], "NOT_RUN")
            self.assertFalse(manifest["full_application_ready"])
            self.assertEqual(dsl["version"], "0.7.0")
            for filename in BUILDER.BASE.PROMPT_FILES.values():
                self.assertEqual((out / "prompts" / filename).read_bytes(), (ROOT / "prompts" / filename).read_bytes())
            self.assertTrue(all(not item["value"] for item in dsl["workflow"]["environment_variables"]))

    def test_manifest_cannot_claim_unconnected_parts_or_runtime_success(self):
        value = BUILDER.status_manifest()
        self.assertFalse(value["full_application_ready"])
        self.assertEqual(value["import_status"], "IMPORT_NOT_RUN")
        self.assertEqual(value["runtime_status"], "NOT_RUN")
        self.assertTrue(value["not_connected"])


class ContentOnlyMarketingContracts(unittest.TestCase):
    """Synthetic branch traversal/contracts; no real marketing success claimed."""
    def unpriced(self, channel="moments"):
        value = bundle("marketing")
        value["task"].update(delivery_scope="content_only", quote_required=False,
                             purchase_plan_required=False, script_required=False,
                             sales_platform=None, content_channel=channel)
        needed = {"fact_compliance_review", "platform_strategy", "visual_layout", "visual_review",
                  "poster_copy" if channel == "store_poster" else "article_write"}
        value["policy"]["required_model_nodes"] = sorted(needed)
        value["policy"]["allowed_model_destinations"] = [row for row in destinations() if row["node_id"] in needed]
        value["policy"]["allowed_model_destinations"].append({"node_id": "visual_review", "provider": "synthetic-provider", "model": "synthetic-vision"})
        value["quote_context"] = {"quote_required": False, "purchase_plan_required": False,
                                  "quote_status": None, "quote_ref": None,
                                  "client_quote_allowed": False, "customer_quote_summary": None}
        return value

    def normalized(self, value):
        return invoke(BUILDER.NORMALIZE, text=encoded({"status": "ready", "task": value}))

    def expected_destinations(self):
        return destinations() + [{"node_id": "visual_review", "provider": "synthetic-provider", "model": "synthetic-vision"}]

    def evidence(self, value):
        code = BUILDER.EVIDENCE.replace("__EXPECTED__", repr(self.expected_destinations()))
        return invoke(code, status_code=200, body=envelope({"task_bundle": value, "quote_request": {"raw_p4": "MUST_NOT_FORWARD"}}),
                      task_json=encoded({"task": value["task"]}), scope_ref="scope-test")

    def draft(self, channel="moments"):
        count = {"wechat_article": 2, "xiaohongshu": 3, "moments": 1, "store_poster": 1}[channel]
        content = {"type": "article", "title": "合成任务说明", "lead": "先核对当前任务。",
                   "blocks": [{"block_id": "body", "heading": "任务与证据", "text": "仅合成产品事实。"}],
                   "cta": "请确认要完成的任务。", "tags": ["合成任务"]}
        target = "/content/blocks/0/text"
        if channel == "store_poster":
            content = {"type": "poster", "headline": "合成任务说明", "subtitle": "先核对当前任务。",
                       "benefits": [{"benefit_id": "benefit-one", "text": "仅合成产品事实。", "claim_ids": ["claim-one"]}],
                       "activity": None, "store": None, "cta": "请确认要完成的任务。", "tags": ["合成任务"]}
            target = "/content/benefits/0/text"
        return {"status": "ready", "content": content, "knowledge_basis": [{"source_ref_id": "s1", "fact_ids": ["f1"], "business_rule_ids": []}],
                "claims": [{"claim_id": "claim-one", "target": target, "text": "仅合成产品事实。", "fact_ids": ["f1"], "business_rule_ids": [], "quote_binding": None}],
                "image_plan": [{"asset_id": "image-" + str(i), "source_ref_id": "s1", "caption": "合成测试图片说明。", "position": "hero" if channel == "store_poster" else "body", "purpose": "仅合成合同测试"} for i in range(count)],
                "purchase_plan": None, "open_questions": [], "blockers": []}

    def with_images(self, channel="moments"):
        value, draft = self.unpriced(channel), self.draft(channel)
        value["allowed_assets"] = [{"asset_id": row["asset_id"], "source_ref_id": "s1"} for row in draft["image_plan"]]
        return value, draft

    def test_explicit_content_only_is_marketing_without_sales_platform_or_price(self):
        for channel in ("wechat_article", "xiaohongshu", "moments", "store_poster"):
            value = self.unpriced(channel)
            result = self.normalized(value["task"])
            self.assertTrue(result["ready"], result)
            current = json.loads(result["payload_json"])["task"]
            self.assertEqual(current["task_kind"], "marketing")
            self.assertEqual(current["delivery_scope"], "content_only")
            self.assertIsNone(current["sales_platform"])
            for flag in ("quote_required", "purchase_plan_required", "script_required"):
                self.assertIs(current[flag], False)

    def test_omitted_or_complete_scope_never_uses_false_flags_as_downgrade(self):
        for kind in ("marketing", "full_package", "quote", "sales_script"):
            for scope in (None, "complete_package"):
                current = task(kind) | {"quote_required": False, "purchase_plan_required": False}
                if scope is not None:
                    current["delivery_scope"] = scope
                parsed = self.normalized(current)
                self.assertTrue(parsed["ready"], parsed)
                normalized = json.loads(parsed["payload_json"])["task"]
                self.assertEqual(normalized["delivery_scope"], "complete_package")
                self.assertIs(normalized["quote_required"], True)
                self.assertIs(normalized["purchase_plan_required"], True)
                current["sales_platform"] = None
                self.assertFalse(self.normalized(current)["ready"])

    def test_content_only_scope_cannot_hide_quote_script_or_wrong_task_kind(self):
        for field in ("quote_required", "purchase_plan_required", "script_required"):
            current = self.unpriced()["task"] | {field: True}
            self.assertFalse(self.normalized(current)["ready"])
        for kind in ("full_package", "quote", "sales_script", "product_intro"):
            self.assertFalse(self.normalized(task(kind) | {"delivery_scope": "content_only"})["ready"])
        for scope in ("", "auto", None, False, [], {}):
            self.assertFalse(self.normalized(task() | {"delivery_scope": scope})["ready"])

    def test_preliminary_strategy_precedes_retrieval_without_inventing_capabilities(self):
        value = self.unpriced("xiaohongshu")
        first = invoke(BUILDER.PRE_STRATEGY, request_json=encoded({"task": value["task"]}))
        self.assertTrue(first["ready"])
        intent = json.loads(first["payload_json"])["retrieval_intent"]
        self.assertEqual(intent["stage"], "pre_retrieval_intent_only")
        self.assertIs(intent["product_capabilities_asserted"], False)
        self.assertIs(intent["facts_verified"], False)
        self.assertEqual(intent["editorial_intent"]["image_count_range"], [3, 6])
        scope = {"source_context_ref": "scope-test", "source_context_proof": "private-synthetic-proof", "purpose_ref": "purpose-test", "destination_ref": "destination-test"}
        scoped = invoke(BUILDER.SCOPE, status_code=200, body=envelope(scope), request_json=first["payload_json"])
        self.assertTrue(scoped["ready"])
        request = json.loads(scoped["payload_json"])
        self.assertEqual(request["retrieval_intent"], intent)
        self.assertIs(request["need_pricing_rules"], False)
        self.assertIs(request["need_images"], True)
        self.assertNotIn("private-synthetic-proof", first["payload_json"])

    def test_content_only_evidence_preserves_real_marketing_and_visual_grants(self):
        value = self.unpriced()
        response = self.evidence(value)
        self.assertTrue(response["ready"], response)
        approved = json.loads(response["payload_json"])
        self.assertEqual(approved["task"]["task_kind"], "marketing")
        self.assertEqual(approved["retrieval_intent"]["platform"], "moments")
        self.assertEqual(response["tool_json"], "{}")
        self.assertNotIn("MUST_NOT_FORWARD", encoded(response))
        for role in ("visual_review", "visual_layout", "platform_strategy", "article_write", "fact_compliance_review"):
            invalid = copy.deepcopy(value)
            invalid["policy"]["allowed_model_destinations"] = [row for row in invalid["policy"]["allowed_model_destinations"] if row["node_id"] != role]
            self.assertFalse(self.evidence(invalid)["ready"], role)

    def test_content_only_missing_visual_binding_is_still_blocked(self):
        value = self.unpriced()
        code = BUILDER.EVIDENCE.replace("__EXPECTED__", repr(destinations()))
        result = invoke(code, status_code=200, body=envelope({"task_bundle": value}), task_json=encoded({"task": value["task"]}), scope_ref="scope-test")
        self.assertFalse(result["ready"])

    def test_mutually_exclusive_input_join_revalidates_both_contracts(self):
        unpriced = self.unpriced()
        self.assertEqual(invoke(BUILDER.MARKETING_SCOPE, bundle_json=encoded(unpriced))["route"], "content_only")
        self.assertTrue(invoke(BUILDER.CONTENT_ONLY_INPUT, bundle_json=encoded(unpriced))["ready"])
        self.assertTrue(invoke(BUILDER.MARKETING_INPUT, selected_json=encoded(unpriced))["ready"])
        priced = bundle("marketing")
        priced["quote_context"]["customer_quote_summary"]["customer_purchase_plan"]["content_channel"] = "moments"
        self.assertEqual(invoke(BUILDER.MARKETING_SCOPE, bundle_json=encoded(priced))["route"], "complete_package")
        self.assertTrue(invoke(BUILDER.MARKETING_INPUT, selected_json=encoded(priced))["ready"])
        self.assertFalse(invoke(BUILDER.CONTENT_ONLY_INPUT, bundle_json=encoded(priced))["ready"])
        for source in ({}, [], {"task": task("product_intro")}, bundle("marketing")):
            self.assertFalse(invoke(BUILDER.MARKETING_INPUT, selected_json=encoded(source))["ready"])

    def test_no_price_input_cannot_carry_stale_quote_or_prior_artifact(self):
        for key, value in (("quote_status", "VALID_OPTIMAL"), ("quote_ref", "old-quote"),
                           ("validation_ref", "old-validation"), ("quote_version", "1"),
                           ("customer_quote_summary", summary()), ("client_quote_allowed", True)):
            current = self.unpriced(); current["quote_context"][key] = value
            self.assertFalse(invoke(BUILDER.MARKETING_INPUT, selected_json=encoded(current))["ready"])
        for key in ("draft", "reviewed_artifacts", "content_verification_ref"):
            current = self.unpriced(); current[key] = {}
            self.assertFalse(invoke(BUILDER.MARKETING_INPUT, selected_json=encoded(current))["ready"])
        for flag in ("quote_required", "purchase_plan_required", "script_required"):
            current = self.unpriced(); current["task"][flag] = True
            self.assertFalse(invoke(BUILDER.MARKETING_SCOPE, bundle_json=encoded(current))["ready"])

    def test_all_platform_image_counts_and_poster_benefit_limit_still_apply(self):
        for channel in ("wechat_article", "xiaohongshu", "moments", "store_poster"):
            value, draft = self.with_images(channel)
            kind = "poster" if channel == "store_poster" else "article"
            code = BUILDER.parse_draft(kind)
            self.assertTrue(invoke(code, text=encoded(draft), bundle_json=encoded(value))["ready"])
            for failure in ("short", "duplicate", "unknown"):
                invalid = copy.deepcopy(draft)
                if failure == "short": invalid["image_plan"].pop()
                if failure == "duplicate": invalid["image_plan"].append(copy.deepcopy(invalid["image_plan"][0]))
                if failure == "unknown": invalid["image_plan"][0]["asset_id"] = "unapproved-image"
                self.assertFalse(invoke(code, text=encoded(invalid), bundle_json=encoded(value))["ready"], (channel, failure))
        value, draft = self.with_images("store_poster")
        draft["content"]["benefits"] *= 4
        self.assertFalse(invoke(BUILDER.parse_draft("poster"), text=encoded(draft), bundle_json=encoded(value))["ready"])

    def test_unpriced_generation_cannot_add_amounts_or_quote_metadata_with_fact_id(self):
        value, draft = self.with_images()
        for sentence in ("到手价100元。", "仅需CNY 10。", "现在九折，一千元。", "立减活动。"):
            current = copy.deepcopy(draft)
            current["content"]["blocks"][0]["text"] = sentence
            current["claims"][0]["text"] = sentence
            self.assertFalse(invoke(BUILDER.parse_draft("article"), text=encoded(current), bundle_json=encoded(value))["ready"])
        for key, item in (("quote_ref", "q-test"), ("purchase_plan", {"plan_ref": "p-test"})):
            current = copy.deepcopy(draft); current[key] = item
            self.assertFalse(invoke(BUILDER.parse_draft("article"), text=encoded(current), bundle_json=encoded(value))["ready"])

    def test_no_price_route_keeps_evidence_strategy_and_whole_text_review(self):
        value, draft = self.with_images()
        strategy = {"status": "ready", "blockers": [], "platform": "moments", "priority_points": [{"fact_ids": ["f1"], "business_rule_ids": []}]}
        self.assertTrue(invoke(BUILDER.STRATEGY, text=encoded(strategy), bundle_json=encoded(value))["ready"])
        invalid = copy.deepcopy(strategy); invalid["priority_points"][0]["fact_ids"] = []
        self.assertFalse(invoke(BUILDER.STRATEGY, text=encoded(invalid), bundle_json=encoded(value))["ready"])
        parsed = invoke(BUILDER.parse_draft("article"), text=encoded(draft), bundle_json=encoded(value))
        namespace = {}; exec(BUILDER.COMMON, namespace)
        cells = namespace["visible_cells"](draft)
        report = {"findings": [{"target_ref": target, "text": text, "decision": "supported", "evidence_refs": ["f1"]} for target, text in cells.items()],
                  "coverage": {"checked_target_refs": list(cells), "unmapped_claims": []}, "conflicts": [], "needs_human_review": False}
        self.assertTrue(invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=parsed["payload_json"])["ready"])
        for target in ("/content/title", "/content/cta", "/image_plan/0/caption"):
            invalid = copy.deepcopy(report); invalid["findings"] = [row for row in invalid["findings"] if row["target_ref"] != target]
            self.assertFalse(invoke(BUILDER.REVIEW_GATE, text=encoded(invalid), bundle_json=parsed["payload_json"])["ready"])

    def test_no_price_route_does_not_skip_visual_or_finalizer_blocks(self):
        value, draft = self.with_images()
        value["reviewed_artifacts"] = {"article": {"draft": draft, "review": {}, "content_hash": "synthetic"}}
        layout = {"status": "ready", "blockers": [], "mode": "article"}
        self.assertIn("ARTICLE_VISUAL_INPUT_ADAPTER_NOT_IMPLEMENTED", invoke(BUILDER.LAYOUT, text=encoded(layout), bundle_json=encoded(value))["message"])
        self.assertFalse(invoke(BUILDER.FINALIZE_REQUEST, bundle_json=encoded(value))["ready"])
        self.assertFalse(invoke(BUILDER.RENDER, status_code=200, body=envelope({"png_ref": "synthetic", "visual_review_passed": True}), bundle_json=encoded(value))["ready"])

    def test_graph_content_only_reaches_marketing_nodes_without_any_quote_node(self):
        graph = BUILDER.build_graph({role: role for role in BUILDER.BASE.PROMPT_FILES}, model_bindings())
        nodes = {node["id"]: node for node in graph["nodes"]}
        adjacency = {node: [] for node in nodes}
        for edge in graph["edges"]: adjacency[edge["source"]].append(edge["target"])
        seen, pending = set(), ["content_only_input"]
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current); pending.extend(adjacency[current])
        self.assertTrue({"platform_strategy", "article_write", "poster_copy", "article_write_review", "poster_copy_review", "article_write_layout", "poster_render"} <= seen)
        self.assertFalse({"quote_solve", "quote_validate", "client_view", "quote_explain", "product_intro"} & seen)
        self.assertEqual(nodes["platform_strategy"]["data"]["prompt_template"][1]["text"], "{{#marketing_input.payload_json#}}")
        selectors = nodes["marketing_bundle"]["data"]["variables"]
        for active in ("quote_explain_review_gate", "content_only_input"):
            pool = {(active, "payload_json"): "synthetic-active-bundle"}
            self.assertEqual(next(pool[tuple(s)] for s in selectors if tuple(s) in pool), "synthetic-active-bundle")
        order = BUILDER.topological_order(graph)
        self.assertLess(order.index("preliminary_strategy"), order.index("scope"))
        self.assertLess(order.index("preliminary_strategy"), order.index("evidence"))
        BUILDER.validate_graph(graph)


class FullReviewFormatContracts(unittest.TestCase):
    MESSAGE = "审核返回的格式不符合约定，本次内容未放行。请重新发起任务；应用不会将格式错误视为审核通过。"

    def current_bundle(self):
        return bundle() | {"draft": explanation(), "current_draft_kind": "quote_explanation"}

    def test_full_strict_review_format_failures_are_distinct_and_never_echoed(self):
        raws = ['{"findings":[{"text":"PRIVATE_ATTACK\nDO_NOT_ECHO"}]}', "```json\n" + encoded(review()) + "\n```",
                '{"findings":[],"findings":["PRIVATE_ATTACK"]}', '{"findings":[{"text":"first","text":"PRIVATE_ATTACK"}]}',
                '{"value":NaN}', '{"value":Infinity}', '[]', '"PRIVATE_ATTACK"', 'null', '{',
                '{"x":"PRIVATE_ATTACK' + 'x' * 200000 + '"}', '[' * 2000 + '0' + ']' * 2000, None]
        for raw in raws:
            with self.subTest(kind=type(raw).__name__, prefix=raw[:24] if isinstance(raw, str) else None):
                result = invoke(BUILDER.REVIEW_GATE, text=raw, bundle_json=encoded(self.current_bundle()))
                self.assertFalse(result["ready"])
                self.assertEqual(result["message"], self.MESSAGE)
                self.assertEqual(result["payload_json"], "{}")
                self.assertEqual(result["tool_json"], "{}")
                self.assertNotIn("PRIVATE_ATTACK", encoded(result))
                self.assertNotIn("DO_NOT_ECHO", encoded(result))
                self.assertNotIn("reviewed_artifacts", result["payload_json"])

    def test_full_valid_json_retains_existing_schema_semantic_reference_and_binding_blocks(self):
        result = invoke(BUILDER.REVIEW_GATE, text="{}", bundle_json=encoded(self.current_bundle()))
        self.assertFalse(result["ready"])
        self.assertEqual(result["message"], "BLOCKED: REVIEW_UNRESOLVED")
        report = review(); report["findings"][0]["decision"] = "unsupported"
        semantic = invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(self.current_bundle()))
        self.assertEqual(semantic["message"], "BLOCKED: REVIEW_FINDING_BLOCKING_OR_POINTER_INVALID")
        report = review(); report["findings"][0]["evidence_refs"] = ["invented-reference"]
        reference = invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(self.current_bundle()))
        self.assertEqual(reference["message"], "BLOCKED: REVIEW_REFERENCE_INVALID")
        malformed_bundle = invoke(BUILDER.REVIEW_GATE, text=encoded(review()), bundle_json="{")
        self.assertEqual(malformed_bundle["message"], "BLOCKED: INDEPENDENT_REVIEW_INVALID")

    def test_full_valid_escaped_newline_is_normal_json_data_without_repair(self):
        report = review()
        report["findings"][0]["reason"] = "合成理由第一行\n第二行"
        result = invoke(BUILDER.REVIEW_GATE, text=encoded(report), bundle_json=encoded(self.current_bundle()))
        self.assertTrue(result["ready"])
        retained = json.loads(result["payload_json"])["reviewed_artifacts"]["quote_explanation"]["review"]
        self.assertEqual(retained, report)


class FullScopeMessageContracts(unittest.TestCase):
    def scope(self, state, reason, *, status_code=200, body=None):
        if body is None:
            body = encoded({"status": state, "data": {"reason": reason, "source_context_proof": "PRIVATE_PROOF",
                "questions": ["PRIVATE_QUESTION"], "headers": {"Authorization": "PRIVATE_HEADER"},
                "url": "https://invalid.example/PRIVATE_URL"}, "error": "PRIVATE_ERROR"})
        return invoke(BUILDER.SCOPE, status_code=status_code, body=body, request_json=encoded({"task": task()}))

    def test_full_scope_known_states_have_fixed_safe_messages(self):
        cases = [("needs_source", "IMA_FACT_VERIFICATION_FAILED", "本次尚未完成 ima 原文核验，未生成内容。请检查知识库访问、网络与所用资料版本后重试；应用不会自动切换到未核验来源。"),
                 ("needs_source", "IMA_DAILY_SOURCE_LIMIT_REACHED", "ima今日资料读取次数已达上限，接口提示明天再尝试。本次未完成参赛来源核验；请稍后重试，或明确使用本地开发模式进行调试。本地候选不能作为参赛核验通过记录。"),
                 ("needs_source", "SOURCE_MODE_NOT_IMPLEMENTED", "当前来源模式尚未启用，未生成内容。请启用并核验所需知识来源后重试；应用不会自动切换到其他来源。"),
                 ("needs_input", "PRODUCT_AMBIGUOUS_OR_MISSING", "请确认完整产品型号、年份或系统版本及相关配置后重试。型号尚未明确，暂未生成内容。")]
        for state, reason, message in cases:
            result = self.scope(state, reason)
            self.assertFalse(result["ready"])
            self.assertEqual(result["message"], message)
            self.assertEqual((result["payload_json"], result["scope_ref"], result["proof"]), ("{}", "", ""))
            self.assertNotIn("PRIVATE_", encoded(result))
            self.assertEqual(result, self.scope(state, reason, body=encoded({"status": state, "data": {"reason": reason}})))

    def test_full_scope_unknown_reason_wrong_state_and_http_error_keep_block(self):
        for state, reason, status in [("needs_source", "unknown", 200), ("denied", "IMA_FACT_VERIFICATION_FAILED", 200),
                ("needs_input", "SOURCE_MODE_NOT_IMPLEMENTED", 200), ("error", "PRODUCT_AMBIGUOUS_OR_MISSING", 200),
                ("needs_source", "IMA_FACT_VERIFICATION_FAILED", 403), ("needs_source", "IMA_FACT_VERIFICATION_FAILED", 500),
                ("error", "IMA_DAILY_SOURCE_LIMIT_REACHED", 200), ("needs_source", "IMA_DAILY_SOURCE_LIMIT_REACHED", 429)]:
            self.assertEqual(self.scope(state, reason, status_code=status)["message"], "BLOCKED: SOURCE_SCOPE_NOT_READY")

    def test_full_scope_malformed_json_and_non_object_details_keep_block(self):
        for raw in ("{", "[]", '```json\n{}\n```', '{"status":"needs_source","status":"needs_source","data":{"reason":"IMA_FACT_VERIFICATION_FAILED"}}',
                    '{"status":"needs_source","data":{"reason":"IMA_FACT_VERIFICATION_FAILED","x":NaN}}',
                    '{"status":"needs_source","data":null,"reason":"IMA_FACT_VERIFICATION_FAILED"}'):
            self.assertEqual(self.scope(None, None, body=raw)["message"], "BLOCKED: SOURCE_SCOPE_NOT_READY")

    def test_full_ready_scope_reason_cannot_replace_required_binding(self):
        body = envelope({"reason": "IMA_FACT_VERIFICATION_FAILED", "source_context_ref": "scope-test", "source_context_proof": "synthetic-proof",
                         "purpose_ref": "purpose-test", "destination_ref": "destination-test"})
        result = self.scope(None, None, body=body)
        self.assertTrue(result["ready"])
        self.assertEqual(result["proof"], "synthetic-proof")
        self.assertEqual(result["message"], "")
        self.assertFalse(self.scope(None, None, body=envelope({"reason": "IMA_FACT_VERIFICATION_FAILED"}))["ready"])


class FullSourceProjectionContracts(unittest.TestCase):
    evidence = FullBundleContracts.evidence

    def test_full_hybrid_evidence_retains_only_safe_exact_selected_file_receipt(self):
        current = hybrid_bundle()
        current["trusted_context"]["source_context_proof"] = "PRIVATE_PROOF_NOT_FOR_MODEL"
        result = self.evidence({"task_bundle": current}, value=current)
        self.assertTrue(result["ready"])
        projected = json.loads(result["payload_json"])["trusted_context"]
        self.assertEqual(projected["ima_verification"], current["trusted_context"]["ima_verification"])
        self.assertEqual(projected["ima_provenance"], "selected_fact_file_original_hash_matched")
        self.assertFalse(projected["competition_eligible"])
        self.assertNotIn("PRIVATE_PROOF_NOT_FOR_MODEL", result["payload_json"])

    def test_full_hybrid_missing_extra_private_or_tampered_manifest_is_blocked(self):
        for key in (None, "schema_version", "sha256", "source_document_ref", "task_hash", "verified_at"):
            current = hybrid_bundle()
            if key is None: del current["trusted_context"]["ima_verification"]
            else: del current["trusted_context"]["ima_verification"][key]
            self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"], key)
        for key in ("api_key", "url", "headers", "source_context_proof", "signed_url", "extra"):
            current = hybrid_bundle(); current["trusted_context"]["ima_verification"][key] = "PRIVATE_VALUE https://not-allowed.invalid"
            result = self.evidence({"task_bundle": current}, value=current)
            self.assertFalse(result["ready"], key)
            self.assertNotIn("PRIVATE_VALUE", result["payload_json"] + result["message"])
        for key, value in (("task_hash", "d" * 64), ("snapshot_ref", "other-snap"), ("source_context_ref", "other-scope"),
                           ("product_ref", "other-product"), ("mapping_hash", "not-hex"), ("byte_length", True),
                           ("scope", "all_library"), ("matched_file_count", 2), ("competition_verified", True),
                           ("p4_rules_verified", True), ("expires_at", time.time() - 1)):
            current = hybrid_bundle(); current["trusted_context"]["ima_verification"][key] = value
            self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"], key)

    def test_full_hybrid_requires_every_document_product_and_provenance_to_match(self):
        for target, key, value in (("source", "document_id", "document_other"), ("source", "content_hash", "d" * 64),
                                   ("source", "ima_provenance", "unverified"), ("fact", "product_ref", "other-product"),
                                   ("fact", "verification_state", "local_source_claim_only"), ("context", "ima_provenance", "verified")):
            current = hybrid_bundle()
            row = current["trusted_context"] if target == "context" else current["evidence"]["source_refs" if target == "source" else "facts"][0]
            row[key] = value
            self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"], (target, key))
        current = hybrid_bundle()
        current["evidence"]["source_refs"].append({"source_ref_id": "other-source", "content_hash": "other", "document_id": "document_other", "ima_provenance": "selected_fact_file_original_hash_matched"})
        self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"])

    def test_full_local_context_projection_is_unchanged_and_cannot_self_upgrade(self):
        current = bundle("product_intro")
        result = self.evidence({"task_bundle": current}, value=current)
        self.assertTrue(result["ready"])
        self.assertEqual(json.loads(result["payload_json"])["trusted_context"], current["trusted_context"])
        for field, value in (("ima_provenance", "selected_fact_file_original_hash_matched"),
                             ("ima_verification", hybrid_bundle()["trusted_context"]["ima_verification"])):
            current = bundle("product_intro"); current["trusted_context"][field] = value
            self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"])

    def test_full_current_source_modes_never_claim_competition_or_implemented_ima_live(self):
        for mode in ("local_snapshot", "hybrid_verified", "ima_live"):
            current = hybrid_bundle() if mode == "hybrid_verified" else bundle("product_intro")
            current["trusted_context"].update(source_mode=mode, competition_eligible=True)
            self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"])
        current = bundle("product_intro"); current["trusted_context"]["source_mode"] = "ima_live"
        self.assertFalse(self.evidence({"task_bundle": current}, value=current)["ready"])


if __name__ == "__main__":
    unittest.main()

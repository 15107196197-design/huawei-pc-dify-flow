"""Offline contract tests only. Synthetic evidence/model identities are not live runs."""
import importlib.util
import json
import copy
import hashlib
import time
from pathlib import Path
import unittest

from services.ima_adapter.hybrid import FactReceipt

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_dify_bundle", ROOT / "scripts/build_dify_bundle.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def invoke(code, **inputs):
    namespace = {}
    exec(code, namespace)
    return namespace["main"](**inputs)


def task():
    return {"task_kind": "product_intro", "product_query": "synthetic-product", "audience": "合成测试人员", "usage_scenario": "仅用于离线合同测试", "quote_required": False, "purchase_plan_required": False, "script_required": False, "recommendation_requested": False,
            "quote_inputs": {"region": None, "as_of": None, "rule_timezone": None, "currency": None, "quantity": None, "eligibility": []}}


DESTINATIONS = [
    {"node_id": "product_intro", "provider": "unit-provider", "model": "unit-write"},
    {"node_id": "fact_compliance_review", "provider": "unit-provider", "model": "unit-review"},
]


def bundle():
    return {"trusted_context": {"source_context_ref": "scope-unit", "source_mode": "local_snapshot", "source_snapshot_ref": "snapshot-unit", "competition_eligible": False},
            "task": task(), "evidence": {"facts": [{"fact_id": "f1", "source_ref_ids": ["s1"], "raw_text": "合成产品只用于测试。"}],
            "source_refs": [{"source_ref_id": "s1", "source_title": "合成测试来源", "content_hash": "unit-hash"}], "business_rules": []},
            "policy": {"llm_payload_allowed": True, "allowed_model_destinations": DESTINATIONS}, "allowed_assets": [],
            "quote_context": {"quote_status": None, "client_quote_allowed": False, "customer_quote_summary": None}}


def draft():
    return {"status": "ready", "scenario_judgment": {}, "knowledge_basis": [{"source_ref_id": "s1", "fact_ids": ["f1"]}],
            "content": {"type": "product_intro", "title": "合成测试", "blocks": [{"block_id": "b1", "text": "合成产品只用于测试。", "claim_ids": ["c1"]}]},
            "claims": [{"claim_id": "c1", "target": "/content/blocks/0/text", "text": "合成产品只用于测试。", "fact_ids": ["f1"], "business_rule_ids": []}],
            "image_plan": [], "open_questions": [], "blockers": []}


def review():
    return {"findings": [{"finding_id": "r0", "target_ref": "/content/title", "text": "合成测试", "decision": "supported", "evidence_refs": []}, {"finding_id": "r1", "target_ref": "/content/blocks/0/text", "text": "合成产品只用于测试。", "decision": "supported", "evidence_refs": ["f1", "s1"]}],
            "coverage": {"checked_target_refs": ["/content/title", "/content/blocks/0/text"], "unmapped_claims": []}, "conflicts": [], "needs_human_review": False}


def hybrid_bundle():
    value = bundle()
    now = time.time()
    sha = hashlib.sha256(b"synthetic-original-only").hexdigest()
    receipt = FactReceipt(relative_path="P1-产品参数库/01-鸿蒙电脑/合成型号/产品事实.md", source_context_ref="scope-unit", product_ref="product-unit",
        scope_hash="a" * 64, task_hash=hashlib.sha256(json.dumps(value["task"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        snapshot_ref="snapshot-unit", sha256=sha, byte_length=23, verified_at=now - 1, expires_at=now + 120, mapping_hash="b" * 64).manifest()
    value["trusted_context"].update(source_mode="hybrid_verified", ima_provenance="selected_fact_file_original_hash_matched", ima_verification=receipt)
    for row in value["evidence"]["source_refs"]:
        row.update(document_id="document_" + receipt["source_document_ref"][:24], content_hash=sha, ima_provenance="selected_fact_file_original_hash_matched")
    for row in value["evidence"]["facts"]:
        row.update(product_ref="product-unit", verification_state="source_original_matched_fact_truth_not_asserted")
    return value


class BundleContracts(unittest.TestCase):
    def test_normalizer_rejects_bad_json_and_nonfinite(self):
        for raw in ("{", '[]', '{"a":NaN}', '{"task":{},"task":{}}', '```json\n{}\n```'):
            self.assertFalse(invoke(BUILDER.NORMALIZE, task_json=raw)["ready"])

    def test_normalizer_discards_claimed_authority(self):
        raw = {"task": task(), "trusted_context": {"tenant_id": "other", "competition_eligible": True}, "evidence": {"facts": ["fake"]}}
        result = invoke(BUILDER.NORMALIZE, task_json=json.dumps(raw))
        self.assertTrue(result["ready"])
        self.assertEqual(json.loads(result["payload_json"]), {"task": task()})

    def test_minimal_route_rejects_quote_and_poster(self):
        for change in ({"quote_required": True}, {"purchase_plan_required": True}, {"script_required": True}, {"content_channel": "store_poster"}, {"task_kind": "marketing"}, {"task_kind": "full_package"}):
            value = task() | change
            self.assertFalse(invoke(BUILDER.NORMALIZE, task_json=json.dumps({"task": value}))["ready"])

    def test_minimal_route_requires_explicit_kind_and_boolean_flags(self):
        value = task()
        del value["task_kind"]
        self.assertFalse(invoke(BUILDER.NORMALIZE, task_json=json.dumps({"task": value}))["ready"])
        for flag in ("quote_required", "purchase_plan_required", "script_required", "recommendation_requested"):
            for invalid in (None, 0, "false", []):
                value = task() | {flag: invalid}
                self.assertFalse(invoke(BUILDER.NORMALIZE, task_json=json.dumps({"task": value}))["ready"])

    def test_normalizer_preserves_unverified_quote_inputs_and_recommendation_request(self):
        inputs = {"region": "合成地区", "as_of": "2026-10-18T10:00:00+08:00", "rule_timezone": "Asia/Shanghai", "currency": "CNY", "quantity": 1,
                  "eligibility": [{"kind": "student", "claimed_status": "user_claimed", "evidence_ref": "claim-unit"}]}
        value = task() | {"quote_inputs": inputs, "recommendation_requested": True}
        result = invoke(BUILDER.NORMALIZE, task_json=json.dumps({"task": value}))
        self.assertTrue(result["ready"])
        self.assertEqual(json.loads(result["payload_json"])["task"], value)

    def test_normalizer_rejects_invalid_or_self_verified_quote_conditions(self):
        cases = [None, [], {"customer_payable_minor": 0}, {"region": "x" * 257}, {"currency": ""},
                 {"eligibility": [{}] * 21}, {"eligibility": "student"},
                 {"eligibility": [{"kind": "student", "claimed_status": "verified", "evidence_ref": None}]},
                 {"eligibility": [{"kind": "student", "claimed_status": "unknown", "verified": True}]},
                 {"eligibility": [{"kind": "x" * 129, "claimed_status": "unknown"}]},
                 {"eligibility": [{"kind": "student", "claimed_status": "unknown", "evidence_ref": "x" * 513}]}]
        cases += [{"quantity": value} for value in (True, False, 0, -1, 1.5, "2")]
        for inputs in cases:
            with self.subTest(inputs=inputs):
                value = task() | {"quote_inputs": inputs}
                self.assertFalse(invoke(BUILDER.NORMALIZE, task_json=json.dumps({"task": value}))["ready"])

    def test_scope_requires_proof_and_business_ready(self):
        inputs = {"status_code": 200, "request_json": json.dumps({"task": task()})}
        for body in ({"status": "denied", "data": {}}, {"status": "ready", "data": {"source_context_ref": "s"}}):
            self.assertFalse(invoke(BUILDER.SCOPE, body=json.dumps(body), **inputs)["ready"])

    def evidence_result(self, value):
        code = BUILDER.EVIDENCE.replace("__EXPECTED_MODEL_DESTINATIONS__", repr(DESTINATIONS))
        return invoke(code, status_code=200, body=json.dumps({"status": "ready", "data": {"task_bundle": value}}), request_json=json.dumps({"task": task()}), scope_ref="scope-unit")

    def test_evidence_removes_proof_and_requires_independent_destinations(self):
        value = bundle()
        value["trusted_context"]["source_context_proof"] = "synthetic-private-proof"
        result = self.evidence_result(value)
        self.assertTrue(result["ready"])
        self.assertNotIn("synthetic-private-proof", result["payload_json"])
        value["policy"]["allowed_model_destinations"] = DESTINATIONS[:1]
        self.assertFalse(self.evidence_result(value)["ready"])

    def test_cross_scope_and_fake_local_competition_blocked(self):
        for name, val in (("source_context_ref", "another-scope"), ("competition_eligible", True)):
            value = bundle()
            value["trusted_context"][name] = val
            self.assertFalse(self.evidence_result(value)["ready"])

    def test_fact_must_link_real_source(self):
        value = bundle()
        value["evidence"]["facts"][0]["source_ref_ids"] = ["not-in-source-response"]
        self.assertFalse(self.evidence_result(value)["ready"])

    def test_service_normalization_may_add_only_unrequested_task_fields(self):
        value = bundle()
        value["task"]["problem"] = None
        value["task"]["hard_requirements"] = []
        self.assertTrue(self.evidence_result(value)["ready"])
        value["task"]["product_query"] = "different-product"
        self.assertFalse(self.evidence_result(value)["ready"])

    def test_evidence_rejects_purchase_plan_downgrade_and_changed_conditions(self):
        for change in ({"purchase_plan_required": True}, {"quote_inputs": task()["quote_inputs"] | {"region": "other"}}, {"recommendation_requested": True}):
            value = bundle()
            value["task"].update(change)
            self.assertFalse(self.evidence_result(value)["ready"])
        value = bundle()
        del value["task"]["purchase_plan_required"]
        self.assertFalse(self.evidence_result(value)["ready"])

    def test_writer_ref_and_json_must_be_real(self):
        value = draft()
        value["claims"][0]["fact_ids"] = ["invented"]
        for raw in (json.dumps(value), "```json\n" + json.dumps(draft()) + "\n```"):
            self.assertFalse(invoke(BUILDER.WRITER_PARSE, text=raw, bundle_json=json.dumps(bundle()))["ready"])

    def test_minimal_writer_rejects_injected_quote_binding(self):
        value = draft()
        value["claims"][0]["quote_binding"] = {"quote_ref": "q", "quote_version": "1"}
        self.assertFalse(invoke(BUILDER.WRITER_PARSE, text=json.dumps(value), bundle_json=json.dumps(bundle()))["ready"])

    def test_quote_binding_for_all_price_output_kinds(self):
        value = bundle()
        value["quote_context"] = {"quote_status": "VALID_OPTIMAL", "client_quote_allowed": True, "validation_ref": "validation-unit",
                                  "customer_quote_summary": {"quote_ref": "q-unit", "quote_version": "1", "product_ref": "sku-unit", "formatted_customer_payable": "仅合成测试金额", "valid_until": "合成测试时点"}}
        for kind, field in (("article", "claims"), ("poster", "claims"), ("quote_explanation", "claim_refs"), ("sales_script", "claims")):
            with self.subTest(kind=kind):
                content = {"kind": kind, field: [{"target": "/synthetic_text", "text": "仅合成报价绑定测试", "quote_binding": {"quote_ref": "q-unit", "quote_version": "1"}, "fact_ids": [], "business_rule_ids": []}]}
                result = invoke(BUILDER.QUOTE_BINDING_GUARD, bundle_json=json.dumps(value), draft_json=json.dumps(content))
                self.assertTrue(result["binding_passed"])
                content[field][0]["quote_binding"]["quote_version"] = "old"
                self.assertFalse(invoke(BUILDER.QUOTE_BINDING_GUARD, bundle_json=json.dumps(value), draft_json=json.dumps(content))["binding_passed"])

    def test_quote_binding_never_upgrades_pending_or_unauthorized_quote(self):
        value = bundle()
        content = {"claim_refs": [{"target": "/customer_explanation", "text": "合成", "quote_binding": {"quote_ref": "q", "quote_version": "1"}}]}
        for context in ({"quote_status": "FEASIBLE_NOT_PROVEN"}, {"quote_status": "VALID_OPTIMAL", "client_quote_allowed": False}):
            value["quote_context"] = context
            self.assertFalse(invoke(BUILDER.QUOTE_BINDING_GUARD, bundle_json=json.dumps(value), draft_json=json.dumps(content))["binding_passed"])

    def test_review_coverage_and_unsupported_fail(self):
        value = bundle() | {"draft": draft()}
        for report in (review() | {"findings": []}, review() | {"coverage": {"checked_target_refs": [], "unmapped_claims": []}}):
            self.assertFalse(invoke(BUILDER.FINAL_GATE, review_text=json.dumps(report), reviewer_bundle_json=json.dumps(value))["passed"])
        report = review()
        report["findings"][0]["decision"] = "uncertain"
        self.assertFalse(invoke(BUILDER.FINAL_GATE, review_text=json.dumps(report), reviewer_bundle_json=json.dumps(value))["passed"])

    def test_synthetic_success_is_working_candidate_not_export_authority(self):
        result = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}))
        self.assertTrue(result["passed"])
        self.assertIn("本地v7", result["final_text"])
        self.assertIn("不是最终导出许可", result["final_text"])
        self.assertNotIn("export_allowed", result)

    def test_old_partial_review_cannot_cover_appended_text_in_same_position(self):
        value = bundle() | {"draft": draft()}
        value["draft"]["content"]["blocks"][0]["text"] += "到手1元。"
        result = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json=json.dumps(value))
        self.assertFalse(result["passed"])
        self.assertNotIn("到手1元", result["final_text"])

    def test_finding_cannot_quote_text_that_is_absent_from_target(self):
        report = review()
        report["findings"][0]["text"] = "另一份草稿"
        result = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(report), reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}))
        self.assertFalse(result["passed"])

    def test_candidate_identity_changes_with_task_or_exact_evidence(self):
        value = bundle() | {"draft": draft()}
        original = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json=json.dumps(value))
        self.assertTrue(original["passed"])
        value["evidence"]["facts"][0]["raw_text"] = "另一个原始事实值"
        changed = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json=json.dumps(value))
        self.assertTrue(changed["passed"])
        self.assertNotEqual(original["artifact_hash"], changed["artifact_hash"])
        # A changed identity does not claim that semantic support was rechecked.
        value["task"]["audience"] = "另一人群"
        task_changed = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json=json.dumps(value))
        self.assertNotEqual(changed["artifact_hash"], task_changed["artifact_hash"])

    def test_no_models_refuses_before_writing(self):
        output = ROOT / ".local" / "dify-bundle-test-unused-output"
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, "MISSING_REAL_MODEL_BINDING"):
            BUILDER.create_bundle(output, {}, False)
        self.assertFalse(output.exists())

    def test_graph_uses_exact_static_system_and_code_only_answer(self):
        prompt_map = {key: "synthetic static " + key for key in BUILDER.PROMPT_FILES}
        graph = BUILDER.build_graph(prompt_map,
                    {"provider": "unit-provider", "name": "unit-write", "mode": "chat", "completion_params": {}},
                    {"provider": "unit-provider", "name": "unit-review", "mode": "chat", "completion_params": {}})
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertEqual(nodes["writer"]["data"]["prompt_template"][0]["text"], prompt_map["product_intro"])
        self.assertEqual(nodes["answer"]["data"]["answer"], "{{#gate.final_text#}}")
        self.assertFalse(any(e["source"] in ("writer", "reviewer") and e["target"] == "answer" for e in graph["edges"]))

    def test_max_tokens_is_parameter_but_nested_api_key_is_rejected(self):
        config = {"models": {"MODEL_WRITE": {"provider": "unit-provider", "name": "unit-write", "completion_params": {"max_tokens": 1024}}}}
        BUILDER.reject_credentials(config)
        self.assertEqual(BUILDER.model_binding(config, "MODEL_WRITE")["completion_params"]["max_tokens"], 1024)
        config["models"]["MODEL_WRITE"]["completion_params"]["extra"] = {"api_key": "synthetic-secret"}
        with self.assertRaisesRegex(ValueError, "CONFIG_MUST_NOT_CONTAIN_CREDENTIALS"):
            BUILDER.reject_credentials(config)

    def revision(self, original=None, reviewed=None, report=None, gate_passed=False):
        original = bundle() if original is None else original
        reviewed = original | {"draft": draft()} if reviewed is None else reviewed
        report = review() if report is None else report
        return invoke(BUILDER.REVISION_FEEDBACK, bundle_json=json.dumps(original),
                      reviewer_bundle_json=json.dumps(reviewed), review_text=report if isinstance(report, str) else json.dumps(report), gate_passed=gate_passed)

    def test_revision_preserves_exact_original_and_genuine_review(self):
        original = bundle()
        original["evidence"]["facts"][0]["raw_text"] += "配置可能因销售版本而异，以实际销售版本为准。"
        report = review()
        report["findings"][1].update(decision="unsupported", reason="原证据中的适用条件遗漏。", suggested_action="补齐原 evidence 已有条件。")
        result = self.revision(original=original, report=report)
        self.assertTrue(result["ready"])
        payload = json.loads(result["payload_json"])
        for key in original:
            self.assertEqual(payload[key], original[key])
        self.assertEqual(payload["draft"], draft())
        feedback = payload["validator_feedback"]
        self.assertEqual(feedback["review"], report)
        self.assertEqual(feedback["attempt"], 2)
        self.assertEqual(feedback["remaining_revisions"], 0)
        self.assertIn("不能新增或改变事实", feedback["revision_instruction"])
        self.assertNotIn("source_context_proof", payload)

    def test_revision_rejects_changed_evidence_task_permission_or_context(self):
        for key in ("evidence", "task", "policy", "trusted_context", "quote_context", "allowed_assets"):
            original = bundle()
            reviewed = copy.deepcopy(original) | {"draft": draft()}
            reviewed[key] = {"changed": True} if key != "allowed_assets" else ["fake-asset"]
            result = self.revision(original=original, reviewed=reviewed)
            self.assertFalse(result["ready"], key)
            self.assertEqual(result["payload_json"], "{}")

    def test_revision_does_not_promote_review_evidence_or_permissions(self):
        for key in ("evidence", "policy", "trusted_context", "quote_context", "export_allowed"):
            report = review() | {key: {"invented": True}}
            self.assertFalse(self.revision(report=report)["ready"])
            report = review()
            report["findings"][1][key] = {"invented": True}
            self.assertFalse(self.revision(report=report)["ready"])
        report = review()
        report["findings"][1]["evidence_refs"] = ["invented_fact"]
        self.assertFalse(self.revision(report=report)["ready"])
        report = review()
        report["findings"][1]["quote_binding"] = {"quote_ref": "new", "quote_version": "1"}
        self.assertFalse(self.revision(report=report)["ready"])

    def test_revision_rejects_wrong_attempt_already_passed_or_embedded_feedback(self):
        for passed in (True, None, 0, "false"):
            self.assertFalse(self.revision(gate_passed=passed)["ready"])
        first = self.revision()
        self.assertTrue(first["ready"])
        previous = json.loads(first["payload_json"])
        self.assertFalse(self.revision(original=previous, reviewed=previous)["ready"])
        reviewed = bundle() | {"draft": draft(), "validator_feedback": {"attempt": 2}}
        self.assertFalse(self.revision(reviewed=reviewed)["ready"])

    def test_revision_does_not_fix_conflicting_source_or_human_review_by_writing(self):
        for report in (review() | {"conflicts": [{"reason": "两条源事实冲突"}]}, review() | {"needs_human_review": True}):
            self.assertFalse(self.revision(report=report)["ready"])

    def test_revision_rejects_malformed_or_wrong_draft_review(self):
        for raw in ("{", "[]", '{"a":NaN}', '{"findings":[],"findings":[]}'):
            self.assertFalse(self.revision(report=raw)["ready"])
        for changed in ("pointer", "text", "refs", "coverage", "unmapped"):
            report = review()
            if changed == "pointer": report["findings"][1]["target_ref"] = "/other"
            if changed == "text": report["findings"][1]["text"] = "另一版草稿"
            if changed == "refs": report["findings"][1]["evidence_refs"] = [{"fact_id": "f1"}]
            if changed == "coverage": report["coverage"]["checked_target_refs"] = ["/other"]
            if changed == "unmapped": report["coverage"]["unmapped_claims"] = [{"policy": "allow"}]
            self.assertFalse(self.revision(report=report)["ready"], changed)

    def test_revised_draft_reparses_original_evidence_and_requires_fresh_full_review(self):
        original = bundle()
        report = review()
        report["findings"][1]["decision"] = "unsupported"
        first = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(report), reviewer_bundle_json=json.dumps(original | {"draft": draft()}))
        self.assertFalse(first["passed"])
        feedback = self.revision(original=original, report=report)
        self.assertTrue(feedback["ready"])
        revised = draft()
        revised["content"]["blocks"][0]["text"] += "测试资料不构成真实产品说明。"
        revised["claims"][0]["text"] = revised["content"]["blocks"][0]["text"]
        parsed = invoke(BUILDER.WRITER_PARSE, text=json.dumps(revised), bundle_json=json.dumps(original))
        self.assertTrue(parsed["ready"])
        self.assertNotIn("validator_feedback", json.loads(parsed["payload_json"]))
        stale = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json=parsed["payload_json"])
        self.assertFalse(stale["passed"])
        fresh_review = review()
        fresh_review["findings"][1]["text"] = revised["content"]["blocks"][0]["text"]
        second = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(fresh_review), reviewer_bundle_json=parsed["payload_json"])
        self.assertTrue(second["passed"])
        revised["claims"][0]["fact_ids"] = ["fact_invented_in_feedback"]
        self.assertFalse(invoke(BUILDER.WRITER_PARSE, text=json.dumps(revised), bundle_json=json.dumps(original))["ready"])

    def test_revision_graph_has_exact_static_system_same_model_and_original_second_parse(self):
        prompts = {key: "synthetic static " + key for key in BUILDER.PROMPT_FILES}
        writer = {"provider": "unit-provider", "name": "unit-write", "mode": "chat", "completion_params": {}}
        reviewer = writer | {"name": "unit-review"}
        graph = BUILDER.build_graph(prompts, writer, reviewer)
        nodes = {n["id"]: n["data"] for n in graph["nodes"]}
        for first, second in (("writer", "writer2"), ("reviewer", "reviewer2")):
            self.assertEqual(nodes[first]["model"], nodes[second]["model"])
            self.assertEqual(nodes[first]["prompt_template"][0]["text"], nodes[second]["prompt_template"][0]["text"])
        self.assertEqual(nodes["writer_parse2"]["code"], BUILDER.WRITER_PARSE)
        self.assertEqual(next(v["value_selector"] for v in nodes["writer_parse2"]["variables"] if v["variable"] == "bundle_json"), ["evidence_parse", "payload_json"])
        self.assertEqual(nodes["gate2"]["code"], BUILDER.FINAL_GATE)
        self.assertEqual(nodes["answer2"]["answer"], "{{#gate2.final_text#}}")
        triples = {(r["source"], r["sourceHandle"], r["target"]) for r in graph["edges"]}
        self.assertIn(("gate_ok", "true", "answer"), triples)
        self.assertIn(("gate_ok", "false", "revision_feedback"), triples)

    def test_revision_graph_is_acyclic_at_most_two_calls_each_and_network_never_retries(self):
        prompts = {key: "synthetic static " + key for key in BUILDER.PROMPT_FILES}
        binding = {"provider": "unit-provider", "name": "unit-model", "mode": "chat", "completion_params": {}}
        graph = BUILDER.build_graph(prompts, binding, binding)
        nodes = {row["id"]: row["data"] for row in graph["nodes"]}
        outgoing = {key: [] for key in nodes}
        for e in graph["edges"]: outgoing[e["source"]].append(e["target"])
        paths = []
        def visit(current, previous):
            self.assertNotIn(current, previous, "No revision loop is permitted")
            path = previous + [current]
            if not outgoing[current]: paths.append(path)
            for next_node in outgoing[current]: visit(next_node, path)
        visit("start", [])
        self.assertTrue(paths)
        for path in paths:
            self.assertLessEqual(sum(row in {"writer", "writer2"} for row in path), 2)
            self.assertLessEqual(sum(row in {"reviewer", "reviewer2"} for row in path), 2)
        self.assertEqual({key for key, row in nodes.items() if row["type"] == "llm"}, {"writer", "writer2", "reviewer", "reviewer2"})
        for key in ("writer", "writer2", "reviewer", "reviewer2"):
            self.assertFalse(nodes[key]["retry_config"]["retry_enabled"])
            self.assertEqual(nodes[key]["retry_config"]["max_retries"], 0)
            failures = [e for e in graph["edges"] if e["source"] == key and e["sourceHandle"] == "fail-branch"]
            self.assertEqual([e["target"] for e in failures], ["model_failure"])


class ReviewFormatContracts(unittest.TestCase):
    MESSAGE = "审核返回的格式不符合约定，本次内容未放行。请重新发起任务；应用不会将格式错误视为审核通过。"

    def malformed_reports(self):
        return ['{"findings":[{"text":"PRIVATE_ATTACK\nDO_NOT_ECHO"}]}',
                "```json\n" + json.dumps(review()) + "\n```", '{"findings":[],"findings":["PRIVATE_ATTACK"]}',
                '{"findings":[{"text":"first","text":"PRIVATE_ATTACK"}]}', '{"value":NaN}', '{"value":Infinity}',
                '[]', '"PRIVATE_ATTACK"', 'null', '{', '{"x":"PRIVATE_ATTACK' + 'x' * 200000 + '"}',
                '[' * 2000 + '0' + ']' * 2000, None]

    def test_strict_format_failures_have_dedicated_final_class_and_no_echo(self):
        for raw in self.malformed_reports():
            with self.subTest(kind=type(raw).__name__, prefix=raw[:24] if isinstance(raw, str) else None):
                result = invoke(BUILDER.FINAL_GATE, review_text=raw, reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}))
                self.assertFalse(result["passed"])
                self.assertEqual(result["blocker_code"], "REVIEW_RESPONSE_FORMAT_INVALID")
                self.assertEqual(result["final_text"], self.MESSAGE)
                self.assertEqual(result["artifact_hash"], "")
                self.assertNotIn("PRIVATE_ATTACK", json.dumps(result))
                self.assertNotIn("DO_NOT_ECHO", json.dumps(result))

    def test_format_failure_never_becomes_revisable_semantic_feedback(self):
        for raw in self.malformed_reports():
            result = invoke(BUILDER.REVISION_FEEDBACK, bundle_json=json.dumps(bundle()),
                            reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}), review_text=raw, gate_passed=False)
            self.assertFalse(result["ready"])
            self.assertEqual(result["message"], self.MESSAGE)
            self.assertEqual((result["payload_json"], result["scope_ref"], result["proof"]), ("{}", "", ""))
            self.assertNotIn("validator_feedback", result["payload_json"])
            self.assertNotIn("PRIVATE_ATTACK", json.dumps(result))

    def test_valid_json_schema_semantic_and_binding_failures_keep_original_class(self):
        for report in ({}, review() | {"findings": []}):
            result = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(report), reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}))
            self.assertFalse(result["passed"])
            self.assertEqual(result["blocker_code"], "OUTPUT_REVIEW_OR_BINDING_INVALID")
            self.assertNotEqual(result["final_text"], self.MESSAGE)
        semantic = review(); semantic["findings"][1]["decision"] = "unsupported"
        feedback = invoke(BUILDER.REVISION_FEEDBACK, bundle_json=json.dumps(bundle()), reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}),
                          review_text=json.dumps(semantic), gate_passed=False)
        self.assertTrue(feedback["ready"])
        bad_schema = invoke(BUILDER.REVISION_FEEDBACK, bundle_json=json.dumps(bundle()), reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}),
                            review_text="{}", gate_passed=False)
        self.assertFalse(bad_schema["ready"])
        self.assertEqual(bad_schema["message"], "BLOCKED: REVISION_FEEDBACK_OR_BINDING_INVALID")
        bad_bundle = invoke(BUILDER.FINAL_GATE, review_text=json.dumps(review()), reviewer_bundle_json="{")
        self.assertEqual(bad_bundle["blocker_code"], "OUTPUT_REVIEW_OR_BINDING_INVALID")

    def test_valid_escaped_newline_in_review_data_is_not_sanitized_or_rejected(self):
        report = review()
        report["findings"][0]["reason"] = "合成理由第一行\n第二行"
        raw = json.dumps(report)
        result = invoke(BUILDER.FINAL_GATE, review_text=raw, reviewer_bundle_json=json.dumps(bundle() | {"draft": draft()}))
        self.assertTrue(result["passed"])
        self.assertEqual(json.loads(raw)["findings"][0]["reason"], report["findings"][0]["reason"])


class ScopeMessageContracts(unittest.TestCase):
    def scope(self, state, reason, *, status_code=200, body=None):
        if body is None:
            body = json.dumps({"status": state, "data": {"reason": reason, "source_context_proof": "PRIVATE_PROOF",
                "questions": ["PRIVATE_QUESTION"], "headers": {"Authorization": "PRIVATE_HEADER"},
                "url": "https://invalid.example/PRIVATE_URL"}, "error": "PRIVATE_ERROR"})
        return invoke(BUILDER.SCOPE, status_code=status_code, body=body, request_json=json.dumps({"task": task()}))

    def test_known_scope_states_have_fixed_safe_customer_guidance(self):
        cases = [("needs_source", "IMA_FACT_VERIFICATION_FAILED", "本次尚未完成 ima 原文核验，未生成内容。请检查知识库访问、网络与所用资料版本后重试；应用不会自动切换到未核验来源。"),
                 ("needs_source", "IMA_DAILY_SOURCE_LIMIT_REACHED", "ima今日资料读取次数已达上限，接口提示明天再尝试。本次未完成参赛来源核验；请稍后重试，或明确使用本地开发模式进行调试。本地候选不能作为参赛核验通过记录。"),
                 ("needs_source", "SOURCE_MODE_NOT_IMPLEMENTED", "当前来源模式尚未启用，未生成内容。请启用并核验所需知识来源后重试；应用不会自动切换到其他来源。"),
                 ("needs_input", "PRODUCT_AMBIGUOUS_OR_MISSING", "请确认完整产品型号、年份或系统版本及相关配置后重试。型号尚未明确，暂未生成内容。")]
        for state, reason, message in cases:
            result = self.scope(state, reason)
            self.assertFalse(result["ready"])
            self.assertEqual(result["message"], message)
            self.assertEqual((result["payload_json"], result["scope_ref"], result["proof"]), ("{}", "", ""))
            self.assertNotIn("PRIVATE_", json.dumps(result))
            other = self.scope(state, reason, body=json.dumps({"status": state, "data": {"reason": reason}}))
            self.assertEqual(result, other)

    def test_unknown_reasons_wrong_states_and_non_2xx_keep_original_block(self):
        for state, reason, status in [("needs_source", "unknown", 200), ("denied", "IMA_FACT_VERIFICATION_FAILED", 200),
                ("needs_input", "SOURCE_MODE_NOT_IMPLEMENTED", 200), ("error", "PRODUCT_AMBIGUOUS_OR_MISSING", 200),
                ("needs_source", "IMA_FACT_VERIFICATION_FAILED", 403), ("needs_source", "IMA_FACT_VERIFICATION_FAILED", 500),
                ("error", "IMA_DAILY_SOURCE_LIMIT_REACHED", 200), ("needs_source", "IMA_DAILY_SOURCE_LIMIT_REACHED", 429)]:
            self.assertEqual(self.scope(state, reason, status_code=status)["message"], "BLOCKED: SCOPE_RESPONSE_INVALID")

    def test_malformed_scope_json_does_not_get_known_business_message(self):
        for raw in ("{", "[]", '```json\n{}\n```', '{"status":"needs_source","status":"needs_source","data":{"reason":"IMA_FACT_VERIFICATION_FAILED"}}',
                    '{"status":"needs_source","data":{"reason":"IMA_FACT_VERIFICATION_FAILED","x":NaN}}',
                    '{"status":"needs_source","data":null,"reason":"IMA_FACT_VERIFICATION_FAILED"}'):
            result = self.scope(None, None, body=raw)
            self.assertFalse(result["ready"])
            self.assertEqual(result["message"], "BLOCKED: SCOPE_RESPONSE_INVALID")

    def test_ready_scope_with_reason_is_still_bound_to_success_proof(self):
        body = json.dumps({"status": "ready", "data": {"reason": "IMA_FACT_VERIFICATION_FAILED",
            "source_context_ref": "scope-unit", "source_context_proof": "synthetic-proof", "purpose_ref": "purpose-unit", "destination_ref": "destination-unit"}})
        result = self.scope(None, None, body=body)
        self.assertTrue(result["ready"])
        self.assertEqual(result["proof"], "synthetic-proof")
        self.assertEqual(result["message"], "")


class SourceProjectionContracts(unittest.TestCase):
    evidence_result = BundleContracts.evidence_result

    def test_safe_hybrid_projection_preserves_exact_selected_original_manifest(self):
        value = hybrid_bundle()
        value["trusted_context"].update(source_context_proof="must-not-reach-model", ignored_internal_field="drop-me")
        result = self.evidence_result(value)
        self.assertTrue(result["ready"])
        context = json.loads(result["payload_json"])["trusted_context"]
        self.assertEqual(set(context), {"source_context_ref", "source_mode", "source_snapshot_ref", "competition_eligible", "ima_provenance", "ima_verification"})
        self.assertEqual(context["ima_verification"], value["trusted_context"]["ima_verification"])
        self.assertFalse(context["competition_eligible"])
        self.assertNotIn("must-not-reach-model", result["payload_json"])
        self.assertNotIn("drop-me", result["payload_json"])
        self.assertEqual(context["ima_verification"]["scope"], "selected_fact_file_only")

    def test_hybrid_missing_manifest_or_any_required_field_blocks(self):
        value = hybrid_bundle()
        manifest = value["trusted_context"].pop("ima_verification")
        self.assertFalse(self.evidence_result(value)["ready"])
        for key in manifest:
            current = hybrid_bundle()
            del current["trusted_context"]["ima_verification"][key]
            self.assertFalse(self.evidence_result(current)["ready"], key)

    def test_hybrid_unknown_manifest_keys_and_unsafe_known_values_never_leak(self):
        for key in ("api_key", "signed_url", "url", "headers", "source_context_proof", "raw_data", "notebook_ext_info", "unexpected"):
            current = hybrid_bundle()
            current["trusted_context"]["ima_verification"][key] = "PRIVATE_VALUE https://unapproved.invalid/secret"
            result = self.evidence_result(current)
            self.assertFalse(result["ready"], key)
            self.assertNotIn("PRIVATE_VALUE", result["payload_json"] + result["message"])
        for key in ("source_context_ref", "snapshot_ref", "product_ref", "mapping_hash", "scope_hash"):
            current = hybrid_bundle()
            current["trusted_context"]["ima_verification"][key] = "https://unapproved.invalid/PRIVATE_VALUE"
            self.assertFalse(self.evidence_result(current)["ready"], key)

    def test_hybrid_manifest_cannot_upgrade_scope_count_truth_rights_or_competition(self):
        changes = {"scope": "whole_library", "schema_version": "2.0", "matched_file_count": 2,
                   "all_library_verified": True, "fact_truth_verified": True, "image_rights_verified": True,
                   "p4_rules_verified": True, "competition_verified": True}
        for key, value in changes.items():
            current = hybrid_bundle()
            current["trusted_context"]["ima_verification"][key] = value
            self.assertFalse(self.evidence_result(current)["ready"], key)
        for value in (True, 1.0, "1"):
            current = hybrid_bundle(); current["trusted_context"]["ima_verification"]["matched_file_count"] = value
            self.assertFalse(self.evidence_result(current)["ready"])

    def test_hybrid_context_task_document_hash_product_and_provenance_are_bound(self):
        for key, value in (("source_context_ref", "other-context"), ("snapshot_ref", "other-snapshot"), ("task_hash", "c" * 64),
                           ("sha256", "d" * 64), ("source_document_ref", "e" * 64), ("product_ref", "other-product")):
            current = hybrid_bundle(); current["trusted_context"]["ima_verification"][key] = value
            self.assertFalse(self.evidence_result(current)["ready"], key)
        for target, key, value in (("context", "ima_provenance", "verified"), ("source", "ima_provenance", "unverified"),
                                   ("source", "document_id", "document_other"), ("source", "content_hash", "f" * 64),
                                   ("fact", "product_ref", "other"), ("fact", "verification_state", "local_source_claim_only")):
            current = hybrid_bundle()
            row = current["trusted_context"] if target == "context" else current["evidence"]["source_refs" if target == "source" else "facts"][0]
            row[key] = value
            self.assertFalse(self.evidence_result(current)["ready"], (target, key))
        current = hybrid_bundle()
        current["task"]["extra_server_normalized_field"] = "task changed after receipt"
        self.assertFalse(self.evidence_result(current)["ready"])

    def test_hybrid_hash_time_length_formats_and_current_window_are_checked(self):
        now = time.time()
        changes = [("mapping_hash", "A" * 64), ("scope_hash", "a" * 63), ("byte_length", 0), ("byte_length", True),
                   ("byte_length", 4 * 1024 * 1024 + 1), ("verified_at", True), ("verified_at", -1),
                   ("verified_at", now + 60), ("expires_at", now - 1), ("expires_at", now + 901)]
        for key, value in changes:
            current = hybrid_bundle(); current["trusted_context"]["ima_verification"][key] = value
            self.assertFalse(self.evidence_result(current)["ready"], (key, value))

    def test_local_projection_unchanged_and_cannot_self_claim_ima_original_match(self):
        original = bundle()
        projected = json.loads(self.evidence_result(original)["payload_json"])["trusted_context"]
        self.assertEqual(projected, original["trusted_context"])
        current = bundle(); current["trusted_context"].update(ima_provenance="unverified", ima_verification=None)
        self.assertEqual(json.loads(self.evidence_result(current)["payload_json"])["trusted_context"], projected)
        for change in ("context_provenance", "receipt", "source_provenance", "fact_state"):
            current = bundle()
            if change == "context_provenance": current["trusted_context"]["ima_provenance"] = "selected_fact_file_original_hash_matched"
            if change == "receipt": current["trusted_context"]["ima_verification"] = hybrid_bundle()["trusted_context"]["ima_verification"]
            if change == "source_provenance": current["evidence"]["source_refs"][0]["ima_provenance"] = "selected_fact_file_original_hash_matched"
            if change == "fact_state": current["evidence"]["facts"][0]["verification_state"] = "source_original_matched_fact_truth_not_asserted"
            self.assertFalse(self.evidence_result(current)["ready"], change)

    def test_current_all_source_modes_cannot_claim_competition_and_ima_live_is_unimplemented(self):
        for mode in ("local_snapshot", "hybrid_verified", "ima_live"):
            current = hybrid_bundle() if mode == "hybrid_verified" else bundle()
            current["trusted_context"].update(source_mode=mode, competition_eligible=True)
            self.assertFalse(self.evidence_result(current)["ready"])
        current = bundle(); current["trusted_context"]["source_mode"] = "ima_live"
        self.assertFalse(self.evidence_result(current)["ready"])


if __name__ == "__main__":
    unittest.main()

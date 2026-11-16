#!/usr/bin/env python3
"""Prepare the larger Dify Chatflow candidate without deploying or calling models.

This is deliberately separate from the tested minimal product-introduction flow.
The node DTOs were checked against the exact Graphon 0.7.0 wheel locked by Dify
1.17.1. The image-to-Dify-File adapter and multi-SKU scheduler are not implemented:
their paths fail closed.
Neither plan-only output nor a locally validated graph is a runnable application.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("minimal_dify_builder", ROOT / "scripts/build_dify_bundle.py")
BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(BASE)

MODEL_SLOTS = {
    "scene_parse": "MODEL_PARSE", "product_intro": "MODEL_WRITE",
    "platform_strategy": "MODEL_STRATEGY", "article_write": "MODEL_WRITE",
    "poster_copy": "MODEL_WRITE", "fact_compliance_review": "MODEL_REVIEW",
    "quote_explain": "MODEL_QUOTE", "visual_layout": "MODEL_LAYOUT",
    "sales_demo": "MODEL_SCRIPT",
}
ALLOWED_NODE_TYPES = {"start", "code", "if-else", "http-request", "llm", "answer", "variable-aggregator"}

# A retrieval plan is an editorial intention, never a claim that a product has
# a capability. Keep it deterministic and reconstruct it from the bound task.
PRELIMINARY_RULES = r'''
def preliminary_strategy(task):
    channel = task.get("content_channel")
    platforms = {
        "wechat_article": {"image_count_range": [2, 4], "structure": ["标题", "导语", "分段正文", "行动引导"], "tone": "解释清楚、证据与限制并列"},
        "xiaohongshu": {"image_count_range": [3, 6], "structure": ["口语标题", "场景短段落", "核对清单", "话题标签", "一次互动"], "tone": "自然具体、不虚构个人体验"},
        "moments": {"image_count_range": [1, 3], "structure": ["人群任务首句", "一个核心卖点", "必要条件", "一次行动引导"], "tone": "克制、简短、低打扰"},
        "store_poster": {"image_count_range": [1, 1], "structure": ["主标题", "副标题", "至多三个卖点", "有据活动或条件", "一次行动引导"], "tone": "短句、清楚层级"},
    }
    if channel is not None and channel not in platforms:
        raise ValueError("PRELIMINARY_CHANNEL_INVALID")
    return {"stage": "pre_retrieval_intent_only", "product_capabilities_asserted": False,
            "facts_verified": False, "platform": channel,
            "task_dimensions": {k: task.get(k) for k in ("audience", "usage_scenario", "purchase_stage", "problem", "content_goal")},
            "editorial_intent": platforms.get(channel),
            "retrieval_targets": ["准确型号和相关配置", "当前任务相关事实及限制", "匹配型号的ima图片及来源"] if channel else ["准确型号和相关配置", "当前任务相关事实及限制"],
            "dynamic_price_rules_required": task.get("quote_required") is True,
            "next_step": "取证后才能选择具体卖点、图片及冻结平台策略"}
'''

# No user-provided tenant, provenance, rule set, permission or quote state can
# enter through scene_parse. The code produces the authoritative task flags.
NORMALIZE = BASE.COMMON + r'''
def main(text: str) -> dict:
    try:
        parsed = strict_json(text)
        if parsed.get("status") != "ready":
            # Questions are compiled from a fixed field dictionary. Raw model
            # prose is not used as a source of prices, facts or permissions.
            questions = {"task_kind": "请说明要产品介绍、平台营销、报价还是三分钟店员讲解。",
                         "product_query": "请补具体型号或要完成的主要任务；不必先知道型号。",
                         "audience": "内容或推荐主要面向哪类顾客？",
                         "usage_scenario": "顾客主要在什么场景完成什么任务？",
                         "hard_requirements": "请补充必须使用的软件、系统或外设等硬性条件。",
                         "required_fact_fields": "本次必须核对哪些产品事实字段？",
                         "problem": "这次主要要解决哪个使用或购机问题？",
                         "content_goal": "这份内容希望读者了解什么或采取什么行动？",
                         "content_channel": "准备发公众号、小红书、朋友圈还是门店海报？",
                         "sales_platform": "报价准备在哪个销售平台或门店使用？",
                         "quote_inputs.region": "报价适用哪个地区？",
                         "quote_inputs.quantity": "需要按几台或几件商品报价？"}
            missing = parsed.get("missing_fields", [])
            selected = [questions[key] for key in questions if isinstance(missing, list) and key in missing][:3]
            value = fail("SCENE_NEEDS_INPUT")
            if selected:
                value["message"] = "请补充以下内容：\n" + "\n".join(selected)
            return value
        raw = parsed.get("task")
        if not isinstance(raw, dict):
            return fail("TASK_OBJECT_REQUIRED")
        kind = raw.get("task_kind")
        if kind not in {"product_intro", "marketing", "quote", "sales_script", "full_package"}:
            return fail("TASK_KIND_REQUIRED")
        allowed = {"task_kind", "delivery_scope", "product_query", "audience", "usage_scenario", "purchase_stage",
                   "purchase_stage_basis", "problem", "hard_requirements", "required_fact_fields",
                   "content_goal", "content_channel", "sales_platform", "quote_required", "script_required",
                   "purchase_plan_required", "recommendation_requested", "quote_inputs"}
        task = {k: v for k, v in raw.items() if k in allowed}
        delivery_scope = task.get("delivery_scope", "complete_package")
        if delivery_scope not in {"content_only", "complete_package"} or (delivery_scope == "content_only" and kind != "marketing"):
            return fail("INVALID_DELIVERY_SCOPE")
        content_only = kind == "marketing" and delivery_scope == "content_only"
        task["delivery_scope"] = delivery_scope
        for flag in ("quote_required", "script_required", "purchase_plan_required", "recommendation_requested"):
            if flag in task and type(task[flag]) is not bool:
                return fail("TASK_FLAGS_MUST_BE_BOOLEANS")
        if kind == "product_intro":
            if any(task.get(k, False) for k in ("quote_required", "script_required", "purchase_plan_required")):
                return fail("EXPLICIT_PRODUCT_INTRO_CONFLICTS_WITH_PRICE_REQUEST")
            task.update(quote_required=False, purchase_plan_required=False, script_required=False)
        elif content_only:
            if any(task.get(k, False) for k in ("quote_required", "purchase_plan_required", "script_required")):
                return fail("CONTENT_ONLY_CONFLICTS_WITH_PRICE_REQUEST")
            task.update(quote_required=False, purchase_plan_required=False, script_required=False)
        else:
            task.update(quote_required=True, purchase_plan_required=True)
            task["script_required"] = kind in {"sales_script", "full_package"} or task.get("script_required", False)
        task["recommendation_requested"] = task.get("recommendation_requested", False)
        for key in ("audience", "usage_scenario"):
            if not isinstance(task.get(key), str) or not task[key].strip() or len(task[key]) > 4000:
                return fail("MISSING_" + key.upper())
        query = task.get("product_query")
        if query is not None and (not isinstance(query, str) or not query.strip() or len(query) > 4000):
            return fail("INVALID_PRODUCT_QUERY")
        if not query and task["recommendation_requested"] is not True:
            return fail("MISSING_PRODUCT_QUERY")
        channel = task.get("content_channel")
        if channel not in {None, "wechat_article", "xiaohongshu", "moments", "store_poster"}:
            return fail("INVALID_CONTENT_CHANNEL")
        if kind in {"marketing", "full_package"} and channel is None:
            return fail("MISSING_CONTENT_CHANNEL")
        if task["quote_required"] and (not isinstance(task.get("sales_platform"), str) or not task["sales_platform"].strip()):
            return fail("MISSING_SALES_PLATFORM")
        # Claims are never self-verified. No values that could select a rule
        # snapshot or authority are accepted inside quote_inputs.
        inputs = task.get("quote_inputs", {})
        limits = {"region": 256, "as_of": 64, "rule_timezone": 64, "currency": 16}
        if not isinstance(inputs, dict) or set(inputs) - (set(limits) | {"quantity", "eligibility"}):
            return fail("INVALID_QUOTE_INPUTS")
        clean_inputs = {}
        for name, maximum in limits.items():
            value = inputs.get(name)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > maximum):
                return fail("INVALID_QUOTE_INPUTS")
            clean_inputs[name] = value
        quantity = inputs.get("quantity")
        if quantity is not None and (type(quantity) is not int or quantity <= 0):
            return fail("INVALID_QUOTE_INPUTS")
        clean_inputs["quantity"] = quantity
        claims = inputs.get("eligibility", [])
        if not isinstance(claims, list) or len(claims) > 20:
            return fail("INVALID_ELIGIBILITY_CLAIMS")
        clean_inputs["eligibility"] = []
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) - {"kind", "claimed_status", "evidence_ref"}:
                return fail("INVALID_ELIGIBILITY_CLAIM")
            name, state, ref = claim.get("kind"), claim.get("claimed_status"), claim.get("evidence_ref")
            if not isinstance(name, str) or not name.strip() or len(name) > 128:
                return fail("INVALID_ELIGIBILITY_CLAIM")
            if state not in {"unknown", "user_claimed", "needs_verification"}:
                return fail("SELF_VERIFIED_ELIGIBILITY_FORBIDDEN")
            if ref is not None and (not isinstance(ref, str) or not ref.strip() or len(ref) > 512):
                return fail("INVALID_ELIGIBILITY_CLAIM")
            clean_inputs["eligibility"].append({"kind": name, "claimed_status": state, "evidence_ref": ref})
        task["quote_inputs"] = clean_inputs
        return {"ready": True, "payload_json": dump({"task": task}), "scope_ref": "", "proof": "", "message": ""}
    except (ValueError, TypeError, KeyError):
        return fail("SCENE_JSON_INVALID")
'''

SCOPE = BASE.COMMON + PRELIMINARY_RULES + r'''
def main(status_code: int, body: str, request_json: str) -> dict:
    try:
        # Exact known business discriminators only; private failure details are
        # not prompt input or customer-facing text. No retry/source fallback.
        if isinstance(status_code, (int, float)) and 200 <= status_code < 300:
            envelope = strict_json(body)
            details = envelope.get("data")
            if isinstance(details, dict):
                state, reason = envelope.get("status"), details.get("reason")
                message = None
                if state == "needs_source" and reason == "IMA_FACT_VERIFICATION_FAILED":
                    message = "本次尚未完成 ima 原文核验，未生成内容。请检查知识库访问、网络与所用资料版本后重试；应用不会自动切换到未核验来源。"
                elif state == "needs_source" and reason == "IMA_DAILY_SOURCE_LIMIT_REACHED":
                    message = "ima今日资料读取次数已达上限，接口提示明天再尝试。本次未完成参赛来源核验；请稍后重试，或明确使用本地开发模式进行调试。本地候选不能作为参赛核验通过记录。"
                elif state == "needs_source" and reason == "SOURCE_MODE_NOT_IMPLEMENTED":
                    message = "当前来源模式尚未启用，未生成内容。请启用并核验所需知识来源后重试；应用不会自动切换到其他来源。"
                elif state == "needs_input" and reason == "PRODUCT_AMBIGUOUS_OR_MISSING":
                    message = "请确认完整产品型号、年份或系统版本及相关配置后重试。型号尚未明确，暂未生成内容。"
                if message is not None:
                    failure = fail("SOURCE_SCOPE_NOT_READY")
                    failure["message"] = message
                    return failure
        data = business_response(status_code, body)
        task = strict_json(request_json)["task"]
        needed = ("source_context_ref", "source_context_proof", "purpose_ref", "destination_ref")
        if any(not isinstance(data.get(k), str) or not data[k] for k in needed):
            return fail("SOURCE_SCOPE_OR_PURPOSE_MISSING")
        request = {"source_context_ref": data["source_context_ref"], "task": task,
                   "product_query": task.get("product_query"), "content_channel": task.get("content_channel"),
                   "sales_platform": task.get("sales_platform"), "need_product_facts": True,
                   "need_pricing_rules": task["quote_required"],
                   "need_images": task["task_kind"] in {"marketing", "full_package"},
                   "retrieval_intent": preliminary_strategy(task),
                   "purpose_ref": data["purpose_ref"], "destination_ref": data["destination_ref"]}
        return {"ready": True, "payload_json": dump(request), "scope_ref": data["source_context_ref"],
                "proof": data["source_context_proof"], "message": ""}
    except (ValueError, TypeError, KeyError):
        return fail("SOURCE_SCOPE_NOT_READY")
'''

# Uniform Code outputs make branch selectors stable. tool_json contains only
# server-produced references/request metadata, never raw P4 or source proofs.
COMMON = BASE.COMMON + PRELIMINARY_RULES + r'''
import re
from datetime import datetime, timezone

def result(bundle=None, tool=None, route="", quote_ref="", quote_version="", validation_ref=""):
    return {"ready": True, "payload_json": dump(bundle or {}), "tool_json": dump(tool or {}),
            "route": route, "quote_ref": quote_ref, "quote_version": quote_version,
            "validation_ref": validation_ref, "message": ""}

def blocked(code, route="needs_source"):
    value = result(route=route)
    value.update(ready=False, message="BLOCKED: " + code)
    return value

def marketing_scope(bundle):
    task = bundle.get("task")
    if not isinstance(task, dict) or task.get("task_kind") not in {"marketing", "full_package"}:
        raise ValueError("MARKETING_TASK_REQUIRED")
    scope = task.get("delivery_scope", "complete_package")
    if scope not in {"content_only", "complete_package"} or (scope == "content_only" and task["task_kind"] != "marketing"):
        raise ValueError("MARKETING_DELIVERY_SCOPE_INVALID")
    expected = scope != "content_only"
    if any(type(task.get(k)) is not bool or task[k] is not expected for k in ("quote_required", "purchase_plan_required")):
        raise ValueError("MARKETING_QUOTE_FLAGS_INCONSISTENT")
    if type(task.get("script_required")) is not bool or (scope == "content_only" and task["script_required"]):
        raise ValueError("MARKETING_SCRIPT_SCOPE_INVALID")
    if task["task_kind"] == "full_package" and task["script_required"] is not True:
        raise ValueError("FULL_PACKAGE_SCRIPT_REQUIRED")
    return scope

def check_content_only_quote_context(bundle):
    if marketing_scope(bundle) != "content_only":
        raise ValueError("EXPLICIT_CONTENT_ONLY_REQUIRED")
    quote = bundle.get("quote_context")
    if (not isinstance(quote, dict) or quote.get("quote_required") is not False
            or quote.get("purchase_plan_required") is not False or quote.get("client_quote_allowed") is not False
            or any(quote.get(k) is not None for k in ("quote_status", "quote_ref", "quote_version", "validation_ref", "customer_quote_summary"))):
        raise ValueError("CONTENT_ONLY_HAS_QUOTE_STATE")
    if any(k in bundle for k in ("draft", "reviewed_artifacts", "content_verification_ref")):
        raise ValueError("CONTENT_ONLY_PREEXISTING_ARTIFACTS_FORBIDDEN")

def opaque(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}", value))

def response(status_code, body):
    if type(status_code) not in (int, float) or not 200 <= status_code < 300:
        raise ValueError("HTTP_ERROR")
    envelope = strict_json(body)
    state = envelope.get("status")
    if state != "ready":
        if state not in {"needs_input", "needs_source", "conflict", "denied", "error"}:
            raise ValueError("INVALID_BUSINESS_STATE")
        return None, state
    if not isinstance(envelope.get("data"), dict):
        raise ValueError("DATA_OBJECT_REQUIRED")
    return envelope["data"], "ready"

def guard_destinations(bundle, expected):
    policy = bundle.get("policy", {})
    grants = policy.get("allowed_model_destinations")
    if policy.get("llm_payload_allowed") is not True or not isinstance(grants, list):
        raise ValueError("DESTINATION_NOT_APPROVED")
    # Derive the consumers from the bound task, never from a possibly empty
    # service assertion or the set of models currently present on the canvas.
    # Keep this required-node rule aligned with Bridge.policy.
    task = bundle.get("task")
    if not isinstance(task, dict) or task.get("task_kind") not in {"product_intro", "marketing", "quote", "sales_script", "full_package"}:
        raise ValueError("DESTINATION_TASK_INVALID")
    if any(type(task.get(flag)) is not bool for flag in ("quote_required", "script_required")):
        raise ValueError("DESTINATION_TASK_INVALID")
    required = {"fact_compliance_review"}
    if task["task_kind"] in {"marketing", "full_package"}:
        if task.get("content_channel") not in {"wechat_article", "xiaohongshu", "moments", "store_poster"}:
            raise ValueError("DESTINATION_TASK_INVALID")
        required |= {"poster_copy" if task["content_channel"] == "store_poster" else "article_write",
                     "platform_strategy", "visual_layout", "visual_review"}
    elif task["task_kind"] == "product_intro":
        required.add("product_intro")
    if task["quote_required"]:
        required.add("quote_explain")
    if task["script_required"]:
        required.add("sales_demo")
    declared = policy.get("required_model_nodes")
    if (not isinstance(declared, list) or not declared or any(not isinstance(node, str) for node in declared)
            or len(declared) != len(set(declared)) or set(declared) != required):
        raise ValueError("REQUIRED_MODEL_NODES_MISMATCH")
    if not isinstance(expected, list):
        raise ValueError("MODEL_BINDINGS_REQUIRED")
    selected = {}
    for item in expected:
        if not isinstance(item, dict):
            raise ValueError("MODEL_BINDINGS_INVALID")
        node = item.get("node_id")
        if node not in required:
            continue
        if node in selected or any(not isinstance(item.get(key), str) or not item[key].strip()
                                   for key in ("node_id", "provider", "model")):
            raise ValueError("MODEL_BINDINGS_INVALID")
        selected[node] = item
    if set(selected) != required:
        raise ValueError("REQUIRED_MODEL_BINDING_MISSING")
    for item in selected.values():
        if not any(isinstance(grant, dict) and all(grant.get(k) == v for k, v in item.items()) for grant in grants):
            raise ValueError("DESTINATION_NOT_APPROVED")

def reject_private_fields(value):
    # Last line of defense for structured metadata. This does not claim to
    # classify arbitrary prose; the authenticated service still owns source
    # classification and field-level disclosure policy.
    forbidden = {"api_key", "apikey", "secret", "password", "authorization", "client_id", "access_token", "source_context_proof", "raw_p4", "raw_rules", "internal_cost", "floor_price", "margin", "rebate", "approval_notes", "signed_url", "filesystem_path"}
    if isinstance(value, dict):
        if any(isinstance(key, str) and key.lower() in forbidden for key in value):
            raise ValueError("PRIVATE_FIELD_IN_MODEL_PAYLOAD")
        for item in value.values():
            reject_private_fields(item)
    elif isinstance(value, list):
        for item in value:
            reject_private_fields(item)

def pointer(obj, target):
    if not isinstance(target, str) or not target.startswith("/"):
        raise ValueError("POINTER_REQUIRED")
    value = obj
    for token in target[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("INVALID_POINTER_ESCAPE")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ValueError("INVALID_ARRAY_POINTER")
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError("POINTER_TARGET_INVALID")
    return value

def visible_cells(draft):
    # These are customer-visible text-bearing fields. Reference IDs, status,
    # source metadata and machine assertions are not presented as customer text.
    cells = {}
    for key in ("content", "customer_explanation", "segments", "safe_customer_message"):
        if key in draft and draft[key] is not None:
            cells.update(content_cells(draft[key], "/" + key))
    plan = draft.get("purchase_plan")
    if isinstance(plan, dict) and isinstance(plan.get("platform_summary"), str):
        cells["/purchase_plan/platform_summary"] = plan["platform_summary"]
    images = draft.get("image_plan", [])
    if isinstance(images, list):
        for index, image in enumerate(images):
            if isinstance(image, dict) and isinstance(image.get("caption"), str) and image["caption"].strip():
                cells["/image_plan/" + str(index) + "/caption"] = image["caption"]
    return cells

def quote_summary(bundle):
    quote = bundle.get("quote_context")
    if not isinstance(quote, dict) or quote.get("quote_status") != "VALID_OPTIMAL" or quote.get("client_quote_allowed") is not True or not opaque(quote.get("validation_ref")):
        raise ValueError("QUOTE_GATE_NOT_PASSED")
    summary = quote.get("customer_quote_summary")
    if not isinstance(summary, dict):
        raise ValueError("CUSTOMER_SUMMARY_MISSING")
    for key in ("quote_ref", "quote_version", "product_ref"):
        if not opaque(summary.get(key)):
            raise ValueError("QUOTE_REFERENCE_INVALID")
    if not isinstance(summary.get("formatted_customer_payable"), str) or not summary["formatted_customer_payable"] or not isinstance(summary.get("valid_until"), str) or not summary["valid_until"]:
        raise ValueError("QUOTE_SUMMARY_INCOMPLETE")
    expires = datetime.fromisoformat(summary["valid_until"].replace("Z", "+00:00"))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("QUOTE_EXPIRED_OR_TIMEZONE_MISSING")
    cash = summary.get("cash_due_now_minor")
    if type(cash) is not int or cash < 0 or summary.get("customer_payable_minor") != cash:
        raise ValueError("CASH_OBJECTIVE_MISMATCH")
    if summary.get("objective_metric") != "min_cash_due_now_given_verified_customer_resources":
        raise ValueError("CASH_OBJECTIVE_MISMATCH")
    plan = summary.get("customer_purchase_plan")
    if not isinstance(plan, dict) or not opaque(plan.get("plan_ref")) or not opaque(plan.get("plan_version")):
        raise ValueError("CUSTOMER_PURCHASE_PLAN_REQUIRED")
    if any(plan.get(k) != summary[k] for k in ("quote_ref", "quote_version")) or plan.get("selected_product_ref") != summary["product_ref"]:
        raise ValueError("PURCHASE_PLAN_BINDING_INVALID")
    if plan.get("objective_metric") != summary["objective_metric"]:
        raise ValueError("PLAN_OBJECTIVE_MISMATCH")
    for key in ("customer_resource_snapshot_ref", "customer_resource_snapshot_version"):
        if not opaque(summary.get(key)) or plan.get(key) != summary[key]:
            raise ValueError("RESOURCE_SNAPSHOT_BINDING_INVALID")
    if not opaque(summary.get("resource_use_scope_ref")):
        raise ValueError("RESOURCE_SCOPE_REQUIRED")
    levels = plan.get("level_rows")
    expected = {"base_price": "基准价", "platform_discount": "平台优惠", "identity_benefit": "身份权益", "trade_in_national_subsidy": "换新国补"}
    if not isinstance(levels, list) or len(levels) != 4 or {r.get("level_id") for r in levels if isinstance(r, dict)} != set(expected):
        raise ValueError("FOUR_LEVELS_INCOMPLETE")
    for row in levels:
        if row.get("display_name") != expected[row["level_id"]] or row.get("applicability") not in {"applicable", "not_applicable", "excluded_mutual_exclusion"} or not row.get("reason"):
            raise ValueError("FOUR_LEVELS_UNKNOWN_OR_UNEXPLAINED")
    rows = plan.get("comparison_rows")
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or not r.get("comparison_sentence") for r in rows):
        raise ValueError("SAFE_COMPARISON_REQUIRED")
    coverage = plan.get("comparison_coverage")
    if not isinstance(coverage, dict) or coverage.get("same_sku_complete") is not True:
        raise ValueError("CANDIDATE_COVERAGE_UNPROVEN")
    # This candidate has one exact-SKU path. It refuses multi-SKU requests until
    # a scheduler/independent aggregate validator has actually been implemented.
    if coverage.get("expected_sku_count") != 1 or coverage.get("validated_sku_count") != 1:
        raise ValueError("MULTI_SKU_SCHEDULER_NOT_CONNECTED")
    for key in ("optimal_scope_sentence", "resource_usage_sentence", "conditions_sentence", "valid_until_display"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError("PURCHASE_PLAN_EXPLANATION_INCOMPLETE")
    if plan.get("content_channel") != bundle["task"].get("content_channel"):
        raise ValueError("PURCHASE_PLAN_CHANNEL_MISMATCH")
    return summary

def check_claims(bundle, draft):
    if draft.get("status") != "ready" or not isinstance(draft.get("blockers"), list) or draft["blockers"]:
        raise ValueError("MODEL_CANDIDATE_NOT_READY")
    rows = draft.get("claims", draft.get("claim_refs"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("CLAIMS_REQUIRED")
    facts, sources, rules = reference_sets(bundle)
    cells = visible_cells(draft)
    if not cells:
        raise ValueError("CUSTOMER_TEXT_REQUIRED")
    if bundle["task"].get("delivery_scope") == "content_only":
        if marketing_scope(bundle) != "content_only" or draft.get("purchase_plan") is not None or any(
                draft.get(key) is not None for key in ("quote_ref", "quote_version", "purchase_plan_ref", "purchase_plan_version")):
            raise ValueError("CONTENT_ONLY_QUOTE_METADATA_FORBIDDEN")
        # Obvious amount/discount text is forbidden even if the model attaches
        # a real product fact ID. This lexical check is not semantic review.
        if any(re.search(r"[¥￥$€]|(?<![A-Za-z])(?:CNY|RMB|USD)\s*\d|\d[\d,.]*\s*(?:元|折)|[一二三四五六七八九十百千万]+元|到手价|实付|优惠价|立减|满减", text, re.I) for text in cells.values()):
            raise ValueError("CONTENT_ONLY_PRICE_TEXT_FORBIDDEN")
    summary = quote_summary(bundle) if bundle["task"]["quote_required"] else None
    bindings = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_CLAIM")
        target, text = row.get("target"), row.get("text")
        if target not in cells or not isinstance(text, str) or not text or text not in cells[target]:
            raise ValueError("CLAIM_TARGET_OR_TEXT_INVALID")
        binding = row.get("quote_binding")
        if binding is not None:
            if summary is None or binding != {"quote_ref": summary["quote_ref"], "quote_version": summary["quote_version"]}:
                raise ValueError("QUOTE_BINDING_INVALID")
            bindings += 1
        else:
            f, r = row.get("fact_ids", []), row.get("business_rule_ids", [])
            if not isinstance(f, list) or not isinstance(r, list) or not (f or r) or not set(f) <= facts or not set(r) <= rules:
                raise ValueError("CLAIM_EVIDENCE_INVALID")
    if summary:
        if not bindings:
            raise ValueError("PRICE_CLAIM_BINDING_REQUIRED")
        if summary["formatted_customer_payable"] not in "\n".join(cells.values()):
            raise ValueError("FORMATTED_CURRENT_CASH_MISSING")
        p = summary["customer_purchase_plan"]
        plan = draft.get("purchase_plan")
        if plan is not None:
            if not isinstance(plan, dict) or any(plan.get(k) != v for k, v in {"plan_ref": p["plan_ref"], "plan_version": p["plan_version"], "quote_ref": summary["quote_ref"], "quote_version": summary["quote_version"]}.items()):
                raise ValueError("DRAFT_PLAN_BINDING_INVALID")
        else:
            if draft.get("purchase_plan_ref") != p["plan_ref"] or draft.get("purchase_plan_version") != p["plan_version"]:
                raise ValueError("DRAFT_PLAN_BINDING_INVALID")
    return cells
'''

PRE_STRATEGY = COMMON + r'''
def main(request_json: str) -> dict:
    try:
        request = strict_json(request_json)
        if set(request) != {"task"} or not isinstance(request["task"], dict):
            return blocked("PRELIMINARY_TASK_REQUIRED")
        task = request["task"]
        if task.get("task_kind") in {"marketing", "full_package"}:
            marketing_scope({"task": task})
        return result({"task": task, "retrieval_intent": preliminary_strategy(task)})
    except (ValueError, TypeError, KeyError):
        return blocked("PRELIMINARY_STRATEGY_INVALID")
'''

MARKETING_SCOPE = COMMON + r'''
def main(bundle_json: str) -> dict:
    try:
        bundle = strict_json(bundle_json)
        return result(bundle, route=marketing_scope(bundle))
    except (ValueError, TypeError, KeyError):
        return blocked("MARKETING_DELIVERY_SCOPE_INVALID")
'''

CONTENT_ONLY_INPUT = COMMON + r'''
def main(bundle_json: str) -> dict:
    try:
        bundle = strict_json(bundle_json)
        check_content_only_quote_context(bundle)
        return result(bundle)
    except (ValueError, TypeError, KeyError):
        return blocked("EXPLICIT_CONTENT_ONLY_INPUT_REQUIRED")
'''

MARKETING_INPUT = COMMON + r'''
def main(selected_json: str) -> dict:
    try:
        bundle = strict_json(selected_json)
        scope = marketing_scope(bundle)
        if scope == "content_only":
            check_content_only_quote_context(bundle)
        else:
            quote_summary(bundle)
        if not isinstance(bundle.get("trusted_context"), dict) or not bundle["trusted_context"].get("source_context_ref"):
            return blocked("MARKETING_SOURCE_CONTEXT_REQUIRED")
        reject_private_fields(bundle)
        return result(bundle)
    except (ValueError, TypeError, KeyError):
        return blocked("MARKETING_INPUT_SCOPE_OR_QUOTE_INVALID")
'''

EVIDENCE = COMMON + r'''
EXPECTED = __EXPECTED__
def main(status_code: int, body: str, task_json: str, scope_ref: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            failure = blocked("EVIDENCE_" + state.upper(), state)
            # Inspect only the exact safe discriminator. Never forward service
            # questions, arbitrary reasons, error bodies or private data.
            envelope = strict_json(body)
            details = envelope.get("data")
            if isinstance(details, dict) and details.get("reason") == "FOUR_LEVELS_PENDING":
                failure["message"] = "暂时无法生成含价格的成品。还缺少与具体商品型号、销售平台、地区和有效期对应的已核验四级价格规则，以及顾客权益、旧机条件的核验结果（含明确不适用）。四级为基准价、平台优惠、身份权益、换新国补；补齐并核验后才能计算最优购买方案。"
            return failure
        bundle = data.get("task_bundle")
        if not isinstance(bundle, dict):
            return blocked("TASK_BUNDLE_MISSING")
        task = strict_json(task_json)["task"]
        if not isinstance(bundle.get("task"), dict) or any(bundle["task"].get(k) != v for k, v in task.items()):
            return blocked("TASK_BINDING_MISMATCH", "denied")
        context = bundle.get("trusted_context")
        if not isinstance(context, dict) or context.get("source_context_ref") != scope_ref:
            return blocked("SCOPE_BINDING_MISMATCH", "denied")
        mode = context.get("source_mode")
        if mode not in {"local_snapshot", "ima_live", "hybrid_verified"} or not context.get("source_snapshot_ref"):
            return blocked("SOURCE_SNAPSHOT_UNVERIFIED")
        if mode == "local_snapshot" and context.get("competition_eligible") is not False:
            return blocked("LOCAL_SNAPSHOT_CANNOT_CLAIM_IMA")
        facts, refs, rules = reference_sets(bundle)
        if not facts or not refs or bundle.get("unresolved_conflicts"):
            return blocked("FACTS_MISSING_OR_CONFLICTING", "conflict" if bundle.get("unresolved_conflicts") else "needs_source")
        for row in bundle["evidence"]["source_refs"]:
            if not row.get("content_hash"):
                return blocked("SOURCE_HASH_REQUIRED")
        if any(not isinstance(f.get("source_ref_ids"), list) or not f["source_ref_ids"] or not set(f["source_ref_ids"]) <= refs for f in bundle["evidence"]["facts"]):
            return blocked("FACT_SOURCE_LINK_INVALID")
        guard_destinations(bundle, EXPECTED)
        approved = {key: bundle[key] for key in ("task", "evidence")}
        policy_keys = {"llm_payload_allowed", "allowed_model_destinations", "required_model_nodes", "source_mode", "competition_eligible", "export_allowed", "development_single_user_only", "multi_store_authorization_implemented", "asset_policy", "platform_rules", "render_constraints"}
        approved["policy"] = {key: value for key, value in bundle["policy"].items() if key in policy_keys}
        approved["trusted_context"] = safe_source_context(context, bundle)
        # Service must already have field-filtered these lists for the approved
        # purpose/model destinations. Raw source objects are never forwarded.
        approved["allowed_assets"] = bundle.get("allowed_assets", [])
        approved["quote_context"] = {"quote_required": task["quote_required"], "purchase_plan_required": task["purchase_plan_required"], "quote_status": None, "client_quote_allowed": False, "customer_quote_summary": None}
        approved["retrieval_intent"] = preliminary_strategy(task)
        if task["task_kind"] in {"marketing", "full_package"}:
            marketing_scope(approved)
        reject_private_fields(approved)
        request = data.get("quote_request", {}) if task["quote_required"] else {}
        if task["quote_required"]:
            if not isinstance(request, dict):
                return blocked("SERVICE_QUOTE_REQUEST_REQUIRED")
            required = {"source_context_ref", "product_ref", "quantity", "currency", "region", "sales_platform", "as_of", "rule_timezone", "eligibility_refs", "customer_resource_snapshot_ref", "customer_resource_snapshot_version", "resource_use_scope_ref", "four_levels_spec_ref", "price_rule_set_ref", "objective", "objective_metric", "objective_metric_version", "task_version_ref", "idempotency_key", "purpose_ref", "destination_ref"}
            if set(request) - (required | {"recommendation_set_ref"}) or not required <= set(request):
                return blocked("SERVICE_QUOTE_REQUEST_INCOMPLETE")
            if request.get("source_context_ref") != scope_ref or request.get("objective") != "min_customer_payable" or request.get("objective_metric") != "min_cash_due_now_given_verified_customer_resources":
                return blocked("SERVICE_QUOTE_SCOPE_OR_OBJECTIVE_INVALID")
            coverage = data.get("recommendation_coverage")
            if not isinstance(coverage, dict) or coverage.get("expected_sku_count") != 1:
                return blocked("MULTI_SKU_SCHEDULER_NOT_CONNECTED")
        return result(approved, request, task["task_kind"])
    except (ValueError, TypeError, KeyError):
        return blocked("EVIDENCE_PAYLOAD_OR_DESTINATION_INVALID")
'''

SOLVE = COMMON + r'''
def main(status_code: int, body: str, bundle_json: str, request_json: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            return blocked("QUOTE_SOLVE_" + state.upper(), state)
        if data.get("quote_status") != "FEASIBLE_NOT_PROVEN" or data.get("reason") != "PENDING_INDEPENDENT_VALIDATION":
            return blocked("QUOTE_NOT_READY_FOR_INDEPENDENT_VALIDATION")
        q, v, dep = data.get("quote_ref"), data.get("quote_version"), data.get("dependency_hash")
        if not all(opaque(x) for x in (q, v, dep)):
            return blocked("QUOTE_REFERENCE_OR_DEPENDENCY_INVALID")
        previous = strict_json(request_json)
        request = {key: previous[key] for key in ("task_version_ref", "purpose_ref", "destination_ref")}
        request.update(quote_version=v, expected_dependency_hash=dep)
        bundle = strict_json(bundle_json)
        return result(bundle, request, quote_ref=q, quote_version=v)
    except (ValueError, TypeError, KeyError):
        return blocked("QUOTE_SOLVE_RESPONSE_INVALID")
'''

VALIDATE = COMMON + r'''
def main(status_code: int, body: str, bundle_json: str, quote_ref: str, quote_version: str, request_json: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            return blocked("QUOTE_VALIDATE_" + state.upper(), state)
        if data.get("quote_status") != "VALID_OPTIMAL" or data.get("quote_ref") != quote_ref or data.get("quote_version") != quote_version or not opaque(data.get("validation_ref")):
            return blocked("INDEPENDENT_QUOTE_VALIDATION_REQUIRED")
        request = strict_json(request_json)
        bundle = strict_json(bundle_json)
        bundle["quote_context"].update(quote_status="VALID_OPTIMAL", quote_ref=quote_ref, quote_version=quote_version, validation_ref=data["validation_ref"])
        return result(bundle, {key: request[key] for key in ("quote_version", "purpose_ref", "destination_ref")}, quote_ref=quote_ref, quote_version=quote_version, validation_ref=data["validation_ref"])
    except (ValueError, TypeError, KeyError):
        return blocked("QUOTE_VALIDATE_RESPONSE_INVALID")
'''

CLIENT_VIEW = COMMON + r'''
def main(status_code: int, body: str, bundle_json: str, quote_ref: str, quote_version: str, validation_ref: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            return blocked("CLIENT_VIEW_" + state.upper(), state)
        if data.get("quote_status") != "VALID_OPTIMAL" or data.get("client_quote_allowed") is not True or data.get("validation_ref") != validation_ref:
            return blocked("CUSTOMER_QUOTE_NOT_AUTHORIZED", "denied")
        bundle = strict_json(bundle_json)
        summary = data.get("customer_quote_summary")
        if not isinstance(summary, dict) or summary.get("quote_ref") != quote_ref or summary.get("quote_version") != quote_version:
            return blocked("CLIENT_QUOTE_VERSION_MISMATCH")
        bundle["quote_context"].update(customer_quote_summary=summary, client_quote_allowed=True, validation_ref=validation_ref)
        reject_private_fields(summary)
        quote_summary(bundle)
        # Script input construction is server-owned. Never invent demo action,
        # fact-set or permission references in a Code/LLM node.
        script_request = data.get("script_request")
        allowed = {"quote_version", "validation_ref", "product_fact_set_ref", "customer_need_ref", "demo_action_plan_ref", "cta_ref", "task_version_ref", "purpose_ref", "destination_ref"}
        if not isinstance(script_request, dict) or set(script_request) != allowed or any(not opaque(v) for v in script_request.values()):
            script_request = {}
        return result(bundle, script_request, route=bundle["task"]["task_kind"], quote_ref=quote_ref, quote_version=quote_version, validation_ref=validation_ref)
    except (ValueError, TypeError, KeyError):
        return blocked("CUSTOMER_PURCHASE_PLAN_INVALID_OR_INCOMPLETE")
'''

STRATEGY = COMMON + r'''
def main(text: str, bundle_json: str) -> dict:
    try:
        bundle, strategy = strict_json(bundle_json), strict_json(text)
        if strategy.get("status") != "ready" or strategy.get("blockers") or strategy.get("platform") != bundle["task"]["content_channel"]:
            return blocked("STRATEGY_NOT_READY_OR_CHANNEL_MISMATCH")
        facts, _, rules = reference_sets(bundle)
        points = strategy.get("priority_points")
        if not isinstance(points, list) or not points:
            return blocked("STRATEGY_EVIDENCE_REQUIRED")
        for point in points:
            if not isinstance(point, dict):
                return blocked("STRATEGY_POINT_INVALID")
            f, r = point.get("fact_ids", []), point.get("business_rule_ids", [])
            if not isinstance(f, list) or not isinstance(r, list) or not (f or r) or not set(f) <= facts or not set(r) <= rules:
                return blocked("STRATEGY_REFERENCE_INVALID")
        bundle["strategy_plan"] = strategy
        return result(bundle, route=bundle["task"]["content_channel"])
    except (ValueError, TypeError, KeyError):
        return blocked("STRATEGY_JSON_INVALID")
'''


def parse_draft(kind: str) -> str:
    """Independent parser for each actual prompt contract, not an LLM approval."""
    return COMMON + "\nKIND = " + repr(kind) + r'''
def main(text: str, bundle_json: str) -> dict:
    try:
        bundle, draft = strict_json(bundle_json), strict_json(text)
        check_claims(bundle, draft)
        if KIND in {"article", "poster", "product_intro"}:
            if not isinstance(draft.get("content"), dict) or draft["content"].get("type") != KIND:
                return blocked("WRONG_CONTENT_BRANCH")
            knowledge = draft.get("knowledge_basis")
            _, sources, _ = reference_sets(bundle)
            if not isinstance(knowledge, list) or not knowledge or any(not isinstance(row, dict) or row.get("source_ref_id") not in sources for row in knowledge):
                return blocked("READABLE_SOURCE_BASIS_REQUIRED")
            if KIND != "product_intro":
                plan = draft.get("image_plan")
                allowed = bundle.get("allowed_assets")
                if not isinstance(plan, list) or not isinstance(allowed, list):
                    return blocked("IMAGE_PLAN_AND_AUTHORIZED_ASSETS_REQUIRED")
                ids = {a.get("asset_id") for a in allowed if isinstance(a, dict)}
                expected = {"wechat_article": (2, 4), "xiaohongshu": (3, 6), "moments": (1, 3), "store_poster": (1, 1)}[bundle["task"]["content_channel"]]
                used = [p.get("asset_id") for p in plan if isinstance(p, dict)]
                if len(used) != len(plan) or len(set(used)) != len(used) or not set(used) <= ids or not expected[0] <= len(used) <= expected[1]:
                    return blocked("IMAGE_COUNT_ID_OR_AUTHORIZATION_INVALID")
                if KIND == "poster" and (not isinstance(draft["content"].get("benefits"), list) or not 1 <= len(draft["content"]["benefits"]) <= 3):
                    return blocked("POSTER_BENEFIT_LIMIT_INVALID")
            elif draft.get("image_plan"):
                return blocked("PRODUCT_INTRO_IMAGE_BRANCH_UNSUPPORTED")
        if KIND == "sales_script":
            segments = draft.get("segments")
            expected = [(0,20),(20,45),(45,85),(85,120),(120,155),(155,180)]
            if not isinstance(segments, list) or len(segments) != 6 or [(s.get("start_second"),s.get("end_second")) for s in segments] != expected:
                return blocked("SIX_SEGMENT_SCRIPT_TIMING_REQUIRED")
            if any(not s.get("verbatim_text") or not isinstance(s.get("staff_actions"), list) for s in segments):
                return blocked("SCRIPT_TEXT_AND_ACTIONS_REQUIRED")
        bundle["draft"] = draft
        bundle["current_draft_kind"] = KIND
        return result(bundle)
    except (ValueError, TypeError, KeyError, IndexError):
        return blocked("DRAFT_JSON_REFERENCE_OR_PRICE_BINDING_INVALID")
'''

REVIEW_GATE = COMMON + r'''
def main(text: str, bundle_json: str) -> dict:
    try:
        report = strict_json(text)
    except (ValueError, TypeError, RecursionError):
        failure = blocked("REVIEW_RESPONSE_FORMAT_INVALID")
        failure["message"] = "审核返回的格式不符合约定，本次内容未放行。请重新发起任务；应用不会将格式错误视为审核通过。"
        return failure
    try:
        bundle = strict_json(bundle_json)
        draft = bundle["draft"]
        cells = check_claims(bundle, draft)
        findings, coverage = report.get("findings"), report.get("coverage")
        if not isinstance(findings, list) or not findings or not isinstance(coverage, dict) or report.get("conflicts") != [] or report.get("needs_human_review") is not False or coverage.get("unmapped_claims") != []:
            return blocked("REVIEW_UNRESOLVED")
        checked = coverage.get("checked_target_refs")
        if not isinstance(checked, list) or not set(cells) <= set(checked):
            return blocked("REVIEW_COVERAGE_INCOMPLETE")
        facts, refs, rules = reference_sets(bundle)
        summary = quote_summary(bundle) if bundle["task"]["quote_required"] else None
        binding = {"quote_ref": summary["quote_ref"], "quote_version": summary["quote_version"]} if summary else None
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("decision") != "supported" or finding.get("target_ref") not in cells:
                return blocked("REVIEW_FINDING_BLOCKING_OR_POINTER_INVALID")
            finding_text = finding.get("text")
            if not isinstance(finding_text, str) or not finding_text.strip() or finding_text not in cells[finding["target_ref"]]:
                return blocked("REVIEW_FINDING_TEXT_NOT_IN_CURRENT_CELL")
            evidence = finding.get("evidence_refs", [])
            if not isinstance(evidence, list) or not set(evidence) <= facts | refs | rules:
                return blocked("REVIEW_REFERENCE_INVALID")
            if finding.get("quote_binding") is not None and finding["quote_binding"] != binding:
                return blocked("REVIEW_QUOTE_BINDING_INVALID")
        for target, cell_text in cells.items():
            # A location alone, or several reviewed fragments, cannot cover
            # text added after review. Require an exact whole-cell finding.
            # This verifies current coverage, not semantic fact support.
            if not any(f["target_ref"] == target and f["text"] == cell_text for f in findings):
                return blocked("VISIBLE_TEXT_NOT_INDEPENDENTLY_REVIEWED")
        for claim in draft.get("claims", draft.get("claim_refs", [])):
            if not any(f["target_ref"] == claim["target"] and isinstance(f.get("text"), str) and claim["text"] in f["text"] and
                       ((claim.get("quote_binding") is not None and f.get("quote_binding") == claim["quote_binding"]) or
                        (claim.get("quote_binding") is None and f.get("evidence_refs"))) for f in findings):
                return blocked("CLAIM_NOT_INDEPENDENTLY_REVIEWED")
        kind = bundle["current_draft_kind"]
        artifacts = bundle.get("reviewed_artifacts", {})
        artifacts[kind] = {"draft": draft, "review": report, "content_hash": hashlib.sha256(dump(draft).encode()).hexdigest()}
        bundle["reviewed_artifacts"] = artifacts
        return result(bundle)
    except (ValueError, TypeError, KeyError):
        return blocked("INDEPENDENT_REVIEW_INVALID")
'''

LAYOUT = COMMON + r'''
def main(text: str, bundle_json: str) -> dict:
    try:
        bundle, layout = strict_json(bundle_json), strict_json(text)
        if layout.get("status") != "ready" or layout.get("blockers"):
            return blocked("LAYOUT_NOT_READY")
        bundle["layout_plan"] = layout
        if bundle["task"]["content_channel"] != "store_poster":
            # There is no audited browser/page renderer or image-file adapter in
            # this candidate. An image plan is not a visual inspection record.
            return blocked("ARTICLE_VISUAL_INPUT_ADAPTER_NOT_IMPLEMENTED")
        if layout.get("mode") != "poster":
            return blocked("POSTER_LAYOUT_MODE_REQUIRED")
        current = bundle["reviewed_artifacts"]["poster"]
        request = {"source_context_ref": bundle["trusted_context"]["source_context_ref"],
                   "content": current["draft"], "content_hash": current["content_hash"],
                   "layout_plan": layout, "asset_refs": [p["asset_id"] for p in current["draft"]["image_plan"]]}
        return result(bundle, request)
    except (ValueError, TypeError, KeyError):
        return blocked("LAYOUT_JSON_OR_CONTENT_BINDING_INVALID")
'''

RENDER = COMMON + r'''
def main(status_code: int, body: str, bundle_json: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            return blocked("RENDER_" + state.upper(), state)
        # A JSON png_ref/hash is insufficient to feed pixels to a Dify vision
        # LLM. Do not fake vision by sending that JSON to a text-only model.
        return blocked("VISION_FILE_ADAPTER_NOT_IMPLEMENTED")
    except (ValueError, TypeError, KeyError):
        return blocked("RENDER_RESPONSE_INVALID")
'''

SCRIPT_REQUEST = COMMON + r'''
def main(bundle_json: str, script_request_json: str) -> dict:
    try:
        bundle = strict_json(bundle_json)
        summary = quote_summary(bundle)
        request = strict_json(script_request_json)
        required = {"quote_version", "validation_ref", "product_fact_set_ref", "customer_need_ref", "demo_action_plan_ref", "cta_ref", "task_version_ref", "purpose_ref", "destination_ref"}
        if not isinstance(request, dict) or set(request) != required or any(not opaque(request[k]) for k in required):
            return blocked("SERVER_BOUND_SCRIPT_INPUT_REQUEST_REQUIRED")
        if request["quote_version"] != summary["quote_version"] or request["validation_ref"] != bundle["quote_context"]["validation_ref"]:
            return blocked("SCRIPT_INPUT_VERSION_MISMATCH")
        return result(bundle, request, quote_ref=summary["quote_ref"], quote_version=summary["quote_version"], validation_ref=request["validation_ref"])
    except (ValueError, TypeError, KeyError):
        return blocked("SCRIPT_PREREQUISITES_INVALID")
'''

SCRIPT_INPUT = COMMON + r'''
def main(status_code: int, body: str, bundle_json: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            return blocked("SCRIPT_INPUT_" + state.upper(), state)
        original = strict_json(bundle_json)
        candidate = data.get("task_bundle")
        if not isinstance(candidate, dict) or candidate.get("task") != original["task"] or candidate.get("trusted_context") != original["trusted_context"]:
            return blocked("SCRIPT_INPUT_TASK_OR_SCOPE_MISMATCH")
        if candidate.get("policy") != original["policy"] or candidate.get("evidence") != original["evidence"] or candidate.get("allowed_assets", []) != original.get("allowed_assets", []):
            return blocked("SCRIPT_INPUT_SOURCE_OR_DESTINATION_CHANGED")
        if quote_summary(candidate) != quote_summary(original):
            return blocked("SCRIPT_INPUT_QUOTE_MISMATCH")
        for key in ("demo_action_plan", "product_identity_ref", "customer_need_ref"):
            if not candidate.get(key):
                return blocked("SCRIPT_ACTION_PRODUCT_OR_NEED_BINDING_MISSING")
        approved = dict(original)
        for key in ("demo_action_plan", "product_identity_ref", "customer_need_ref", "cta_ref"):
            if key in candidate:
                approved[key] = candidate[key]
        return result(approved)
    except (ValueError, TypeError, KeyError):
        return blocked("SCRIPT_INPUT_RESPONSE_INVALID")
'''

VERIFY_REQUEST = COMMON + r'''
def main(bundle_json: str) -> dict:
    try:
        bundle = strict_json(bundle_json)
        summary = quote_summary(bundle)
        artifacts = bundle.get("reviewed_artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            return blocked("INDEPENDENTLY_REVIEWED_ARTIFACTS_REQUIRED")
        if bundle["task"]["script_required"] and "sales_script" not in artifacts:
            return blocked("REQUIRED_SCRIPT_MISSING")
        # Full marketing is deliberately unreachable here until image paths
        # acquire actual rendering/visual records and their version binding.
        if bundle["task"]["task_kind"] in {"marketing", "full_package"}:
            return blocked("REQUIRED_VISUAL_PIPELINE_NOT_COMPLETE")
        request = {"source_context_ref": bundle["trusted_context"]["source_context_ref"],
                   "quote_version": summary["quote_version"], "validation_ref": bundle["quote_context"]["validation_ref"],
                   "content": artifacts, "content_hash": hashlib.sha256(dump(artifacts).encode()).hexdigest(),
                   "purchase_plan_ref": summary["customer_purchase_plan"]["plan_ref"],
                   "purchase_plan_version": summary["customer_purchase_plan"]["plan_version"]}
        return result(bundle, request, quote_ref=summary["quote_ref"], quote_version=summary["quote_version"], validation_ref=bundle["quote_context"]["validation_ref"])
    except (ValueError, TypeError, KeyError):
        return blocked("FINAL_VERIFY_REQUEST_INVALID")
'''

VERIFY_RESPONSE = COMMON + r'''
def main(status_code: int, body: str, bundle_json: str, request_json: str) -> dict:
    try:
        data, state = response(status_code, body)
        if state != "ready":
            return blocked("VERIFY_CONTENT_" + state.upper(), state)
        request = strict_json(request_json)
        if data.get("passed") is not True or data.get("content_hash") != request["content_hash"] or not opaque(data.get("content_verification_ref")):
            return blocked("CONTENT_SERVER_VERIFICATION_REQUIRED")
        bundle = strict_json(bundle_json)
        bundle["content_verification_ref"] = data["content_verification_ref"]
        return result(bundle)
    except (ValueError, TypeError, KeyError):
        return blocked("VERIFY_CONTENT_RESPONSE_INVALID")
'''

FINALIZE_REQUEST = COMMON + r'''
def main(bundle_json: str) -> dict:
    try:
        bundle = strict_json(bundle_json)
        artifacts = bundle.get("reviewed_artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            return blocked("REVIEWED_ARTIFACTS_REQUIRED")
        kind = bundle["task"]["task_kind"]
        if kind in {"marketing", "full_package"}:
            return blocked("MARKETING_VISUAL_AND_MULTI_SKU_ACCEPTANCE_NOT_COMPLETE")
        if bundle["task"]["quote_required"] and not opaque(bundle.get("content_verification_ref")):
            return blocked("SERVER_QUOTE_CONTENT_VERIFICATION_REQUIRED")
        request = {"source_context_ref": bundle["trusted_context"]["source_context_ref"],
                   "source_snapshot_ref": bundle["trusted_context"]["source_snapshot_ref"],
                   "task": bundle["task"], "reviewed_artifacts": artifacts,
                   "content_verification_ref": bundle.get("content_verification_ref"),
                   "content_hash": hashlib.sha256(dump(artifacts).encode()).hexdigest()}
        if bundle["task"]["quote_required"]:
            summary = quote_summary(bundle)
            request.update(quote_ref=summary["quote_ref"], quote_version=summary["quote_version"], validation_ref=bundle["quote_context"]["validation_ref"], purchase_plan_ref=summary["customer_purchase_plan"]["plan_ref"])
        return result(bundle, request)
    except (ValueError, TypeError, KeyError):
        return blocked("FINALIZE_REQUEST_INVALID")
'''

FINALIZE_RESPONSE = COMMON + r'''
def main(status_code: int, body: str, request_json: str) -> dict:
    try:
        data, state = response(status_code, body)
        request = strict_json(request_json)
        if state != "ready" or data.get("delivery_allowed") is not True or not opaque(data.get("artifact_manifest_ref")) or data.get("content_hash") != request["content_hash"]:
            return blocked("FINAL_DELIVERY_NOT_AUTHORIZED", state)
        if data.get("source_snapshot_ref") != request["source_snapshot_ref"]:
            return blocked("FINAL_SOURCE_SNAPSHOT_MISMATCH")
        # No model text ever goes directly to Answer. Final customer-facing
        # four-part content is reassembled by the authenticated finalizer.
        text = data.get("customer_text")
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            return blocked("FINALIZED_CUSTOMER_TEXT_REQUIRED")
        value = result()
        value["message"] = text
        return value
    except (ValueError, TypeError, KeyError):
        return blocked("FINALIZE_RESPONSE_INVALID")
'''


def full_code(node_id: str, title: str, code: str, variables: dict, x: int, y: int = 180) -> dict:
    compile(code, node_id, "exec")
    kinds = {"ready": "boolean", "payload_json": "string", "tool_json": "string", "route": "string",
             "quote_ref": "string", "quote_version": "string", "validation_ref": "string", "message": "string"}
    return BASE.node(node_id, "code", title, x, y, code_language="python3", code=code,
                     variables=[{"variable": k, "value_selector": v} for k, v in variables.items()],
                     outputs={k: {"type": v, "children": None} for k, v in kinds.items()})


def route_if(node_id: str, upstream: str, routes: list[str], x: int, y: int = 180) -> dict:
    return BASE.node(node_id, "if-else", "按已校验任务分支", x, y, cases=[
        {"case_id": route, "logical_operator": "and", "conditions": [
            {"variable_selector": [upstream, "route"], "comparison_operator": "is", "value": route}]}
        for route in routes])


def full_http(node_id: str, title: str, path: str, upstream: str, x: int, method="post", tool=True) -> dict:
    result = BASE.http_node(node_id, title, path, upstream, x, "scope_parse")
    result["data"]["method"] = method
    if method == "get":
        # Opaque identifiers are checked before interpolation. The HTTP request
        # contains no caller-supplied host/path. GET query uses controlled IDs.
        result["data"]["params"] = "quote_version:{{#quote_valid.quote_version#}}\npurpose_ref:{{#env.BUSINESS_PURPOSE_REF#}}\ndestination_ref:{{#env.BUSINESS_DESTINATION_REF#}}"
        result["data"]["body"] = {"type": "none", "data": []}
    elif tool:
        result["data"]["body"]["data"][0]["value"] = "{{#" + upstream + ".tool_json#}}"
    return result


class Graph:
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.types = {}
        self.error_sources = set()
        self.x = 0

    def add(self, item: dict) -> str:
        if item["id"] in self.types:
            raise ValueError("DUPLICATE_NODE_ID")
        self.nodes.append(item)
        self.types[item["id"]] = item["data"]["type"]
        if item["data"]["type"] == "http-request":
            # Non-2xx and transport exceptions have a known safe terminal path.
            # Graphon 0.7.0 NodeRunResult defaults to the ordinary source handle
            # on success; ErrorHandler explicitly emits fail-branch on failure.
            item["data"]["error_strategy"] = "fail-branch"
            item["data"]["retry_config"] = {"retry_enabled": False, "max_retries": 0, "retry_interval": 0}
            self.link(item["id"], "http_failure_answer", "fail-branch")
        return item["id"]

    def link(self, source: str, target: str, handle="source") -> None:
        self.edges.append(BASE.edge(source, target, self.types[source], self.types[target], handle))

    def gate(self, source: str, tag: str, x: int) -> str:
        check = self.add(BASE.if_node(tag + "_ok", source, x))
        self.link(source, check)
        self.error_sources.add(source)
        self.link(check, "error_aggregate", "false")
        return check

    def code(self, source: str, node_id: str, title: str, code: str, variables: dict, x: int, handle="source") -> str:
        self.add(full_code(node_id, title, code, variables, x))
        self.link(source, node_id, handle)
        return node_id

    def llm(self, source: str, node_id: str, role: str, prompts: dict, models: dict, bundle: str, x: int, handle="source") -> str:
        self.add(BASE.llm_node(node_id, role + " 候选", prompts[role], models[role], bundle, x))
        self.link(source, node_id, handle)
        return node_id

    def parse_review(self, source: str, role: str, kind: str, prompts: dict, models: dict, bundle: str, x: int, handle="source") -> tuple[str, str]:
        writer = self.llm(source, role, role, prompts, models, bundle, x, handle)
        parsed = self.code(writer, role + "_parse", "严格JSON/引用/SKU/方案绑定", parse_draft(kind), {"text": [writer, "text"], "bundle_json": [bundle, "payload_json"]}, x + 300)
        writer_ok = self.gate(parsed, role, x + 600)
        reviewer = self.llm(writer_ok, role + "_review", "fact_compliance_review", prompts, models, parsed, x + 900, "true")
        checked = self.code(reviewer, role + "_review_gate", "独立逐位置审核覆盖", REVIEW_GATE, {"text": [reviewer, "text"], "bundle_json": [parsed, "payload_json"]}, x + 1200)
        return checked, self.gate(checked, role + "_review", x + 1500)


def build_graph(prompts: dict, models: dict) -> dict:
    graph = Graph()
    graph.add(BASE.node("start", "start", "自然语言任务入口", 0, 180, variables=[]))
    graph.add(BASE.node("http_failure_answer", "answer", "HTTP失败安全收口；不展示Headers/正文", 900, 820,
                        answer="BLOCKED: HTTP_TRANSPORT_OR_RESPONSE_FAILED。业务工具请求未完成；未生成或放行成品。"))
    graph.add(BASE.node("error_aggregate", "variable-aggregator", "互斥失败消息收口；不汇总并行审核", 900, 640,
                        output_type="string", variables=[], advanced_settings={"group_enabled": False, "groups": []}))
    graph.add(BASE.node("error_answer", "answer", "展示当前确定性阻断原因", 1200, 640,
                        answer="{{#error_aggregate.output#}}"))
    graph.link("error_aggregate", "error_answer")
    graph.add(BASE.node("scene_parse", "llm", "自然语言场景与任务解析", 300, 180,
                        model=models["scene_parse"], prompt_template=[
                            {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "huawei/full/scene/system")), "role": "system", "text": prompts["scene_parse"]}],
                        # Graphon 0.7 appends memory.query_prompt_template after
                        # native history. Do not also put sys.query in a static
                        # USER message: native assembly does not deduplicate it.
                        context={"enabled": False, "variable_selector": []},
                        memory={"window": {"enabled": True, "size": 8}, "query_prompt_template": "{{#sys.query#}}"},
                        vision={"enabled": False},
                        structured_output_enabled=False, reasoning_format="separated"))
    graph.link("start", "scene_parse")
    graph.add(BASE.code_node("normalize", "任务完整性/正式报价双true", NORMALIZE, {"text": ["scene_parse", "text"]}, 600))
    graph.link("scene_parse", "normalize")
    normal_ok = graph.gate("normalize", "input", 900)
    graph.code(normal_ok, "preliminary_strategy", "检索前平台意图；不宣称产品能力", PRE_STRATEGY,
               {"request_json": ["normalize", "payload_json"]}, 1050, "true")
    preliminary_ok = graph.gate("preliminary_strategy", "preliminary_strategy", 1150)
    graph.add(BASE.http_node("scope", "身份/资料模式/用途范围", "/v1/contexts/resolve", "preliminary_strategy", 1200))
    graph.link(preliminary_ok, "scope", "true")
    graph.add(BASE.code_node("scope_parse", "验证资料proof；仅传HTTP", SCOPE, {"status_code": ["scope", "status_code"], "body": ["scope", "body"], "request_json": ["preliminary_strategy", "payload_json"]}, 1500))
    graph.link("scope", "scope_parse")
    scope_ok = graph.gate("scope_parse", "scope", 1800)
    graph.add(BASE.http_node("evidence", "指定库只读取证/冲突检查", "/v1/kb/evidence", "scope_parse", 2100, "scope_parse"))
    graph.link(scope_ok, "evidence", "true")
    expected = [{"node_id": role, "provider": model["provider"], "model": model["name"]} for role, model in models.items() if role != "scene_parse"]
    graph.code("evidence", "evidence_parse", "状态/快照/真实模型目的地/字段投影", EVIDENCE.replace("__EXPECTED__", repr(expected)), {"status_code": ["evidence", "status_code"], "body": ["evidence", "body"], "task_json": ["normalize", "payload_json"], "scope_ref": ["scope_parse", "scope_ref"]}, 2400)
    # Separate explicit information/source/conflict/denied branches. All are
    # safe terminal answers; none flows to a writer or solver on failure.
    evidence_ok = graph.gate("evidence_parse", "evidence", 2700)
    status_routes = graph.add(route_if("source_failure_routes", "evidence_parse", ["needs_input", "needs_source", "conflict", "denied", "error"], 3000, 700))
    # Replace the generic false edge with explicit status branches.
    graph.edges = [e for e in graph.edges if not (e["source"] == evidence_ok and e["sourceHandle"] == "false")]
    graph.link(evidence_ok, status_routes, "false")
    answer = graph.add(BASE.node("source_failure_answer", "answer", "信息/来源/冲突/权限缺口安全说明", 3300, 600,
                                answer="{{#evidence_parse.message#}}"))
    for state in ["needs_input", "needs_source", "conflict", "denied", "error"]:
        graph.link(status_routes, answer, state)
    graph.link(status_routes, "error_aggregate", "false")
    task_routes = graph.add(route_if("task_routes", "evidence_parse", ["product_intro", "marketing", "quote", "sales_script", "full_package"], 3000))
    graph.link(evidence_ok, task_routes, "true")
    unknown = graph.add(BASE.node("task_route_unknown", "answer", "不降级正式任务", 3300, 500, answer="BLOCKED: TASK_ROUTE_UNKNOWN"))
    graph.link(task_routes, unknown, "false")

    intro, intro_ok = graph.parse_review(task_routes, "product_intro", "product_intro", prompts, models, "evidence_parse", 3300, "product_intro")
    add_finalization(graph, intro_ok, intro, "intro", 5300, quoted=False)

    # Only an explicit marketing/content_only bypasses pricing. It remains a
    # marketing task, with the same strategy, images, review and visual gates.
    graph.code(task_routes, "marketing_scope", "显式无价营销与完整购买方案互斥", MARKETING_SCOPE,
               {"bundle_json": ["evidence_parse", "payload_json"]}, 3150, "marketing")
    marketing_scope_ok = graph.gate("marketing_scope", "marketing_scope", 3225)
    delivery_routes = graph.add(route_if("marketing_delivery_routes", "marketing_scope", ["content_only", "complete_package"], 3300, 400))
    graph.link(marketing_scope_ok, delivery_routes, "true")
    graph.link(delivery_routes, "task_route_unknown", "false")
    graph.code(delivery_routes, "content_only_input", "无价图文输入；禁止价格与旧产物", CONTENT_ONLY_INPUT,
               {"bundle_json": ["marketing_scope", "payload_json"]}, 3500, "content_only")
    content_only_ok = graph.gate("content_only_input", "content_only_input", 3750)

    # Complete packages, quote-only and sales-script tasks still require
    # deterministic pricing. A source/pricing failure cannot enter no-price.
    graph.add(full_http("quote_solve", "单SKU四级合法组合/固定顾客资源现金最低", "/v1/quotes/solve", "evidence_parse", 3300))
    for route in ("quote", "sales_script", "full_package"):
        graph.link(task_routes, "quote_solve", route)
    graph.link(delivery_routes, "quote_solve", "complete_package")
    graph.code("quote_solve", "quote_pending", "只接待独立复算候选", SOLVE,
               {"status_code": ["quote_solve", "status_code"], "body": ["quote_solve", "body"], "bundle_json": ["evidence_parse", "payload_json"], "request_json": ["evidence_parse", "tool_json"]}, 3600)
    solve_ok = graph.gate("quote_pending", "quote_pending", 3900)
    graph.add(full_http("quote_validate", "独立复算与严格最优/有效性验证", "/v1/quotes/{{#quote_pending.quote_ref#}}/validate", "quote_pending", 4200))
    graph.link(solve_ok, "quote_validate", "true")
    graph.code("quote_validate", "quote_valid", "未VALID_OPTIMAL不取摘要", VALIDATE,
               {"status_code": ["quote_validate", "status_code"], "body": ["quote_validate", "body"], "bundle_json": ["quote_pending", "payload_json"], "quote_ref": ["quote_pending", "quote_ref"], "quote_version": ["quote_pending", "quote_version"], "request_json": ["quote_pending", "tool_json"]}, 4500)
    valid_ok = graph.gate("quote_valid", "quote_valid", 4800)
    graph.add(full_http("client_view", "本次目的地白名单客户摘要与购买计划", "/v1/quotes/{{#quote_valid.quote_ref#}}/client-view", "quote_valid", 5100, method="get"))
    graph.link(valid_ok, "client_view", "true")
    graph.code("client_view", "client_quote", "四级完整/组合对比/同资源/方案版本", CLIENT_VIEW,
               {"status_code": ["client_view", "status_code"], "body": ["client_view", "body"], "bundle_json": ["quote_valid", "payload_json"], "quote_ref": ["quote_valid", "quote_ref"], "quote_version": ["quote_valid", "quote_version"], "validation_ref": ["quote_valid", "validation_ref"]}, 5400)
    client_ok = graph.gate("client_quote", "client_quote", 5700)
    explained, explanation_ok = graph.parse_review(client_ok, "quote_explain", "quote_explanation", prompts, models, "client_quote", 6000, "true")
    post_quote = graph.add(route_if("priced_task_routes", "client_quote", ["marketing", "full_package", "sales_script", "quote"], 7900))
    graph.link(explanation_ok, post_quote, "true")
    graph.link(post_quote, "task_route_unknown", "false")

    # Quote-only and sales-script share no visual branch. Optional script on a
    # quote task is handled explicitly by this Code-derived boolean route.
    choose_script = COMMON + r'''
def main(bundle_json: str) -> dict:
    try:
        bundle = strict_json(bundle_json)
        return result(bundle, route="script" if bundle["task"]["script_required"] else "no_script")
    except (ValueError, TypeError, KeyError):
        return blocked("SCRIPT_FLAG_INVALID")
'''
    graph.add(full_code("quote_script_choice", "需要脚本才进入；不暗省", choose_script, {"bundle_json": [explained, "payload_json"]}, 8200))
    graph.link(post_quote, "quote_script_choice", "quote")
    graph.link(post_quote, "quote_script_choice", "sales_script")
    script_choice = graph.add(route_if("script_choice", "quote_script_choice", ["script", "no_script"], 8500))
    graph.link("quote_script_choice", script_choice)
    graph.link(script_choice, "task_route_unknown", "false")
    add_finalization(graph, script_choice, "quote_script_choice", "quote_only", 8800, quoted=True, handle="no_script")
    graph.code(script_choice, "script_request", "服务绑定演示动作/产品/报价输入", SCRIPT_REQUEST, {"bundle_json": ["quote_script_choice", "payload_json"], "script_request_json": ["client_quote", "tool_json"]}, 8800, "script")
    script_request_ok = graph.gate("script_request", "script_request", 9100)
    graph.add(full_http("script_input", "组装获准脚本最小输入", "/v1/quotes/{{#script_request.quote_ref#}}/script-input", "script_request", 9400))
    graph.link(script_request_ok, "script_input", "true")
    graph.code("script_input", "script_input_parse", "核对当前产品/动作/同报价引用", SCRIPT_INPUT, {"status_code": ["script_input", "status_code"], "body": ["script_input", "body"], "bundle_json": ["script_request", "payload_json"]}, 9700)
    script_input_ok = graph.gate("script_input_parse", "script_input", 10000)
    script, script_ok = graph.parse_review(script_input_ok, "sales_demo", "sales_script", prompts, models, "script_input_parse", 10300, "true")
    add_finalization(graph, script_ok, script, "script", 12300, quoted=True)

    # These success inputs are mutually exclusive at runtime. Unlike the
    # failure aggregator this is a success bundle join, not evidence that
    # parallel checks completed. Re-parse and enforce the task/quote contract.
    graph.add(BASE.node("marketing_bundle", "variable-aggregator", "互斥定价/无价营销输入合流", 7900, 400,
                        output_type="string", variables=[[explained, "payload_json"], ["content_only_input", "payload_json"]],
                        advanced_settings={"group_enabled": False, "groups": []}))
    graph.link(content_only_ok, "marketing_bundle", "true")
    graph.link(post_quote, "marketing_bundle", "marketing")
    graph.link(post_quote, "marketing_bundle", "full_package")
    graph.code("marketing_bundle", "marketing_input", "恢复营销DTO；完整任务仍须有效报价", MARKETING_INPUT,
               {"selected_json": ["marketing_bundle", "output"]}, 8000)
    marketing_input_ok = graph.gate("marketing_input", "marketing_input", 8100)
    strategy_llm = graph.llm(marketing_input_ok, "platform_strategy", "platform_strategy", prompts, models, "marketing_input", 8200, "true")
    graph.code(strategy_llm, "strategy_parse", "平台/场景策略引用检查", STRATEGY, {"text": [strategy_llm, "text"], "bundle_json": ["marketing_input", "payload_json"]}, 8500)
    strategy_ok = graph.gate("strategy_parse", "strategy", 8800)
    channels = graph.add(route_if("channel_routes", "strategy_parse", ["store_poster", "wechat_article", "xiaohongshu", "moments"], 9100))
    graph.link(strategy_ok, channels, "true")
    graph.link(channels, "task_route_unknown", "false")
    for role, kind, route in (("poster_copy", "poster", "store_poster"), ("article_write", "article", "wechat_article")):
        checked, checked_ok = graph.parse_review(channels, role, kind, prompts, models, "strategy_parse", 9400, route)
        if role == "article_write":
            for extra in ("xiaohongshu", "moments"):
                graph.link(channels, role, extra)
        layout = graph.llm(checked_ok, role + "_layout", "visual_layout", prompts, models, checked, 11300, "true")
        parsed = graph.code(layout, role + "_layout_parse", "布局候选；无像素不伪装视觉核验", LAYOUT, {"text": [layout, "text"], "bundle_json": [checked, "payload_json"]}, 11600)
        layout_ok = graph.gate(parsed, role + "_layout", 11900)
        if kind == "poster":
            graph.add(full_http("poster_render", "知识库原图+受限确定性PNG渲染", "/v1/renders/poster", parsed, 12200))
            graph.link(layout_ok, "poster_render", "true")
            rendered = graph.code("poster_render", "poster_visual_adapter", "未接真实File像素则阻断", RENDER, {"status_code": ["poster_render", "status_code"], "body": ["poster_render", "body"], "bundle_json": [parsed, "payload_json"]}, 12500)
            graph.error_sources.add(rendered)
            graph.link(rendered, "error_aggregate")
        else:
            # LAYOUT always fails closed for an article: no success edge may
            # accidentally bypass visual requirements after a future change.
            stop = graph.add(BASE.node("article_visual_unimplemented", "answer", "图文视觉路径尚未实现", 12200, 180, answer="BLOCKED: ARTICLE_VISUAL_INPUT_ADAPTER_NOT_IMPLEMENTED"))
            graph.link(layout_ok, stop, "true")
    value = {"nodes": graph.nodes, "edges": graph.edges, "viewport": {"x": 0, "y": 0, "zoom": 0.1}}
    # A run has only one active serial branch. On its first failed gate, all
    # later nodes are skipped. Select message variables in reverse topological
    # order, so the current failed node precedes earlier successful messages.
    # This is NOT a join or a proof that concurrent checks all completed.
    selectors = [[node_id, "message"] for node_id in reversed(topological_order(value)) if node_id in graph.error_sources]
    next(n for n in graph.nodes if n["id"] == "error_aggregate")["data"]["variables"] = selectors
    validate_graph(value)
    return value


def add_finalization(graph: Graph, source: str, bundle: str, prefix: str, x: int, quoted: bool, handle="true") -> None:
    """No raw model output is ever connected directly to an Answer."""
    if quoted:
        request = graph.code(source, prefix + "_verify_request", "冻结已审核产物/完整必需项", VERIFY_REQUEST, {"bundle_json": [bundle, "payload_json"]}, x, handle)
        request_ok = graph.gate(request, prefix + "_verify_request", x + 300)
        http = prefix + "_verify_content"
        graph.add(full_http(http, "金额/条件/范围/保密服务再核验", "/v1/quotes/{{#" + request + ".quote_ref#}}/verify-content", request, x + 600))
        graph.link(request_ok, http, "true")
        parsed = graph.code(http, prefix + "_verify_result", "服务器检查必须绑定当前内容hash", VERIFY_RESPONSE, {"status_code": [http, "status_code"], "body": [http, "body"], "bundle_json": [request, "payload_json"], "request_json": [request, "tool_json"]}, x + 900)
        source = graph.gate(parsed, prefix + "_verify", x + 1200)
        bundle, handle, x = parsed, "true", x + 1500
    request = graph.code(source, prefix + "_finalize_request", "最终来源/依赖/用途交付门禁", FINALIZE_REQUEST, {"bundle_json": [bundle, "payload_json"]}, x, handle)
    request_ok = graph.gate(request, prefix + "_finalize_request", x + 300)
    http = prefix + "_finalize"
    graph.add(full_http(http, "服务原子确认与四部分交付组装", "/v1/artifacts/finalize", request, x + 600))
    graph.link(request_ok, http, "true")
    parsed = graph.code(http, prefix + "_finalized", "仅展示真实授权成品", FINALIZE_RESPONSE, {"status_code": [http, "status_code"], "body": [http, "body"], "request_json": [request, "tool_json"]}, x + 900)
    graph.add(BASE.node(prefix + "_answer", "answer", "仅服务核准的四部分结果", x + 1200, 180, answer="{{#" + parsed + ".message#}}"))
    graph.link(parsed, prefix + "_answer")


def topological_order(graph: dict) -> list[str]:
    nodes = {n["id"]: n for n in graph["nodes"]}
    adjacency = {key: [] for key in nodes}
    incoming = {key: 0 for key in nodes}
    for edge in graph["edges"]:
        adjacency[edge["source"]].append(edge["target"])
        incoming[edge["target"]] += 1
    pending = [key for key, count in incoming.items() if count == 0]
    ordered = []
    while pending:
        here = pending.pop()
        ordered.append(here)
        for target in adjacency[here]:
            incoming[target] -= 1
            if incoming[target] == 0:
                pending.append(target)
    if len(ordered) != len(nodes):
        raise ValueError("CYCLE_DETECTED")
    return ordered


def validate_graph(graph: dict) -> None:
    nodes = {n["id"]: n for n in graph["nodes"]}
    if len(nodes) != len(graph["nodes"]) or any(n["data"]["type"] not in ALLOWED_NODE_TYPES for n in nodes.values()):
        raise ValueError("DUPLICATE_OR_UNVERIFIED_NODE_TYPE")
    for edge in graph["edges"]:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("DANGLING_EDGE")
        if nodes[edge["source"]]["data"]["type"] == "llm" and nodes[edge["target"]]["data"]["type"] == "answer":
            raise ValueError("RAW_LLM_TO_ANSWER_FORBIDDEN")
        source_data = nodes[edge["source"]]["data"]
        if source_data["type"] == "if-else" and edge.get("sourceHandle") not in {"false"} | {case["case_id"] for case in source_data.get("cases", [])}:
            raise ValueError("INVALID_CASE_HANDLE")
        if source_data["type"] == "http-request" and source_data.get("error_strategy") == "fail-branch" and edge.get("sourceHandle") not in {"source", "fail-branch"}:
            raise ValueError("INVALID_HTTP_FAIL_BRANCH_HANDLE")
    adjacency = {key: [] for key in nodes}
    for edge in graph["edges"]:
        adjacency[edge["source"]].append(edge["target"])
    visited, pending = set(), ["start"]
    while pending:
        here = pending.pop()
        if here in visited:
            continue
        visited.add(here)
        pending.extend(adjacency[here])
    if visited != set(nodes):
        raise ValueError("UNREACHABLE_NODE")
    # Acyclic control flow and no bare non-answer terminals are local checks.
    topological_order(graph)
    if any(not targets and nodes[key]["data"]["type"] != "answer" for key, targets in adjacency.items()):
        raise ValueError("NON_ANSWER_TERMINAL")
    validate_selectors(graph)


def validate_selectors(graph: dict) -> None:
    """Check declared outputs and control ancestors; not a Dify runtime test."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    parents = {key: set() for key in nodes}
    for edge in graph["edges"]:
        parents[edge["target"]].add(edge["source"])
    ancestors = {}
    for node_id in topological_order(graph):
        ancestors[node_id] = set(parents[node_id])
        for parent in parents[node_id]:
            ancestors[node_id].update(ancestors[parent])
    outputs = {}
    for node_id, item in nodes.items():
        data = item["data"]
        kind = data["type"]
        fixed = {
            "http-request": {"status_code", "body", "headers", "files"},
            "llm": {"text", "usage", "finish_reason", "structured_output", "reasoning_content"},
            "if-else": {"result", "selected_case_id"}, "variable-aggregator": {"output"},
            "answer": set(),
        }
        if kind == "start":
            outputs[node_id] = {v["variable"] for v in data.get("variables", [])}
        elif kind == "code":
            outputs[node_id] = set(data.get("outputs", {}))
        else:
            outputs[node_id] = fixed[kind]

    def check(selector, consumer):
        if not isinstance(selector, (tuple, list)) or len(selector) < 2:
            raise ValueError("INVALID_VARIABLE_SELECTOR")
        owner, field = selector[:2]
        if owner == "env":
            if field not in {"BUSINESS_SERVICE_BASE", "BUSINESS_SERVICE_TOKEN", "BUSINESS_PURPOSE_REF", "BUSINESS_DESTINATION_REF"}:
                raise ValueError("UNDECLARED_ENV_SELECTOR")
            return
        if owner == "sys":
            if field not in {"query", "files"}:
                raise ValueError("UNEXPECTED_SYSTEM_SELECTOR")
            return
        if owner not in outputs or field not in outputs[owner] or owner not in ancestors[consumer]:
            raise ValueError("UNKNOWN_OR_NON_UPSTREAM_SELECTOR: " + consumer + ":" + ".".join(selector))

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    for node_id, item in nodes.items():
        data = item["data"]
        kind = data["type"]
        if kind == "code":
            for variable in data["variables"]:
                check(variable["value_selector"], node_id)
        if kind == "if-else":
            for case in data.get("cases", []):
                for condition in case["conditions"]:
                    check(condition["variable_selector"], node_id)
        if kind == "variable-aggregator":
            for selector in data["variables"]:
                check(selector, node_id)
        for text in strings(data):
            for match in re.finditer(r"\{\{#([^#{}]+)#\}\}", text):
                check(match.group(1).split("."), node_id)


def status_manifest() -> dict:
    return {"schema_version": "1.0", "dify_version": BASE.DIFY_VERSION, "dsl_version": BASE.DSL_VERSION,
            "status": "PREPARATION_ONLY", "full_application_ready": False,
            "import_status": "IMPORT_NOT_RUN", "runtime_status": "NOT_RUN", "upstream_schema_execution": "PASSED_OFFLINE_NODE_DTO_ONLY",
            "upstream_schema_review": {
                "dify_commit": "8387590ace4a094de812b7847fc6a4c3a27cd52b",
                "graphon_version": "0.7.0",
                "locked_wheel_sha256": "6f7608aaaa65607c4935735137ed4b7029b1e6ca80202cbe829af3370cf4404e",
                "actual_checks": ["NodeConfigDictAdapter plus concrete Pydantic DTO for every full candidate node", "StringVariable and SecretVariable accept empty import values", "actual upstream VariableAggregatorNode._run on 29 serial failure pools", "actual upstream CodeNode.transform_result on 33 negative-path output dictionaries"],
                "http_runtime_handles": {"success": "source", "failure": "fail-branch"},
                "not_checked": ["Dify application DSL import/persistence", "provider/plugin availability", "Dify canvas layout and UI", "live graph traversal", "live HTTP/model/vision execution"],
                "source_urls": ["https://github.com/langgenius/dify/blob/8387590ace4a094de812b7847fc6a4c3a27cd52b/api/uv.lock", "https://github.com/langgenius/dify/blob/8387590ace4a094de812b7847fc6a4c3a27cd52b/api/constants/dsl_version.py", "https://files.pythonhosted.org/packages/9c/9b/3b02d944a20b3693bb5bb77cbb16b3afed44a965096970c47625560c0235/graphon-0.7.0-py3-none-any.whl"]},
            "connected_candidate_paths": [
                "natural query -> scene_parse -> deterministic task flags -> preliminary platform/retrieval intention (no product claims) -> scope/proof -> evidence/status branches",
                "explicit product_intro -> product writer -> independent review -> authenticated finalize -> Answer",
                "default complete-package marketing/full_package and quote/script -> exact single-SKU solve -> independent validate -> purpose-scoped client-view -> purchase-plan guard -> quote explanation -> independent review",
                "explicit marketing/content_only -> no-price marketing DTO -> mutually exclusive bundle join (no quote_solve) -> evidence-based platform strategy",
                "quote -> optional script; sales_script -> service script-input -> six-segment writer -> independent review -> verify-content -> finalize -> Answer",
                "marketing/full_package -> platform strategy -> article/poster independent writer -> independent review -> layout",
                "poster -> deterministic renderer -> explicit unimplemented vision-file adapter block",
                "article -> explicit unimplemented article pixel/vision adapter block"],
            "not_connected": ["actual Dify File pixels to an approved visual_review model", "verified article-page renderer and visual review", "multi-SKU per-item scheduling/complete comparison aggregate", "marketing/full_package post-visual script and final merge", "finite revision-and-recheck loops"],
            "current_service_limits": ["local facts/scoped proof paths exist separately and need actual Dify binding", "pricing deliberately returns FOUR_LEVELS_PENDING without verified executable rules", "validate/client-view/script-input/verify-content/finalize/render adapters are contract candidates and not implemented by the current bridge", "ima_live/hybrid source adapters are not implemented", "multi-store trusted user authorization is not implemented"],
            "error_route_design": "Single mutually exclusive failure aggregator in reverse topological order; shared safe HTTP failure Answer. Separate marketing success aggregator joins mutually exclusive priced/content-only inputs and revalidates the DTO; neither aggregator proves parallel checks completed.",
            "delivery_scope_policy": {"default": "complete_package", "explicit_content_only_task": "marketing", "no_automatic_source_failure_downgrade": True, "content_only_skips": ["quote_solve", "quote_validate", "client_view", "quote_explain"], "content_only_retains": ["platform_strategy", "article_or_poster", "image_requirements", "independent_review", "layout", "visual_and_final_delivery_gates"]},
            "customer_purchase_plan_contract": "quote_context.customer_quote_summary.customer_purchase_plan; service-generated only",
            "objective_metric": "min_cash_due_now_given_verified_customer_resources",
            "no_success_claim": "Offline graph/code checks and synthetic contracts do not establish Dify import, real model collaboration, quote accuracy, PNG export, source eligibility, or a finished Agent."}


def create_bundle(out: Path, config: dict, plan_only=False) -> None:
    BASE.reject_credentials(config)
    if out.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    if set(config) - {"models", "dependencies", "note"}:
        raise ValueError("UNEXPECTED_CONFIG_KEY")
    prompts, hashes = {}, {}
    for role, filename in BASE.PROMPT_FILES.items():
        raw = (ROOT / "prompts" / filename).read_bytes()
        prompts[role] = raw.decode("utf-8")
        hashes[filename] = {"sha256": BASE.sha256(raw), "bytes": len(raw)}
    dependencies = config.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("DEPENDENCIES_MUST_MATCH_REAL_DIFY_EXPORT")
    models = None
    if not plan_only:
        models = {role: BASE.model_binding(config, slot) for role, slot in MODEL_SLOTS.items()}
        if (models["article_write"]["provider"], models["article_write"]["name"]) == (models["fact_compliance_review"]["provider"], models["fact_compliance_review"]["name"]):
            raise ValueError("DISTINCT_WRITE_REVIEW_BINDINGS_REQUIRED")
    manifest = status_manifest()
    manifest.update(prompts=hashes, status="PREPARATION_ONLY" if plan_only else "IMPORT_CANDIDATE_WITH_EXPLICIT_GAPS")
    graph = build_graph(prompts, models) if models else None
    if graph:
        manifest["node_count"] = len(graph["nodes"])
        manifest["edge_count"] = len(graph["edges"])
    BASE.write_new(out / "manifest.json", BASE.json_text(manifest))
    BASE.write_new(out / "model-bindings.example.json", BASE.json_text({"models": {slot: {"provider": "", "name": "", "completion_params": {}} for slot in sorted(set(MODEL_SLOTS.values()))}, "dependencies": [], "note": "Only registered actual provider/model IDs. The same actual provider/model may fill multiple roles, except writer and independent reviewer must differ. Credentials stay in Dify Secret settings. No vision slot is falsely advertised as connected."}))
    for role, filename in BASE.PROMPT_FILES.items():
        BASE.write_new(out / "prompts" / filename, prompts[role])
    if graph:
        dsl = {"kind": "app", "version": BASE.DSL_VERSION,
               "app": {"name": "华为PC 场景与购买方案完整路由候选（含明确缺口）", "description": "IMPORT_NOT_RUN；正式营销受报价/真实资产/视觉工具门禁阻断，不是已完成Agent。", "mode": "advanced-chat", "icon": "💻", "icon_type": "emoji", "icon_background": "#FFFFFF", "use_icon_as_answer_icon": False},
               "dependencies": dependencies,
               "workflow": {"graph": graph, "conversation_variables": [], "environment_variables": [
                   {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "huawei/full/" + name)), "name": name, "value_type": kind, "value": "", "description": description}
                   for name, kind, description in [("BUSINESS_SERVICE_BASE", "string", "已核准服务地址，无/v1尾缀"), ("BUSINESS_SERVICE_TOKEN", "secret", "本机服务凭证；不可放普通变量或模型输入"), ("BUSINESS_PURPOSE_REF", "string", "与服务受控配置一致的用途ref；ref不是授权"), ("BUSINESS_DESTINATION_REF", "string", "与服务受控配置一致的目的地ref；ref不是授权")]],
                            "features": {"file_upload": {"enabled": False}, "opening_statement": "开发候选：说明人群、场景、产品/需求与发布平台。默认完整营销含经服务核验的四级购买方案；可明确仅做营销图文、不报价，仍须满足图片与核验要求。", "retriever_resource": {"enabled": False}, "sensitive_word_avoidance": {"enabled": False}, "speech_to_text": {"enabled": False}, "suggested_questions": [], "suggested_questions_after_answer": {"enabled": False}, "text_to_speech": {"enabled": False}}}}
        BASE.write_new(out / "full-workflow.candidate.yml", BASE.json_text(dsl))
    BASE.write_new(out / "README.md", "# 完整路由候选准备包\n\nIMPORT_NOT_RUN / runtime NOT_RUN。此包没有部署、调用模型或取得真实报价。\n\n"
                   "scene_parse消费自然语言，代码对默认complete_package的marketing/full_package固定quote_required与purchase_plan_required双true；显式marketing/content_only保持marketing且双false、无销售平台必填，不经过quote_solve。两路互斥合流后仍执行相同平台策略、文章/海报、图片、独立审核和视觉/最终交付门禁。来源或报价失败不自动切换无价路由，产品介绍仍是独立明确任务。\n\n"
                   "检索前有确定性平台/场景意图，只描述任务、格式与查证目标，不断言产品能力；检索后LLM仍依据事实生成并冻结平台策略。新增路由与变量合流需目标Dify重新导入/保存和真实遍历验收，离线检查不证明已部署。\n\n"
                   "System逐字复制prompts并记录hash。只有已在目标Dify登记的真实provider/model绑定才生成候选DSL；文本与独立审核实际身份必须不同。JSON表示采用合法YAML；依赖插件清单须来自目标实例真实导出。\n\n"
                   "完整路由连接了正式报价/购买方案和文章/海报独立候选，但当前服务尚未实现定价/复算/摘要/渲染/最终交付。多SKU调度与真实File视觉接线明确阻断，marketing/full_package后视觉脚本/合流尚未连接；不能称完整可用应用。\n\n"
                   "quote_request、script_request、comparison_coverage及finalize返回字段是本构建器提出的具体适配合同，须与受认证业务服务共同实现并实测。报价/授权/规则/最优性不交给LLM。HTTP成功、模型ready、VALID_OPTIMAL字符串都不足以越过其他门禁。\n\n"
                   "请先实现服务Schema与受限字段投影，再在Dify真实导入、配置Secret/实际模型、检查节点变量及所有失败分支，最后运行验收。此包不替代最短产品介绍链，也不包含真实秘密或知识库原文。\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
        if not isinstance(config, dict):
            raise ValueError("CONFIG_OBJECT_REQUIRED")
        create_bundle(args.out.resolve(), config, args.plan_only)
        print(BASE.json_text({"status": "PREPARATION_ONLY" if args.plan_only else "IMPORT_CANDIDATE_WITH_EXPLICIT_GAPS", "import_status": "IMPORT_NOT_RUN", "runtime_status": "NOT_RUN", "out": str(args.out.resolve())}))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print("BUILD_BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

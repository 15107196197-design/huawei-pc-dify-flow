"""Synthetic-only deterministic kernel tests; none is a Huawei offer or price.

No production source, customer account, provider key or business data is used.
Passing these tests does not enable real_quote or measure real quote accuracy.
"""

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from services.quote_engine import (
    CandidateManifest, ChoiceGroup, Eligibility, Evidence, Fee, LevelEvidence,
    OldAsset, QuoteContext, QuoteEngine, Resource, ResourceSnapshot, RuleSet,
    SalesOption,
)


AT = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
START, END = AT - timedelta(days=1), AT + timedelta(days=1)
EVIDENCE = ("synthetic-evidence-only",)


def option(rule_id, operation, value=None, **kwargs):
    kind = {"set_base": "base_price", "noop": "no_adjustment",
            "fixed_discount": "sales_discount", "rate_discount": "identity_benefit"}.get(operation, "unsupported")
    return SalesOption(rule_id=rule_id, operation=operation, value=value,
                       evidence_refs=EVIDENCE, customer_reason="Synthetic rule: " + rule_id,
                       benefit_kind=kwargs.pop("benefit_kind", kind), **kwargs)


def fixture():
    """Arbitrary finite arithmetic fixture; never copy these values into a KB."""
    ctx = QuoteContext(tenant_ref="synthetic-tenant", store_ref="synthetic-store-ref",
                       actor_ref="synthetic-operator", customer_ref="synthetic-customer", product_ref="synthetic-sku",
                       configuration_ref="synthetic-config", quantity=1, currency="CNY",
                       sales_platform="synthetic-store", region="synthetic-region", as_of=AT,
                       rule_timezone="Asia/Shanghai", source_mode="synthetic_test",
                       recommendation_set_ref="synthetic-recommendations", recommendation_set_version="1")
    levels = tuple(LevelEvidence(level_id, display, "applicable", EVIDENCE, "Synthetic applicability")
                   for level_id, display in (
                       ("base_price", "基准价"), ("platform_discount", "平台优惠"),
                       ("identity_benefit", "身份权益"), ("trade_in_national_subsidy", "换新国补")))
    groups = (
        ChoiceGroup("base", "base_price", (option("base-100k", "set_base", 100000),)),
        ChoiceGroup("coupon", "platform_discount", (option("no-coupon", "noop"),
                    option("coupon-10k", "fixed_discount", 10000))),
        ChoiceGroup("identity", "identity_benefit", (option("no-identity", "noop"),
                    option("identity-10pct", "rate_discount", "0.10", cap_minor=8000,
                           rounding_mode="ROUND_HALF_UP", eligibility_refs=("synthetic-student",)))),
        ChoiceGroup("trade", "trade_in_national_subsidy", (option("no-extra-trade-discount", "noop"),)),
    )
    resources = (
        Resource(resource_ref="synthetic-trade-voucher", resource_kind="trade_in_voucher",
                 unit="minor_currency", balance_units=15000, permitted_max_units=15000,
                 increment_units=5000, unit_value_minor="1", rounding_mode="ROUND_DOWN",
                 evidence_refs=EVIDENCE, allocation_order="goods_then_fees",
                 verification_state="verified", availability="available"),
        Resource(resource_ref="synthetic-points", resource_kind="points", unit="points",
                 balance_units=3000, permitted_max_units=3000, increment_units=1000,
                 unit_value_minor="1", rounding_mode="ROUND_DOWN", evidence_refs=EVIDENCE,
                 allocation_order="goods_then_fees", verification_state="verified",
                 availability="available", cap_rate_decimal="0.30"),
    )
    manifest = CandidateManifest("synthetic-complete-manifest", True,
                                 tuple((g.group_id, tuple(o.rule_id for o in g.options)) for g in groups),
                                 tuple(r.resource_ref for r in resources), EVIDENCE)
    rules = RuleSet(rule_set_ref="synthetic-rules-only", version="1", publication_status="synthetic_fixture",
                    approval_ref="synthetic-test-approval-not-business-authorization",
                    tenant_ref=ctx.tenant_ref, store_ref=ctx.store_ref,
                    product_ref=ctx.product_ref, configuration_ref=ctx.configuration_ref,
                    sales_platform=ctx.sales_platform, region=ctx.region, currency=ctx.currency,
                    quantity=ctx.quantity, valid_from=START, valid_until=END, rule_timezone=ctx.rule_timezone,
                    levels=levels, groups=groups, calculation_order=tuple(g.group_id for g in groups),
                    calculation_order_evidence_refs=EVIDENCE,
                    payment_order=tuple(r.resource_ref for r in resources), payment_order_evidence_refs=EVIDENCE,
                    fees=(Fee("synthetic-required-fee", "fixed", 1000, EVIDENCE, "Synthetic fee"),),
                    fee_coverage_complete=True, fee_coverage_evidence_refs=EVIDENCE, manifest=manifest,
                    evidence=(Evidence(EVIDENCE[0], "synthetic_fixture", "verified", START, END),))
    snapshot = ResourceSnapshot(snapshot_ref="synthetic-resource-snapshot", version="1",
                                customer_ref=ctx.customer_ref, verification_state="verified",
                                tenant_ref=ctx.tenant_ref,
                                resource_use_scope_ref="synthetic-permitted-use", use_scope_confirmed=True,
                                valid_from=START, valid_until=END, resources=resources,
                                old_assets=(OldAsset("synthetic-old-asset", 15000, "inspected_final",
                                                     "issued_available", resources[0].resource_ref, EVIDENCE),),
                                eligibility=(Eligibility("synthetic-student", "verified", EVIDENCE),),
                                evidence_refs=EVIDENCE)
    return ctx, rules, snapshot


def regroup(rules, groups):
    return replace(rules, groups=tuple(groups), calculation_order=tuple(g.group_id for g in groups),
                   manifest=replace(rules.manifest,
                                    group_option_ids=tuple((g.group_id, tuple(o.rule_id for o in g.options))
                                                           for g in groups)))


def reresc(rules, snapshot, resources, *, old_assets=None):
    resources = tuple(resources)
    return (replace(rules, payment_order=tuple(r.resource_ref for r in resources),
                    manifest=replace(rules.manifest, resource_refs=tuple(r.resource_ref for r in resources))),
            replace(snapshot, resources=resources,
                    old_assets=snapshot.old_assets if old_assets is None else tuple(old_assets)))


class QuoteEngineTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.rules, self.snapshot = fixture()
        self.engine = QuoteEngine(synthetic_test=True)

    def solve(self, ctx=None, rules=None, snapshot=None, engine=None):
        return (engine or self.engine).solve(ctx or self.ctx, rules or self.rules, snapshot or self.snapshot)

    def assert_blocked(self, reason, **kwargs):
        result = self.solve(**kwargs)
        self.assertEqual(result.reason, reason)
        self.assertIsNone(result.internal_quote)
        self.assertFalse(result.safe_status()["real_quote_enabled"])
        return result

    def test_complete_enumeration_cash_ledger_and_recovery_not_double_deducted(self):
        result = self.solve()
        self.assertEqual(result.reason, "PENDING_INDEPENDENT_VALIDATION")
        q = result.internal_quote
        self.assertEqual(q["coverage"]["expected_candidates"], 64)
        self.assertEqual(q["coverage"]["evaluated_candidates"], 64)
        best = q["optimal_candidates"][0]
        self.assertEqual(best["merchandise_total_minor"], 82000)
        self.assertEqual(best["mandatory_fees_minor"], 1000)
        self.assertEqual(best["order_total_before_payment_minor"], 83000)
        self.assertEqual(best["credits_applied_minor"], 18000)
        self.assertEqual(best["cash_due_now_minor"], 65000)
        self.assertEqual(best["customer_payable_minor"], best["cash_due_now_minor"])
        self.assertEqual(q["customer_old_asset_summary"][0]["inspected_final_value_minor"], 15000)
        self.assertEqual(len(q["four_level_rows"]), 4)
        self.assertFalse(q["coverage"]["cross_sku_comparison_complete"])
        self.assertEqual(self.engine.validate(result, self.ctx, self.rules, self.snapshot).validation_state, "PASS")

    def test_safe_status_never_releases_synthetic_quote_or_internal_rules(self):
        validated = self.engine.validate(self.solve(), self.ctx, self.rules, self.snapshot)
        self.assertEqual(validated.validation_state, "PASS")
        self.assertEqual(validated.reason, "SYNTHETIC_TEST_ONLY")
        safe = validated.safe_status()
        self.assertEqual(safe["quote_status"], "FEASIBLE_NOT_PROVEN")
        self.assertIsNone(safe["customer_quote_summary"])
        self.assertFalse(safe["client_quote_allowed"])
        self.assertFalse(safe["real_quote_enabled"])
        self.assertNotIn("synthetic-rules-only", str(safe))

    def test_unknown_or_template_publication_and_external_candidate_cannot_execute(self):
        for state in ["unverified", "draft", "pending_kb_ingestion", "v0.1_empty_template", "approved"]:
            with self.subTest(state=state):
                self.assert_blocked("RULES_NOT_APPROVED", rules=replace(self.rules, publication_status=state))

    def test_synthetic_data_cannot_enter_non_test_engine(self):
        self.assert_blocked("SYNTHETIC_MODE_MISMATCH", engine=QuoteEngine())
        self.assert_blocked("SYNTHETIC_MODE_MISMATCH", ctx=replace(self.ctx, source_mode="ima_live"))

    def test_kernel_accepts_only_explicit_internal_typed_structures(self):
        self.assert_blocked("INTERNAL_TYPED_INPUT_REQUIRED", ctx={"customer_ref": "untrusted-json"})
        self.assert_blocked("INTERNAL_TYPED_INPUT_REQUIRED", rules=replace(self.rules, groups=list(self.rules.groups)))

    def test_sku_configuration_quantity_currency_platform_and_region_scope(self):
        for key, value in [("product_ref", "another-sku"), ("configuration_ref", "another-config"),
                           ("quantity", 2), ("currency", "USD"), ("sales_platform", "another-store"),
                           ("region", "another-region")]:
            with self.subTest(field=key):
                result = self.solve(ctx=replace(self.ctx, **{key: value}))
                self.assertEqual(result.reason, "RULE_SCOPE_MISMATCH_" + key.upper())

    def test_missing_and_unaware_time_inputs_block(self):
        self.assert_blocked("REQUIRED_CONTEXT_OR_VERSION_MISSING", ctx=replace(self.ctx, currency=""))
        self.assert_blocked("AWARE_DATETIME_REQUIRED_RULES", ctx=replace(self.ctx, as_of=AT.replace(tzinfo=None)))
        self.assert_blocked("UNKNOWN_RULE_TIMEZONE", ctx=replace(self.ctx, rule_timezone="Unknown/Zone"),
                            rules=replace(self.rules, rule_timezone="Unknown/Zone"))

    def test_expiry_is_half_open_and_earliest_used_evidence_limits_quote(self):
        self.assertEqual(self.solve(ctx=replace(self.ctx, as_of=START)).reason, "PENDING_INDEPENDENT_VALIDATION")
        self.assert_blocked("OUTSIDE_VALIDITY_RULES", ctx=replace(self.ctx, as_of=END))
        evidence_end = AT + timedelta(minutes=5)
        rules = replace(self.rules, evidence=(replace(self.rules.evidence[0], valid_until=evidence_end),))
        self.assertEqual(self.solve(rules=rules).internal_quote["valid_until"], evidence_end.isoformat())
        expired = replace(self.rules, evidence=(replace(self.rules.evidence[0], valid_until=AT),))
        self.assert_blocked("OUTSIDE_VALIDITY_EVIDENCE", rules=expired)

    def test_dst_fold_uses_utc_for_expiry_and_validity_order(self):
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, tzinfo=zone)
        end = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        after_expiry = datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1)
        ctx = replace(self.ctx, as_of=after_expiry, rule_timezone="America/New_York")
        rules = replace(self.rules, valid_from=start, valid_until=end,
                        rule_timezone=ctx.rule_timezone)
        self.assert_blocked("OUTSIDE_VALIDITY_RULES", ctx=ctx, rules=rules)
        inverted = replace(rules, valid_from=after_expiry)
        self.assert_blocked("INVALID_VALIDITY_RULES", ctx=ctx, rules=inverted)

    def test_dst_fold_earliest_source_expiry_uses_utc(self):
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, tzinfo=zone)
        early = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        later = datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1)
        evidence_end = datetime(2026, 11, 1, 2, tzinfo=zone)
        ctx = replace(self.ctx, as_of=start + timedelta(minutes=30),
                      rule_timezone="America/New_York")
        rules = replace(self.rules, valid_from=start, valid_until=early,
                        rule_timezone=ctx.rule_timezone,
                        evidence=(replace(self.rules.evidence[0], valid_from=start,
                                          valid_until=evidence_end),))
        snapshot = replace(self.snapshot, valid_from=start, valid_until=later)
        result = self.solve(ctx=ctx, rules=rules, snapshot=snapshot)
        self.assertEqual(result.internal_quote["valid_until"], early.isoformat())
        self.assertEqual(self.engine.validate(result, ctx, rules, snapshot).validation_state, "PASS")

    def test_four_levels_require_verified_applicability_not_just_names(self):
        self.assert_blocked("FOUR_LEVEL_EVIDENCE_INCOMPLETE", rules=replace(self.rules, levels=self.rules.levels[:-1]))
        levels = (replace(self.rules.levels[0], applicability="unknown"),) + self.rules.levels[1:]
        self.assert_blocked("FOUR_LEVEL_APPLICABILITY_UNVERIFIED", rules=replace(self.rules, levels=levels))
        levels = (replace(self.rules.levels[0], evidence_refs=()),) + self.rules.levels[1:]
        self.assert_blocked("REQUIRED_EVIDENCE_MISSING", rules=replace(self.rules, levels=levels))

    def test_absent_calculation_order_or_payment_order_is_not_inferred(self):
        self.assert_blocked("EXPLICIT_CALCULATION_ORDER_REQUIRED", rules=replace(self.rules, calculation_order=()))
        self.assert_blocked("EXPLICIT_PAYMENT_ORDER_REQUIRED", rules=replace(self.rules, payment_order=()))
        self.assert_blocked("BASE_MUST_PRECEDE_DISCOUNTS",
                            rules=replace(self.rules, calculation_order=("coupon", "base", "identity", "trade")))

    def test_actual_group_order_changes_calculation(self):
        identity = replace(self.rules.groups[2], options=(option("identity-10pct", "rate_discount", "0.10",
                                                                rounding_mode="ROUND_HALF_UP"),))
        normal = regroup(self.rules, (self.rules.groups[0], self.rules.groups[1], identity, self.rules.groups[3]))
        reversed_order = replace(normal, calculation_order=("base", "identity", "coupon", "trade"))
        self.assertEqual(self.solve(rules=normal).internal_quote["optimal_candidates"][0]["merchandise_total_minor"], 81000)
        self.assertEqual(self.solve(rules=reversed_order).internal_quote["optimal_candidates"][0]["merchandise_total_minor"], 80000)

    def test_threshold_is_current_goods_and_cap_is_applied(self):
        identity = replace(self.rules.groups[2], options=(option("no-identity", "noop"),
                           option("identity-threshold", "fixed_discount", 15000, minimum_spend_minor=95000, cap_minor=12000)))
        rules = regroup(self.rules, self.rules.groups[:2] + (identity, self.rules.groups[3]))
        q = self.solve(rules=rules).internal_quote
        self.assertEqual(q["optimal_candidates"][0]["merchandise_total_minor"], 88000)
        self.assertGreater(q["coverage"]["rejection_counts"]["THRESHOLD"], 0)

    def test_mutual_exclusion_and_prerequisite_constraints(self):
        identity = replace(self.rules.groups[2], options=(option("no-identity", "noop"),
                           option("identity-needs-coupon", "fixed_discount", 20000,
                                  requires_rule_ids=("coupon-10k",), exclusive_rule_ids=("no-coupon",))))
        rules = regroup(self.rules, self.rules.groups[:2] + (identity, self.rules.groups[3]))
        q = self.solve(rules=rules).internal_quote
        self.assertEqual(q["optimal_candidates"][0]["merchandise_total_minor"], 70000)
        self.assertGreater(q["coverage"]["rejection_counts"]["OPTION_CONSTRAINT"], 0)

    def test_unknown_qualification_is_missing_not_silently_ineligible(self):
        snapshot = replace(self.snapshot, eligibility=(replace(self.snapshot.eligibility[0], state="unknown"),))
        self.assert_blocked("ELIGIBILITY_UNKNOWN", snapshot=snapshot)
        snapshot = replace(self.snapshot, eligibility=(replace(self.snapshot.eligibility[0], state="not_eligible"),))
        best = self.solve(snapshot=snapshot).internal_quote["optimal_candidates"][0]
        self.assertEqual(best["merchandise_total_minor"], 90000)

    def test_cash_minimum_can_differ_from_merchandise_minimum(self):
        coupon = replace(self.rules.groups[1], options=(option("coupon-30k", "fixed_discount", 30000),
                                                       option("coupon-20k", "fixed_discount", 20000)))
        identity = replace(self.rules.groups[2], options=(option("no-identity", "noop"),))
        rules = regroup(self.rules, (self.rules.groups[0], coupon, identity, self.rules.groups[3]))
        voucher = replace(self.snapshot.resources[0], exclusive_rule_ids=("coupon-30k",))
        snapshot = replace(self.snapshot, resources=(voucher, self.snapshot.resources[1]))
        best = self.solve(rules=rules, snapshot=snapshot).internal_quote["optimal_candidates"][0]
        self.assertIn("coupon-20k", best["selected_rule_ids"])
        self.assertEqual(best["merchandise_total_minor"], 80000)
        self.assertEqual(best["cash_due_now_minor"], 63000)

    def test_goods_only_credits_cannot_pay_required_shipping(self):
        groups = (replace(self.rules.groups[0], options=(option("base-small", "set_base", 1000),)),
                  replace(self.rules.groups[1], options=(option("no-coupon", "noop"),)),
                  replace(self.rules.groups[2], options=(option("no-identity", "noop"),)), self.rules.groups[3])
        rules = regroup(self.rules, groups)
        points = replace(self.snapshot.resources[1], balance_units=5000, permitted_max_units=5000,
                         cap_rate_decimal=None)
        rules, snapshot = reresc(rules, self.snapshot, [points], old_assets=[])
        result = self.solve(rules=rules, snapshot=snapshot)
        self.assertEqual(result.internal_quote["optimal_candidates"][0]["cash_due_now_minor"], 1000)

    def test_missing_and_dynamic_fees_block_instead_of_assuming_zero(self):
        self.assert_blocked("MANDATORY_FEE_COVERAGE_UNKNOWN", rules=replace(self.rules, fee_coverage_complete=False))
        self.assert_blocked("MANDATORY_FEE_AMOUNT_UNKNOWN", rules=replace(self.rules, fees=(replace(self.rules.fees[0], amount_minor=None),)))
        self.assert_blocked("UNSUPPORTED_FEE_OPERATION", rules=replace(self.rules, fees=(replace(self.rules.fees[0], operation="after_points_threshold"),)))

    def test_unknown_infinite_future_or_unissued_resource_is_not_usable(self):
        for changes, reason in [({"balance_units": None}, "RESOURCE_BALANCE_OR_USE_LIMIT_UNKNOWN"),
                                ({"availability": "future_order_reward"}, "RESOURCE_NOT_VERIFIED_AND_AVAILABLE"),
                                ({"verification_state": "unknown"}, "RESOURCE_NOT_VERIFIED_AND_AVAILABLE"),
                                ({"permitted_max_units": 16000}, "PERMITTED_USE_EXCEEDS_BALANCE")]:
            with self.subTest(changes=changes):
                snapshot = replace(self.snapshot, resources=(replace(self.snapshot.resources[0], **changes),
                                                            self.snapshot.resources[1]))
                self.assert_blocked(reason, snapshot=snapshot)

    def test_old_asset_requires_final_inspection_and_issued_voucher(self):
        for changes in [{"inspection_status": "preliminary_estimate"}, {"voucher_status": "pending"},
                        {"inspected_final_value_minor": None}]:
            snapshot = replace(self.snapshot, old_assets=(replace(self.snapshot.old_assets[0], **changes),))
            self.assert_blocked("OLD_ASSET_VALUE_NOT_FINAL_OR_VOUCHER_NOT_ISSUED", snapshot=snapshot)
        self.assert_blocked("TRADE_IN_VOUCHER_FINAL_ASSET_LINK_MISSING", snapshot=replace(self.snapshot, old_assets=()))

    def test_recovery_value_or_points_cannot_be_second_sales_adjustment(self):
        for kind in ["old_asset_recovery_value", "payment_credit", "membership_points"]:
            coupon = replace(self.rules.groups[1], options=(option("unsafe-deduction", "fixed_discount", 15000,
                                                                 benefit_kind=kind),))
            rules = regroup(self.rules, (self.rules.groups[0], coupon, *self.rules.groups[2:]))
            self.assert_blocked("UNSUPPORTED_BENEFIT_LEDGER_KIND", rules=rules)

    def test_resource_customer_and_allowed_scope_cannot_be_invented(self):
        self.assert_blocked("CUSTOMER_RESOURCE_MISMATCH", snapshot=replace(self.snapshot, customer_ref="another-customer"))
        self.assert_blocked("CUSTOMER_RESOURCE_MISMATCH", snapshot=replace(self.snapshot, tenant_ref="another-tenant"))
        self.assert_blocked("RULE_SCOPE_MISMATCH_STORE_REF", rules=replace(self.rules, store_ref="another-store"))
        self.assert_blocked("CUSTOMER_RESOURCES_OR_ALLOWED_SCOPE_UNVERIFIED", snapshot=replace(self.snapshot, use_scope_confirmed=False))

    def test_manifest_must_exactly_cover_groups_and_resources(self):
        for manifest in [replace(self.rules.manifest, complete=False),
                         replace(self.rules.manifest, group_option_ids=self.rules.manifest.group_option_ids[:-1]),
                         replace(self.rules.manifest, resource_refs=())]:
            self.assert_blocked("CANDIDATE_COVERAGE_INCOMPLETE", rules=replace(self.rules, manifest=manifest))

    def test_bounded_domain_does_not_claim_partial_optimal(self):
        result = self.assert_blocked("COMPLETE_DOMAIN_EXCEEDS_CONFIGURED_BOUND",
                                     engine=QuoteEngine(synthetic_test=True, max_candidates=63))
        self.assertEqual(result.quote_status, "TIMEOUT")

    def test_no_legal_combination_is_proven_only_after_complete_enumeration(self):
        coupon = replace(self.rules.groups[1], options=(option("too-large", "fixed_discount", 100001),))
        rules = regroup(self.rules, (self.rules.groups[0], coupon, *self.rules.groups[2:]))
        result = self.solve(rules=rules)
        self.assertEqual(result.quote_status, "INFEASIBLE_PROVEN")
        self.assertIsNone(result.internal_quote)

    def test_ties_preserve_different_consumption_without_executing_it(self):
        groups = (replace(self.rules.groups[0], options=(option("base-small", "set_base", 1000),)),
                  replace(self.rules.groups[1], options=(option("no-coupon", "noop"),)),
                  replace(self.rules.groups[2], options=(option("no-identity", "noop"),)), self.rules.groups[3])
        rules = regroup(self.rules, groups)
        voucher = replace(self.snapshot.resources[0], increment_units=1000)
        points = replace(self.snapshot.resources[1], cap_rate_decimal=None)
        snapshot = replace(self.snapshot, resources=(voucher, points))
        q = self.solve(rules=rules, snapshot=snapshot).internal_quote
        self.assertEqual(q["tie_selection_state"], "CUSTOMER_CHOICE_REQUIRED")
        self.assertGreater(len(q["optimal_candidates"]), 1)
        self.assertEqual(self.snapshot.resources[0].balance_units, snapshot.resources[0].balance_units)
        self.assertTrue(all(r["cash_due_now_minor"] == 1000 for r in q["optimal_candidates"]))

    def test_decimal_rounding_replayed_with_exact_rationals(self):
        for mode, goods in [("ROUND_DOWN", 1000), ("ROUND_HALF_UP", 999), ("ROUND_UP", 999)]:
            with self.subTest(mode=mode):
                groups = (replace(self.rules.groups[0], options=(option("base-round", "set_base", 1001),)),
                          replace(self.rules.groups[1], options=(option("no-coupon", "noop"),)),
                          replace(self.rules.groups[2], options=(option("rounding-rate", "rate_discount", "0.0015",
                                                                        rounding_mode=mode),)), self.rules.groups[3])
                rules = regroup(self.rules, groups)
                result = self.solve(rules=rules)
                self.assertEqual(result.internal_quote["optimal_candidates"][0]["merchandise_total_minor"], goods)
                self.assertEqual(self.engine.validate(result, self.ctx, rules, self.snapshot).validation_state, "PASS")

    def test_non_integer_money_boolean_and_invalid_decimal_rejected(self):
        for value in [True, 1.2, -1, "1000"]:
            groups = (replace(self.rules.groups[0], options=(option("invalid-base", "set_base", value),)), *self.rules.groups[1:])
            self.assertIsNone(self.solve(rules=regroup(self.rules, groups)).internal_quote)
        for rate in ["NaN", "Infinity", "1e1000000", "-0.1", "1.01", "0.1234567890123"]:
            identity = replace(self.rules.groups[2], options=(option("invalid-rate", "rate_discount", rate,
                                                                   rounding_mode="ROUND_HALF_UP"),))
            self.assertIsNone(self.solve(rules=regroup(self.rules, (*self.rules.groups[:2], identity, self.rules.groups[3]))).internal_quote)

    def test_unimplemented_operation_and_payment_allocation_are_blocked(self):
        coupon = replace(self.rules.groups[1], options=(option("unsupported", "custom_python", "do_anything"),))
        self.assert_blocked("UNSUPPORTED_OPERATION", rules=regroup(self.rules, (self.rules.groups[0], coupon, *self.rules.groups[2:])))
        snapshot = replace(self.snapshot, resources=(replace(self.snapshot.resources[0], allocation_order="fees_first"), self.snapshot.resources[1]))
        self.assert_blocked("UNSUPPORTED_PAYMENT_ALLOCATION_ORDER", snapshot=snapshot)

    def test_unknown_evidence_and_unverified_external_source_block(self):
        for source_kind, state in [("official_web_candidate", "verified"), ("synthetic_fixture", "unverified")]:
            rules = replace(self.rules, evidence=(replace(self.rules.evidence[0], source_kind=source_kind, verification_state=state),))
            self.assert_blocked("EVIDENCE_NOT_APPROVED", rules=rules)

    def test_independent_validator_detects_amount_tampering_and_missing_legal_rows(self):
        for change in ["cash", "alias", "legal_rows", "metadata", "optimal_rows"]:
            with self.subTest(change=change):
                result = self.solve()
                q = copy.deepcopy(result.internal_quote)
                if change == "cash":
                    q["optimal_candidates"][0]["cash_due_now_minor"] -= 1
                elif change == "alias":
                    q["optimal_candidates"][0]["customer_payable_minor"] += 1
                elif change == "legal_rows":
                    q["legal_candidates"].pop()
                elif change == "metadata":
                    q["objective_metric"] = "min_goods_only"
                elif change == "optimal_rows":
                    q["optimal_candidates"] = q["legal_candidates"][:1]
                validated = self.engine.validate(replace(result, internal_quote=q), self.ctx, self.rules, self.snapshot)
                self.assertEqual(validated.validation_state, "FAIL")
                self.assertEqual(validated.quote_status, "SOLVER_ERROR")

    def test_resource_or_context_change_invalidates_old_quote(self):
        result = self.solve()
        changed = replace(self.snapshot, version="2")
        validated = self.engine.validate(result, self.ctx, self.rules, changed)
        self.assertEqual(validated.reason, "VALIDATION_DEPENDENCY_MISMATCH")
        self.assertEqual(validated.validation_state, "FAIL")

    def test_matching_forged_quote_refs_do_not_replace_dependency_identity(self):
        result = self.solve()
        quote = copy.deepcopy(result.internal_quote)
        quote["quote_ref"] = "qkernel_someone_else"
        forged = replace(result, quote_ref=quote["quote_ref"], internal_quote=quote)
        validated = self.engine.validate(forged, self.ctx, self.rules, self.snapshot)
        self.assertEqual(validated.reason, "VALIDATION_DEPENDENCY_MISMATCH")
        self.assertEqual(validated.validation_state, "FAIL")

    def test_production_input_still_needs_adapter_authorization_before_release(self):
        ctx = replace(self.ctx, source_mode="ima_live")
        rules = replace(self.rules, publication_status="approved",
                        evidence=(replace(self.rules.evidence[0], source_kind="ima_verified"),))
        engine = QuoteEngine()
        result = engine.solve(ctx, rules, self.snapshot)
        validated = engine.validate(result, ctx, rules, self.snapshot)
        self.assertEqual(validated.validation_state, "PASS")
        self.assertEqual(validated.reason, "CORE_VALIDATED_NOT_RELEASED")
        self.assertFalse(validated.safe_status()["real_quote_enabled"])
        self.assertFalse(validated.safe_status()["client_quote_allowed"])
        self.assertIsNone(validated.safe_status()["customer_quote_summary"])


if __name__ == "__main__":
    unittest.main()

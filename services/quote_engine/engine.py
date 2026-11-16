"""Strict, bounded deterministic quote kernel. No IO, model calls, or real rules.

The dataclasses below are an INTERNAL input contract for an authenticated rule
compiler. Constructing a dataclass, setting ``approved``, or supplying an evidence
reference is NOT authentication or evidence verification. An eventual adapter
must verify source access, signed/published rule versions, customer identity,
tenant scope, source integrity and destination permissions before calling this
kernel. Do not expose this input format as an unauthenticated HTTP body.

Supported subset: exactly-one finite sales choice groups, explicit group order,
unit base prices, fixed/rate sales discounts on the current goods subtotal,
thresholds, discount caps, explicit mutual exclusion/dependencies, fixed mandatory
fees, and finitely enumerated payment resources with integer consumption steps.
Every unsupported operation/fee dependency is blocked, never approximated.
Old-asset value is metadata for a verified, issued payment voucher, not another
discount. All monetary input is integer minor units or bounded Decimal strings.

This module is NOT connected to knowledge_bridge, Dify, a real rule publisher,
or an authorized customer-view service. Its public result NEVER enables real
quotes or discloses a customer summary. Synthetic results are labelled as such.
Independent replay and exhaustive validation are kernel evidence, not complete
business release authorization or a claim of measured >95% accuracy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, localcontext
import hashlib
import itertools
import json
from typing import Optional, Union, get_args, get_origin, get_type_hints
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


OBJECTIVE = "min_customer_payable"
METRIC = "min_cash_due_now_given_verified_customer_resources"
METRIC_VERSION = "1.0"
LEVELS = (
    ("base_price", "基准价"), ("platform_discount", "平台优惠"),
    ("identity_benefit", "身份权益"), ("trade_in_national_subsidy", "换新国补"),
)
ROUNDING = {"ROUND_DOWN": ROUND_DOWN, "ROUND_HALF_UP": ROUND_HALF_UP, "ROUND_UP": ROUND_UP}
MAX_MINOR = 10**15


@dataclass(frozen=True)
class Evidence:
    evidence_ref: str
    source_kind: str  # synthetic_fixture / ima_verified / local_approved
    verification_state: str
    valid_from: datetime
    valid_until: datetime


@dataclass(frozen=True)
class LevelEvidence:
    level_id: str
    display_name: str
    applicability: str  # applicable / not_applicable / excluded_mutual_exclusion
    evidence_refs: tuple[str, ...]
    customer_reason: str


@dataclass(frozen=True)
class Eligibility:
    eligibility_ref: str
    state: str  # verified / not_eligible / unknown
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class SalesOption:
    rule_id: str
    operation: str  # set_base / fixed_discount / rate_discount / noop
    value: object
    evidence_refs: tuple[str, ...]
    customer_reason: str
    benefit_kind: str  # base_price / no_adjustment / sales_discount / identity_benefit / additional_trade_in_bonus / national_subsidy
    eligibility_refs: tuple[str, ...] = ()
    requires_rule_ids: tuple[str, ...] = ()
    exclusive_rule_ids: tuple[str, ...] = ()
    minimum_spend_minor: int = 0
    threshold_base: str = "current_merchandise"
    cap_minor: Optional[int] = None
    rounding_mode: Optional[str] = None


@dataclass(frozen=True)
class ChoiceGroup:
    group_id: str
    level_id: str
    options: tuple[SalesOption, ...]


@dataclass(frozen=True)
class Fee:
    fee_ref: str
    operation: str  # only fixed is currently supported
    amount_minor: Optional[int]
    evidence_refs: tuple[str, ...]
    customer_reason: str


@dataclass(frozen=True)
class CandidateManifest:
    manifest_ref: str
    complete: bool
    group_option_ids: tuple[tuple[str, tuple[str, ...]], ...]
    resource_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class RuleSet:
    rule_set_ref: str
    version: str
    publication_status: str  # approved or synthetic_fixture
    approval_ref: str
    tenant_ref: str
    store_ref: str
    product_ref: str
    configuration_ref: str
    sales_platform: str
    region: str
    currency: str
    quantity: int
    valid_from: datetime
    valid_until: datetime
    rule_timezone: str
    levels: tuple[LevelEvidence, ...]
    groups: tuple[ChoiceGroup, ...]
    calculation_order: tuple[str, ...]
    calculation_order_evidence_refs: tuple[str, ...]
    payment_order: tuple[str, ...]
    payment_order_evidence_refs: tuple[str, ...]
    fees: tuple[Fee, ...]
    fee_coverage_complete: bool
    fee_coverage_evidence_refs: tuple[str, ...]
    manifest: CandidateManifest
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class Resource:
    resource_ref: str
    resource_kind: str  # points / payment_voucher / trade_in_voucher
    unit: str  # points / minor_currency
    balance_units: Optional[int]
    permitted_max_units: Optional[int]
    increment_units: int
    unit_value_minor: str
    rounding_mode: str
    evidence_refs: tuple[str, ...]
    allocation_order: str  # goods_then_fees is the only supported, evidenced policy
    eligibility_refs: tuple[str, ...] = ()
    requires_rule_ids: tuple[str, ...] = ()
    exclusive_rule_ids: tuple[str, ...] = ()
    verification_state: str = "unverified"
    availability: str = "unknown"  # available only; no pending/future balances
    cap_minor: Optional[int] = None
    cap_rate_decimal: Optional[str] = None
    cap_base: str = "merchandise_total"
    eligible_for_fees: bool = False


@dataclass(frozen=True)
class OldAsset:
    asset_ref: str
    inspected_final_value_minor: Optional[int]
    inspection_status: str
    voucher_status: str
    issued_resource_ref: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ResourceSnapshot:
    snapshot_ref: str
    version: str
    customer_ref: str
    tenant_ref: str
    verification_state: str
    resource_use_scope_ref: str
    use_scope_confirmed: bool
    valid_from: datetime
    valid_until: datetime
    resources: tuple[Resource, ...]
    old_assets: tuple[OldAsset, ...]
    eligibility: tuple[Eligibility, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class QuoteContext:
    tenant_ref: str
    store_ref: str
    actor_ref: str
    customer_ref: str
    product_ref: str
    configuration_ref: str
    quantity: int
    currency: str
    sales_platform: str
    region: str
    as_of: datetime
    rule_timezone: str
    source_mode: str
    recommendation_set_ref: str
    recommendation_set_version: str
    objective: str = OBJECTIVE
    objective_metric: str = METRIC
    objective_metric_version: str = METRIC_VERSION


@dataclass(frozen=True)
class QuoteResult:
    """Internal kernel result. Never serialize ``internal_quote`` to a model."""

    quote_status: str
    reason: str
    quote_ref: Optional[str] = None
    internal_quote: Optional[dict] = None
    validation_state: str = "NOT_RUN"
    synthetic_test_only: bool = False

    def safe_status(self) -> dict:
        return {
            "quote_required": True, "quote_status": self.quote_status,
            "reason": self.reason, "quote_ref": self.quote_ref,
            "client_quote_allowed": False, "customer_quote_summary": None,
            "real_quote_enabled": False, "kernel_validation_state": self.validation_state,
            "synthetic_test_only": self.synthetic_test_only,
            "integration_state": "CORE_ONLY_BRIDGE_NOT_CONNECTED",
        }


class _Blocked(Exception):
    def __init__(self, status: str, reason: str):
        self.status, self.reason = status, reason


class _Rejected(Exception):
    """A fully defined candidate is illegal, not missing evidence."""


def _block(status: str, reason: str) -> None:
    raise _Blocked(status, reason)


def _int(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > MAX_MINOR:
        _block("SOLVER_ERROR", "INVALID_INTEGER_" + name)
    return value


def _typed(value: object, expected: object) -> bool:
    """Reject malformed internal structures, including mutable list substitutions."""
    origin, arguments = get_origin(expected), get_args(expected)
    if origin is Union:
        return any(_typed(value, item) for item in arguments)
    if origin is tuple:
        if type(value) is not tuple:
            return False
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return all(_typed(item, arguments[0]) for item in value)
        return len(value) == len(arguments) and all(_typed(item, kind) for item, kind in zip(value, arguments))
    if expected is object:
        return value is None or type(value) in {int, str}
    if expected is type(None):
        return value is None
    if expected in {str, int, bool}:
        return type(value) is expected
    if expected is datetime:
        return isinstance(value, datetime)
    if isinstance(expected, type) and is_dataclass(expected):
        if type(value) is not expected:
            return False
        hints = get_type_hints(expected)
        return all(_typed(getattr(value, name), kind) for name, kind in hints.items())
    return False


def _decimal(value: object, name: str, *, rate: bool = False) -> Decimal:
    # Bounded plain strings prevent float coercion, exponent bombs and precision loss.
    if not isinstance(value, str) or len(value) > 40:
        _block("SOLVER_ERROR", "INVALID_DECIMAL_" + name)
    import re
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,12})?", value):
        _block("SOLVER_ERROR", "INVALID_DECIMAL_" + name)
    try:
        number = Decimal(value)
    except InvalidOperation:
        _block("SOLVER_ERROR", "INVALID_DECIMAL_" + name)
    if not number.is_finite() or number < 0 or (rate and number > 1):
        _block("SOLVER_ERROR", "INVALID_DECIMAL_" + name)
    return number


def _valid_period(start: datetime, end: datetime, at: datetime, label: str) -> None:
    if any(not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() is None for d in (start, end, at)):
        _block("MISSING_INPUT", "AWARE_DATETIME_REQUIRED_" + label)
    start_utc, end_utc, at_utc = (value.astimezone(timezone.utc) for value in (start, end, at))
    if start_utc >= end_utc:
        _block("BLOCKED_SOURCE_UNVERIFIED", "INVALID_VALIDITY_" + label)
    if not start_utc <= at_utc < end_utc:  # half-open on the actual UTC timeline
        _block("SOURCE_EXPIRED", "OUTSIDE_VALIDITY_" + label)


def _canonical(value: object) -> object:
    if is_dataclass(value):
        return {f.name: _canonical(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    return value


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _rounded(value: Decimal, rounding_mode: str) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUNDING[rounding_mode]))


class QuoteEngine:
    def __init__(self, *, synthetic_test: bool = False, max_candidates: int = 10_000):
        if type(synthetic_test) is not bool or type(max_candidates) is not int or not 1 <= max_candidates <= 100_000:
            raise ValueError("explicit Boolean mode and positive integer candidate bound required")
        self.synthetic_test, self.max_candidates = synthetic_test, max_candidates

    def _preflight(self, ctx: QuoteContext, rules: RuleSet, snapshot: ResourceSnapshot) -> dict:
        if not _typed(ctx, QuoteContext) or not _typed(rules, RuleSet) or not _typed(snapshot, ResourceSnapshot):
            _block("SOLVER_ERROR", "INTERNAL_TYPED_INPUT_REQUIRED")
        required = (ctx.tenant_ref, ctx.store_ref, ctx.actor_ref, ctx.customer_ref,
                    ctx.product_ref, ctx.configuration_ref, ctx.currency,
                    ctx.sales_platform, ctx.region, ctx.rule_timezone, ctx.recommendation_set_ref,
                    ctx.recommendation_set_version, rules.rule_set_ref, rules.version,
                    rules.approval_ref,
                    snapshot.snapshot_ref, snapshot.version, snapshot.resource_use_scope_ref)
        if any(not isinstance(v, str) or not v.strip() for v in required):
            _block("MISSING_INPUT", "REQUIRED_CONTEXT_OR_VERSION_MISSING")
        if (ctx.objective, ctx.objective_metric, ctx.objective_metric_version) != (OBJECTIVE, METRIC, METRIC_VERSION):
            _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_OBJECTIVE")
        _int(ctx.quantity, "QUANTITY", positive=True)
        if ctx.source_mode not in {"local_snapshot", "ima_live", "hybrid_verified", "synthetic_test"}:
            _block("BLOCKED_SOURCE_UNVERIFIED", "UNKNOWN_SOURCE_MODE")
        if self.synthetic_test != (ctx.source_mode == "synthetic_test"):
            _block("ACCESS_DENIED", "SYNTHETIC_MODE_MISMATCH")
        expected_publication = "synthetic_fixture" if self.synthetic_test else "approved"
        if rules.publication_status != expected_publication:
            _block("BLOCKED_SOURCE_UNVERIFIED", "RULES_NOT_APPROVED")
        for name in ("tenant_ref", "store_ref", "product_ref", "configuration_ref", "quantity", "currency", "sales_platform", "region", "rule_timezone"):
            if getattr(ctx, name) != getattr(rules, name):
                _block("MISSING_INPUT", "RULE_SCOPE_MISMATCH_" + name.upper())
        try:
            ZoneInfo(ctx.rule_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            _block("MISSING_INPUT", "UNKNOWN_RULE_TIMEZONE")
        _valid_period(rules.valid_from, rules.valid_until, ctx.as_of, "RULES")
        _valid_period(snapshot.valid_from, snapshot.valid_until, ctx.as_of, "RESOURCES")
        if snapshot.customer_ref != ctx.customer_ref or snapshot.tenant_ref != ctx.tenant_ref:
            _block("ACCESS_DENIED", "CUSTOMER_RESOURCE_MISMATCH")
        if snapshot.verification_state != "verified" or snapshot.use_scope_confirmed is not True:
            _block("MISSING_INPUT", "CUSTOMER_RESOURCES_OR_ALLOWED_SCOPE_UNVERIFIED")
        evidence = {e.evidence_ref: e for e in rules.evidence}
        if len(evidence) != len(rules.evidence):
            _block("BLOCKED_SOURCE_UNVERIFIED", "DUPLICATE_EVIDENCE_REF")

        used_evidence_refs = set()

        def require_evidence(refs: tuple[str, ...]) -> None:
            if not isinstance(refs, tuple) or not refs or any(not ref or ref not in evidence for ref in refs):
                _block("SOURCE_MISSING", "REQUIRED_EVIDENCE_MISSING")
            for ref in refs:
                used_evidence_refs.add(ref)
                e = evidence[ref]
                allowed = {"synthetic_fixture"} if self.synthetic_test else {"ima_verified", "local_approved"}
                if ctx.source_mode in {"ima_live", "hybrid_verified"}:
                    allowed = {"ima_verified"}
                if e.verification_state != "verified" or e.source_kind not in allowed:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "EVIDENCE_NOT_APPROVED")
                _valid_period(e.valid_from, e.valid_until, ctx.as_of, "EVIDENCE")

        require_evidence(snapshot.evidence_refs)
        levels = {level.level_id: level for level in rules.levels}
        if len(levels) != 4 or set(levels) != dict(LEVELS).keys():
            _block("BLOCKED_SOURCE_UNVERIFIED", "FOUR_LEVEL_EVIDENCE_INCOMPLETE")
        for level_id, display in LEVELS:
            level = levels[level_id]
            if level.display_name != display or level.applicability not in {
                "applicable", "not_applicable", "excluded_mutual_exclusion"
            } or not level.customer_reason:
                _block("BLOCKED_SOURCE_UNVERIFIED", "FOUR_LEVEL_APPLICABILITY_UNVERIFIED")
            require_evidence(level.evidence_refs)
        if levels["base_price"].applicability != "applicable":
            _block("BLOCKED_SOURCE_UNVERIFIED", "BASE_PRICE_NOT_APPLICABLE")
        groups = {g.group_id: g for g in rules.groups}
        if (len(groups) != len(rules.groups) or not groups or len(set(rules.calculation_order)) != len(groups)
                or set(rules.calculation_order) != set(groups)):
            _block("BLOCKED_SOURCE_UNVERIFIED", "EXPLICIT_CALCULATION_ORDER_REQUIRED")
        require_evidence(rules.calculation_order_evidence_refs)
        if groups[rules.calculation_order[0]].level_id != "base_price":
            _block("BLOCKED_SOURCE_UNVERIFIED", "BASE_MUST_PRECEDE_DISCOUNTS")
        qualifications = {e.eligibility_ref: e for e in snapshot.eligibility}
        if len(qualifications) != len(snapshot.eligibility):
            _block("BLOCKED_SOURCE_UNVERIFIED", "DUPLICATE_ELIGIBILITY_REF")
        for e in snapshot.eligibility:
            if e.state not in {"verified", "not_eligible", "unknown"}:
                _block("MISSING_INPUT", "UNKNOWN_ELIGIBILITY_STATE")
            if e.state != "unknown":
                require_evidence(e.evidence_refs)

        def check_eligibility(refs: tuple[str, ...]) -> None:
            for ref in refs:
                if ref not in qualifications or qualifications[ref].state == "unknown":
                    _block("MISSING_INPUT", "ELIGIBILITY_UNKNOWN")

        option_ids = set()
        base_groups = 0
        for group in rules.groups:
            if not group.group_id or group.level_id not in levels or not group.options:
                _block("BLOCKED_SOURCE_UNVERIFIED", "EMPTY_OR_UNKNOWN_CHOICE_GROUP")
            if levels[group.level_id].applicability != "applicable":
                _block("RULE_CONFLICT", "INAPPLICABLE_LEVEL_HAS_EXECUTABLE_OPTIONS")
            base_groups += group.level_id == "base_price"
            for option in group.options:
                if not option.rule_id or option.rule_id in option_ids or not option.customer_reason:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "DUPLICATE_OR_UNEXPLAINED_OPTION")
                option_ids.add(option.rule_id)
                require_evidence(option.evidence_refs)
                check_eligibility(option.eligibility_refs)
                if option.operation not in {"set_base", "fixed_discount", "rate_discount", "noop"}:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_OPERATION")
                permitted_kind = {"set_base": {"base_price"}, "noop": {"no_adjustment"},
                                  "fixed_discount": {"sales_discount", "identity_benefit", "additional_trade_in_bonus", "national_subsidy"},
                                  "rate_discount": {"sales_discount", "identity_benefit", "additional_trade_in_bonus", "national_subsidy"}}
                if option.benefit_kind not in permitted_kind[option.operation]:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_BENEFIT_LEDGER_KIND")
                if (group.level_id == "base_price") != (option.operation == "set_base"):
                    _block("RULE_CONFLICT", "BASE_OPERATION_SCOPE_CONFLICT")
                if option.threshold_base != "current_merchandise":
                    _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_THRESHOLD_BASE")
                _int(option.minimum_spend_minor, "THRESHOLD")
                if option.cap_minor is not None:
                    _int(option.cap_minor, "DISCOUNT_CAP")
                if option.operation in {"set_base", "fixed_discount"}:
                    _int(option.value, "RULE_VALUE", positive=option.operation == "set_base")
                elif option.operation == "rate_discount":
                    _decimal(option.value, "DISCOUNT_RATE", rate=True)
                    if option.rounding_mode not in ROUNDING:
                        _block("BLOCKED_SOURCE_UNVERIFIED", "EXPLICIT_ROUNDING_REQUIRED")
                elif option.value is not None:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "NOOP_MUST_HAVE_NO_VALUE")
                if option.operation in {"set_base", "noop"} and (
                        option.minimum_spend_minor or option.cap_minor is not None or option.rounding_mode is not None):
                    _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_BASE_OR_NOOP_MODIFIER")
                if option.operation == "fixed_discount" and option.rounding_mode is not None:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_FIXED_DISCOUNT_ROUNDING")
        if base_groups != 1:
            _block("RULE_CONFLICT", "EXACTLY_ONE_BASE_GROUP_REQUIRED")
        for level_id, level in levels.items():
            if level.applicability == "applicable" and not any(g.level_id == level_id for g in rules.groups):
                _block("SOURCE_MISSING", "APPLICABLE_LEVEL_HAS_NO_OPTIONS")
        for group in rules.groups:
            for option in group.options:
                related = set(option.requires_rule_ids) | set(option.exclusive_rule_ids)
                if not related <= option_ids or option.rule_id in related:
                    _block("BLOCKED_SOURCE_UNVERIFIED", "UNKNOWN_OR_SELF_RULE_RELATION")
        if rules.fee_coverage_complete is not True:
            _block("SOURCE_MISSING", "MANDATORY_FEE_COVERAGE_UNKNOWN")
        require_evidence(rules.fee_coverage_evidence_refs)
        if len({fee.fee_ref for fee in rules.fees}) != len(rules.fees):
            _block("BLOCKED_SOURCE_UNVERIFIED", "DUPLICATE_FEE")
        for fee in rules.fees:
            if fee.operation != "fixed":
                _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_FEE_OPERATION")
            if fee.amount_minor is None:
                _block("MISSING_INPUT", "MANDATORY_FEE_AMOUNT_UNKNOWN")
            _int(fee.amount_minor, "MANDATORY_FEE")
            require_evidence(fee.evidence_refs)
        resources = {r.resource_ref: r for r in snapshot.resources}
        if len(resources) != len(snapshot.resources):
            _block("BLOCKED_SOURCE_UNVERIFIED", "DUPLICATE_RESOURCE_REF")
        if len(set(rules.payment_order)) != len(resources) or set(rules.payment_order) != set(resources):
            _block("BLOCKED_SOURCE_UNVERIFIED", "EXPLICIT_PAYMENT_ORDER_REQUIRED")
        require_evidence(rules.payment_order_evidence_refs)
        for resource in snapshot.resources:
            if resource.resource_kind not in {"points", "payment_voucher", "trade_in_voucher"}:
                _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_RESOURCE_KIND")
            if resource.unit != ("points" if resource.resource_kind == "points" else "minor_currency"):
                _block("BLOCKED_SOURCE_UNVERIFIED", "RESOURCE_UNIT_MISMATCH")
            if resource.verification_state != "verified" or resource.availability != "available":
                _block("MISSING_INPUT", "RESOURCE_NOT_VERIFIED_AND_AVAILABLE")
            if resource.balance_units is None or resource.permitted_max_units is None:
                _block("MISSING_INPUT", "RESOURCE_BALANCE_OR_USE_LIMIT_UNKNOWN")
            _int(resource.balance_units, "RESOURCE_BALANCE")
            _int(resource.permitted_max_units, "PERMITTED_USE")
            _int(resource.increment_units, "REDEMPTION_INCREMENT", positive=True)
            if resource.permitted_max_units > resource.balance_units:
                _block("MISSING_INPUT", "PERMITTED_USE_EXCEEDS_BALANCE")
            if not isinstance(resource.eligible_for_fees, bool):
                _block("BLOCKED_SOURCE_UNVERIFIED", "FEE_PAYMENT_SCOPE_REQUIRED")
            if resource.rounding_mode not in ROUNDING or resource.cap_base != "merchandise_total":
                _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_PAYMENT_ROUNDING_OR_CAP_BASE")
            if resource.allocation_order != "goods_then_fees":
                _block("BLOCKED_SOURCE_UNVERIFIED", "UNSUPPORTED_PAYMENT_ALLOCATION_ORDER")
            if _decimal(resource.unit_value_minor, "UNIT_VALUE") <= 0:
                _block("BLOCKED_SOURCE_UNVERIFIED", "NONPOSITIVE_RESOURCE_UNIT_VALUE")
            if resource.cap_minor is not None:
                _int(resource.cap_minor, "RESOURCE_CAP")
            if resource.cap_rate_decimal is not None:
                _decimal(resource.cap_rate_decimal, "RESOURCE_CAP_RATE", rate=True)
            require_evidence(resource.evidence_refs)
            check_eligibility(resource.eligibility_refs)
            if not (set(resource.requires_rule_ids) | set(resource.exclusive_rule_ids)) <= option_ids:
                _block("BLOCKED_SOURCE_UNVERIFIED", "UNKNOWN_RESOURCE_SALES_RELATION")
        if len({a.asset_ref for a in snapshot.old_assets}) != len(snapshot.old_assets):
            _block("BLOCKED_SOURCE_UNVERIFIED", "DUPLICATE_OLD_ASSET")
        issued_refs = [a.issued_resource_ref for a in snapshot.old_assets]
        if len(set(issued_refs)) != len(issued_refs):
            _block("BLOCKED_SOURCE_UNVERIFIED", "OLD_ASSET_VOUCHER_REUSED")
        for asset in snapshot.old_assets:
            require_evidence(asset.evidence_refs)
            if (asset.inspection_status != "inspected_final" or asset.voucher_status != "issued_available"
                    or asset.inspected_final_value_minor is None):
                _block("MISSING_INPUT", "OLD_ASSET_VALUE_NOT_FINAL_OR_VOUCHER_NOT_ISSUED")
            _int(asset.inspected_final_value_minor, "OLD_ASSET_FINAL_VALUE")
            linked = resources.get(asset.issued_resource_ref)
            if (linked is None or linked.resource_kind != "trade_in_voucher"
                    or _decimal(linked.unit_value_minor, "TRADE_IN_UNIT_VALUE") != 1
                    or linked.balance_units > asset.inspected_final_value_minor):
                _block("RULE_CONFLICT", "OLD_ASSET_PAYMENT_LINK_INVALID")
        for resource in snapshot.resources:
            if resource.resource_kind == "trade_in_voucher" and resource.resource_ref not in issued_refs:
                _block("SOURCE_MISSING", "TRADE_IN_VOUCHER_FINAL_ASSET_LINK_MISSING")
        manifest = rules.manifest
        require_evidence(manifest.evidence_refs)
        actual_options = {g.group_id: tuple(sorted(o.rule_id for o in g.options)) for g in rules.groups}
        declared_options = {g: tuple(sorted(options)) for g, options in manifest.group_option_ids}
        if (manifest.complete is not True or not manifest.manifest_ref
                or len(declared_options) != len(manifest.group_option_ids)
                or declared_options != actual_options or len(set(manifest.resource_refs)) != len(resources)
                or len(manifest.resource_refs) != len(resources)
                or set(manifest.resource_refs) != set(resources)):
            _block("SOURCE_MISSING", "CANDIDATE_COVERAGE_INCOMPLETE")
        return {"groups": groups, "resources": resources, "eligibility": qualifications, "levels": levels,
                "valid_until": min((rules.valid_until, snapshot.valid_until,
                                    *(evidence[ref].valid_until for ref in used_evidence_refs)),
                                   key=lambda value: value.astimezone(timezone.utc))}

    @staticmethod
    def _eligible(refs: tuple[str, ...], qualifications: dict) -> bool:
        return all(qualifications[ref].state == "verified" for ref in refs)

    def _candidate_space(self, rules: RuleSet, snapshot: ResourceSnapshot, prepared: dict):
        groups = [prepared["groups"][name] for name in rules.calculation_order]
        resources = [prepared["resources"][name] for name in rules.payment_order]
        count = 1
        for group in groups:
            count *= len(group.options)
        ranges = []
        for resource in resources:
            options = range(0, resource.permitted_max_units + 1, resource.increment_units)
            # A verified not-eligible resource contributes the explicitly legal zero-use option.
            if not self._eligible(resource.eligibility_refs, prepared["eligibility"]):
                options = range(1)
            ranges.append(options)
            count *= len(options)
        if count > self.max_candidates:
            _block("TIMEOUT", "COMPLETE_DOMAIN_EXCEEDS_CONFIGURED_BOUND")
        return groups, resources, ranges, count

    def _evaluate(self, ctx, rules, snapshot, prepared, selected, units) -> dict:
        chosen = {o.rule_id for o in selected}
        for option in selected:
            if (not set(option.requires_rule_ids) <= chosen or set(option.exclusive_rule_ids) & chosen
                    or not self._eligible(option.eligibility_refs, prepared["eligibility"])):
                raise _Rejected("OPTION_CONSTRAINT")
        merchandise = 0
        ledger = []
        with localcontext() as arithmetic:
            arithmetic.prec = 64
            for group_id, option in zip(rules.calculation_order, selected):
                before = merchandise
                if merchandise < option.minimum_spend_minor:
                    raise _Rejected("THRESHOLD")
                if option.operation == "set_base":
                    merchandise = option.value * ctx.quantity
                elif option.operation == "fixed_discount":
                    deduction = option.value if option.cap_minor is None else min(option.value, option.cap_minor)
                    if deduction > merchandise:
                        raise _Rejected("DISCOUNT_EXCEEDS_GOODS")
                    merchandise -= deduction
                elif option.operation == "rate_discount":
                    deduction = _rounded(Decimal(merchandise) * Decimal(option.value), option.rounding_mode)
                    if option.cap_minor is not None:
                        deduction = min(deduction, option.cap_minor)
                    if deduction > merchandise:
                        raise _Rejected("DISCOUNT_EXCEEDS_GOODS")
                    merchandise -= deduction
                _int(merchandise, "COMPUTED_MERCHANDISE")
                ledger.append({"group_id": group_id, "rule_id": option.rule_id,
                               "level_id": prepared["groups"][group_id].level_id,
                               "before_minor": before, "after_minor": merchandise,
                               "customer_reason": option.customer_reason})
            fee = sum(f.amount_minor for f in rules.fees)
            total = _int(merchandise + fee, "COMPUTED_ORDER")
            cash, goods_remaining, consumed = total, merchandise, []
            for ref, used in zip(rules.payment_order, units):
                resource = prepared["resources"][ref]
                if used and (not set(resource.requires_rule_ids) <= chosen or set(resource.exclusive_rule_ids) & chosen):
                    raise _Rejected("RESOURCE_SALES_CONSTRAINT")
                credit = _rounded(Decimal(used) * Decimal(resource.unit_value_minor), resource.rounding_mode)
                allowed = cash if resource.eligible_for_fees else min(cash, goods_remaining)
                if resource.cap_minor is not None:
                    allowed = min(allowed, resource.cap_minor)
                if resource.cap_rate_decimal is not None:
                    allowed = min(allowed, _rounded(Decimal(merchandise) * Decimal(resource.cap_rate_decimal), resource.rounding_mode))
                if credit > allowed:
                    raise _Rejected("PAYMENT_SCOPE_OR_CAP")
                cash -= credit
                # Supported payment allocation explicitly pays goods first, then permitted fees.
                goods_remaining -= min(goods_remaining, credit)
                consumed.append({"resource_ref": ref, "resource_kind": resource.resource_kind,
                                 "unit": resource.unit, "consumed_units": used,
                                 "applied_amount_minor": credit,
                                 "remaining_units": resource.balance_units - used})
        return {
            "selected_rule_ids": tuple(o.rule_id for o in selected), "resource_units": tuple(units),
            "merchandise_total_minor": merchandise, "mandatory_fees_minor": fee,
            "order_total_before_payment_minor": total, "credits_applied_minor": total - cash,
            "cash_due_now_minor": cash, "customer_payable_minor": cash,
            "customer_resource_usage": consumed, "sales_ledger": ledger,
        }

    def solve(self, ctx: QuoteContext, rules: RuleSet, snapshot: ResourceSnapshot) -> QuoteResult:
        try:
            prepared = self._preflight(ctx, rules, snapshot)
            groups, resources, ranges, count = self._candidate_space(rules, snapshot, prepared)
            evaluated, legal, rejection_counts, minima, comparison_rows = 0, 0, {}, [], []
            for selected in itertools.product(*(g.options for g in groups)):
                for units in itertools.product(*ranges):
                    evaluated += 1
                    try:
                        record = self._evaluate(ctx, rules, snapshot, prepared, selected, units)
                    except _Rejected as rejected:
                        reason = str(rejected)
                        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                        continue
                    legal += 1
                    comparison_rows.append(record)
                    if not minima or record["cash_due_now_minor"] < minima[0]["cash_due_now_minor"]:
                        minima = [record]
                    elif record["cash_due_now_minor"] == minima[0]["cash_due_now_minor"]:
                        minima.append(record)
            if evaluated != count:
                _block("SOLVER_ERROR", "INCOMPLETE_ENUMERATION")
            if not minima:
                return QuoteResult("INFEASIBLE_PROVEN", "NO_LEGAL_COMBINATION_IN_COMPLETE_DOMAIN",
                                   synthetic_test_only=self.synthetic_test)
            dependency_hash = _hash((ctx, rules, snapshot))
            quote_ref = "qkernel_" + dependency_hash[:24]
            internal = {
                "quote_ref": quote_ref, "quote_version": dependency_hash,
                "dependency_hash": dependency_hash, "objective": OBJECTIVE,
                "objective_metric": METRIC, "objective_metric_version": METRIC_VERSION,
                "product_ref": ctx.product_ref, "configuration_ref": ctx.configuration_ref,
                "tenant_ref": ctx.tenant_ref, "store_ref": ctx.store_ref, "actor_ref": ctx.actor_ref,
                "quantity": ctx.quantity, "currency": ctx.currency,
                "customer_resource_snapshot_ref": snapshot.snapshot_ref,
                "customer_resource_snapshot_version": snapshot.version,
                "resource_use_scope_ref": snapshot.resource_use_scope_ref,
                "recommendation_set_ref": ctx.recommendation_set_ref,
                "recommendation_set_version": ctx.recommendation_set_version,
                "solver_state": "OPTIMAL_PROVEN", "candidate_manifest_ref": rules.manifest.manifest_ref,
                "coverage": {"expected_candidates": count, "evaluated_candidates": evaluated,
                             "legal_candidates": legal, "rejection_counts": rejection_counts,
                             "complete": True, "sku_count": 1,
                             "cross_sku_comparison_complete": False},
                "four_level_rows": [asdict(prepared["levels"][name]) for name, _ in LEVELS],
                "optimal_candidates": minima, "legal_candidates": comparison_rows,
                "customer_old_asset_summary": [asdict(asset) for asset in snapshot.old_assets],
                "tie_selection_state": "CUSTOMER_CHOICE_REQUIRED" if len(minima) > 1 else "SINGLE_OPTIMAL_PROPOSAL",
                "valid_until": prepared["valid_until"].isoformat(),
                "synthetic_test_only": self.synthetic_test,
                "real_quote_enabled": False,
            }
            return QuoteResult("FEASIBLE_NOT_PROVEN", "PENDING_INDEPENDENT_VALIDATION", quote_ref, internal,
                               synthetic_test_only=self.synthetic_test)
        except _Blocked as blocked:
            return QuoteResult(blocked.status, blocked.reason, synthetic_test_only=self.synthetic_test)

    def validate(self, result: QuoteResult, ctx: QuoteContext, rules: RuleSet,
                 snapshot: ResourceSnapshot) -> QuoteResult:
        """Re-enumerate independently with rational arithmetic, without _evaluate.

        Source authenticity/permissions are still the adapter's responsibility.
        The kernel never promotes a result to customer-releasable VALID_OPTIMAL.
        """
        if not isinstance(result, QuoteResult):
            return QuoteResult("SOLVER_ERROR", "INTERNAL_RESULT_TYPE_REQUIRED", validation_state="FAIL",
                               synthetic_test_only=self.synthetic_test)
        if result.quote_status != "FEASIBLE_NOT_PROVEN" or result.internal_quote is None:
            return replace(result, validation_state="NOT_APPLICABLE")
        try:
            prepared = self._preflight(ctx, rules, snapshot)
            groups, resources, ranges, expected = self._candidate_space(rules, snapshot, prepared)
            q = result.internal_quote
            if type(q) is not dict or result.synthetic_test_only != self.synthetic_test:
                _block("SOLVER_ERROR", "INTERNAL_RESULT_MODE_OR_STRUCTURE_INVALID")
            expected_hash = _hash((ctx, rules, snapshot))
            expected_quote_ref = "qkernel_" + expected_hash[:24]
            if (q.get("dependency_hash") != expected_hash
                    or q.get("quote_ref") != result.quote_ref
                    or result.quote_ref != expected_quote_ref):
                _block("SOLVER_ERROR", "VALIDATION_DEPENDENCY_MISMATCH")
            expected_metadata = {
                "quote_version": expected_hash, "objective": OBJECTIVE,
                "objective_metric": METRIC, "objective_metric_version": METRIC_VERSION,
                "product_ref": ctx.product_ref, "configuration_ref": ctx.configuration_ref,
                "tenant_ref": ctx.tenant_ref, "store_ref": ctx.store_ref, "actor_ref": ctx.actor_ref,
                "quantity": ctx.quantity, "currency": ctx.currency,
                "customer_resource_snapshot_ref": snapshot.snapshot_ref,
                "customer_resource_snapshot_version": snapshot.version,
                "resource_use_scope_ref": snapshot.resource_use_scope_ref,
                "recommendation_set_ref": ctx.recommendation_set_ref,
                "recommendation_set_version": ctx.recommendation_set_version,
                "solver_state": "OPTIMAL_PROVEN", "candidate_manifest_ref": rules.manifest.manifest_ref,
                "synthetic_test_only": self.synthetic_test, "real_quote_enabled": False,
                "four_level_rows": [asdict(prepared["levels"][name]) for name, _ in LEVELS],
                "customer_old_asset_summary": [asdict(asset) for asset in snapshot.old_assets],
                "valid_until": prepared["valid_until"].isoformat(),
            }
            if any(q.get(name) != value for name, value in expected_metadata.items()):
                _block("SOLVER_ERROR", "VALIDATION_METADATA_MISMATCH")
            from fractions import Fraction

            def rational_round(value: Fraction, mode: str) -> int:
                quotient, remainder = divmod(value.numerator, value.denominator)
                if mode == "ROUND_UP":
                    return quotient + bool(remainder)
                if mode == "ROUND_HALF_UP":
                    return quotient + (2 * remainder >= value.denominator)
                return quotient

            # Independent replay uses integer rational arithmetic, not Decimal evaluation.
            expected_legal, expected_minima, traversed = {}, {}, 0
            for options in itertools.product(*(g.options for g in groups)):
                selected_ids = {o.rule_id for o in options}
                for consumptions in itertools.product(*ranges):
                    traversed += 1
                    if any(not set(o.requires_rule_ids) <= selected_ids or set(o.exclusive_rule_ids) & selected_ids
                           or not self._eligible(o.eligibility_refs, prepared["eligibility"]) for o in options):
                        continue
                    goods, valid, ledger = 0, True, []
                    for group_id, o in zip(rules.calculation_order, options):
                        before = goods
                        if goods < o.minimum_spend_minor:
                            valid = False
                            break
                        if o.operation == "set_base":
                            goods = o.value * ctx.quantity
                        elif o.operation in {"fixed_discount", "rate_discount"}:
                            discount = (o.value if o.operation == "fixed_discount" else
                                        rational_round(Fraction(goods) * Fraction(o.value), o.rounding_mode))
                            if o.cap_minor is not None:
                                discount = min(discount, o.cap_minor)
                            if discount > goods:
                                valid = False
                                break
                            goods -= discount
                        ledger.append({"group_id": group_id, "rule_id": o.rule_id,
                                       "level_id": prepared["groups"][group_id].level_id,
                                       "before_minor": before, "after_minor": goods,
                                       "customer_reason": o.customer_reason})
                    if not valid:
                        continue
                    fees = sum(f.amount_minor for f in rules.fees)
                    unpaid, goods_left, usage = goods + fees, goods, []
                    for r, used in zip(resources, consumptions):
                        if used and (not set(r.requires_rule_ids) <= selected_ids or set(r.exclusive_rule_ids) & selected_ids):
                            valid = False
                            break
                        value = rational_round(Fraction(used) * Fraction(r.unit_value_minor), r.rounding_mode)
                        cap = unpaid if r.eligible_for_fees else min(unpaid, goods_left)
                        if r.cap_minor is not None:
                            cap = min(cap, r.cap_minor)
                        if r.cap_rate_decimal is not None:
                            cap = min(cap, rational_round(Fraction(goods) * Fraction(r.cap_rate_decimal), r.rounding_mode))
                        if value > cap:
                            valid = False
                            break
                        unpaid -= value
                        goods_left -= min(goods_left, value)
                        usage.append({"resource_ref": r.resource_ref, "resource_kind": r.resource_kind,
                                      "unit": r.unit, "consumed_units": used, "applied_amount_minor": value,
                                      "remaining_units": r.balance_units - used})
                    if not valid:
                        continue
                    record = {"selected_rule_ids": tuple(o.rule_id for o in options),
                              "resource_units": tuple(consumptions), "merchandise_total_minor": goods,
                              "mandatory_fees_minor": fees, "order_total_before_payment_minor": goods + fees,
                              "credits_applied_minor": goods + fees - unpaid,
                              "cash_due_now_minor": unpaid, "customer_payable_minor": unpaid,
                              "customer_resource_usage": usage, "sales_ledger": ledger}
                    key = (record["selected_rule_ids"], record["resource_units"])
                    expected_legal[key] = record
                    if not expected_minima or unpaid < next(iter(expected_minima.values()))["cash_due_now_minor"]:
                        expected_minima = {key: record}
                    elif unpaid == next(iter(expected_minima.values()))["cash_due_now_minor"]:
                        expected_minima[key] = record

            def keyed(records):
                mapped = {(tuple(r["selected_rule_ids"]), tuple(r["resource_units"])): r for r in records}
                if len(mapped) != len(records):
                    _block("SOLVER_ERROR", "DUPLICATE_REPLAY_RECORD")
                return mapped

            if (traversed != expected or q["coverage"]["expected_candidates"] != expected
                    or q["coverage"]["evaluated_candidates"] != expected
                    or q["coverage"]["legal_candidates"] != len(expected_legal)
                    or q["coverage"]["complete"] is not True
                    or q["coverage"]["sku_count"] != 1
                    or q["coverage"]["cross_sku_comparison_complete"] is not False
                    or sum(q["coverage"]["rejection_counts"].values()) != expected - len(expected_legal)
                    or keyed(q["legal_candidates"]) != expected_legal
                    or keyed(q["optimal_candidates"]) != expected_minima):
                _block("SOLVER_ERROR", "INDEPENDENT_REPLAY_OR_OPTIMUM_MISMATCH")
            if q["tie_selection_state"] != ("CUSTOMER_CHOICE_REQUIRED" if len(expected_minima) > 1 else "SINGLE_OPTIMAL_PROPOSAL"):
                _block("SOLVER_ERROR", "TIE_SELECTION_STATE_MISMATCH")
            validated = dict(q)
            validated["validation_ref"] = "qvalidation_" + _hash((q["dependency_hash"], list(expected_minima.values())))[:24]
            validated["kernel_validation_state"] = "VALIDATED_OPTIMAL_CORE"
            return replace(result, reason="SYNTHETIC_TEST_ONLY" if self.synthetic_test else "CORE_VALIDATED_NOT_RELEASED",
                           internal_quote=validated, validation_state="PASS")
        except _Blocked as blocked:
            return QuoteResult(blocked.status, blocked.reason, result.quote_ref,
                               validation_state="FAIL", synthetic_test_only=self.synthetic_test)
        except (KeyError, TypeError, ValueError):
            return QuoteResult("SOLVER_ERROR", "MALFORMED_INTERNAL_REPLAY_RECORD", result.quote_ref,
                               validation_state="FAIL", synthetic_test_only=self.synthetic_test)

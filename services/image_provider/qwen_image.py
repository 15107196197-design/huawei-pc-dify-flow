"""Qwen Image 3.0 Pro adapter contract, verified against Alibaba docs 2026-10-18.

Official reference, actually browsed while implementing:
https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference

Strict supported subset: DashScope synchronous multimodal generation, Beijing
workspace endpoint, qwen-image-3.0-pro, text-to-image or 1-3 authorized PNG byte
references, direct prompting, explicit size/seed/n. This is NOT /images/edits.
PNG-only input is our subset; the provider supports additional input formats.
No SDK, default network transport, file IO, URL fetching, polling or cloud
resource creation is included. A reviewed server transport must be injected.

Policies/credentials MUST come from trusted server authentication and destination
approval, not user JSON or LLM claims. A Python dataclass and its Boolean flags
do not establish authorization. Exact request fingerprints bind approvals to
payloads; the parent service must validate/revoke approvals and authenticate the
tenant/actor. Key-region metadata is server-attested, not inferred from key text.

Outputs are unreviewed AI artifact candidates. They never become ima originals,
licensed assets, visually approved files or export-ready posters. No Dify bridge
is wired here, no live key is bundled, and tests only inject simulated transport.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
import struct
from typing import Callable, Optional, Protocol
from urllib.parse import urlsplit
import zlib


MODEL = "qwen-image-3.0-pro"
PROVIDER = "aliyun_bailian"
REGION = "cn-beijing"
API_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
REFERENCE_URL = "https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference"
MAX_REFERENCE_BYTES = 10_000_000  # conservative decimal MB limit
MAX_RESPONSE_BYTES = 1_000_000
DEFAULT_RESULT_HOST = "dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com"
BACKGROUND_INSTRUCTION = (
    "Generate a decorative background only. Do not depict or redraw products, "
    "product specifications, logos, brand marks, prices or promotional claims. "
    "Leave clear space for later deterministic composition with authorized original assets.\n"
)


@dataclass(frozen=True)
class ReferenceImage:
    asset_ref: str
    content_bytes: bytes = field(repr=False)
    mime_type: str = "image/png"
    contains_product: bool = True  # conservative; metadata is not a vision check
    source_kind: str = "unverified"


@dataclass(frozen=True)
class ImageRequest:
    task_ref: str
    task_version: str
    operation: str  # text_to_image / image_edit
    purpose: str  # background_without_product / authorized_reference_edit
    prompt: str = field(repr=False)
    references: tuple[ReferenceImage, ...] = field(default=(), repr=False)
    size: Optional[tuple[int, int]] = (1024, 1024)
    n: int = 1
    seed: Optional[int] = None
    negative_prompt: str = field(default="", repr=False)
    prompt_extend: bool = False
    enable_thinking: bool = False
    watermark: bool = True


@dataclass(frozen=True)
class ImagePolicy:
    tenant_ref: str
    actor_ref: str
    task_ref: str
    task_version: str
    mode: str  # concept_preview / creative_authorized / competition_strict
    authorization_ref: str
    request_fingerprint: str
    valid_from: datetime
    valid_until: datetime
    purpose_ref: str
    destination_ref: str
    provider: str
    model: str
    region: str
    allow_generation: bool = False
    allow_prompt_disclosure: bool = False
    allow_reference_upload: bool = False
    allow_product_reference_upload: bool = False
    approved_asset_hashes: tuple[tuple[str, str], ...] = ()
    max_output_images: int = 1


@dataclass(frozen=True)
class ProviderConfig:
    workspace_id: str
    credential_region: str
    api_key: Optional[str] = field(default=None, repr=False)
    region: str = REGION
    model: str = MODEL
    destination_ref: str = "aliyun_bailian_qwen_image_cn_beijing"
    enabled: bool = False
    live_calls_enabled: bool = False
    contract_test_mode: bool = False
    timeout_seconds: int = 600
    allowed_result_hosts: tuple[str, ...] = (DEFAULT_RESULT_HOST,)


@dataclass(frozen=True)
class ProviderRequest:
    url: str
    headers: dict = field(repr=False)
    json_body: dict = field(repr=False)
    method: str = "POST"


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    json_body: dict = field(repr=False)
    headers: dict = field(default_factory=dict, repr=False)


class Transport(Protocol):
    """Reviewed server code, never user-selected URLs or an arbitrary model tool.

    Implementations must honor socket timeout, bounded JSON response size,
    cancellation checks and no redirects. A cancelled wait cannot promise remote
    generation cancellation. ``is_simulated`` is a test assertion, not security.
    """

    is_simulated: bool

    def send(self, request: ProviderRequest, *, timeout_seconds: int,
             cancelled: Callable[[], bool]) -> TransportResponse: ...


@dataclass(frozen=True)
class ArtifactCandidate:
    artifact_ref: str
    remote_url: str = field(repr=False)  # server-internal signed URL; never auto-fetch
    provider: str = PROVIDER
    model: str = MODEL
    provenance: str = "ai_generated_candidate"
    rights_status: str = "UNVERIFIED"
    visual_review_status: str = "NOT_RUN"
    export_allowed: bool = False
    provider_url_ttl_hint_seconds: int = 86400
    exact_expiry_verified: bool = False

    def safe_view(self) -> dict:
        return {
            "artifact_ref": self.artifact_ref, "provider": self.provider, "model": self.model,
            "provenance": self.provenance, "rights_status": self.rights_status,
            "visual_review_status": self.visual_review_status, "export_allowed": False,
            "provider_url_ttl_hint_seconds": self.provider_url_ttl_hint_seconds,
            "exact_expiry_verified": False,
        }


@dataclass(frozen=True)
class ImageResult:
    status: str
    reason: str
    artifacts: tuple[ArtifactCandidate, ...] = field(default=(), repr=False)
    request_id: Optional[str] = None
    usage: Optional[dict] = None
    provider_error_code: Optional[str] = None
    provider_http_status: Optional[int] = None
    remote_execution_state: str = "NOT_SUBMITTED"
    contract_test_only: bool = False

    def safe_view(self) -> dict:
        return {
            "status": self.status, "reason": self.reason,
            "artifact_candidates": [artifact.safe_view() for artifact in self.artifacts],
            "request_id": self.request_id, "usage": self.usage,
            "provider_error_code": self.provider_error_code,
            "provider_http_status": self.provider_http_status,
            "remote_execution_state": self.remote_execution_state,
            "contract_test_only": self.contract_test_only,
            "integration_state": "ADAPTER_ONLY_DIFY_BRIDGE_NOT_CONNECTED",
            "export_allowed": False, "visual_review_status": "NOT_RUN",
        }


class _Rejected(Exception):
    def __init__(self, status: str, reason: str):
        self.status, self.reason = status, reason


def _reject(status: str, reason: str) -> None:
    raise _Rejected(status, reason)


def _token(value: object, *, secret: Optional[str] = None) -> Optional[str]:
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value)
            or (secret and secret in value)):
        return None
    return value


def _period(start: object, end: object, now: object) -> None:
    if any(not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() is None for d in (start, end, now)):
        _reject("denied", "APPROVAL_AWARE_DATETIME_REQUIRED")
    if not start.astimezone(timezone.utc) <= now.astimezone(timezone.utc) < end.astimezone(timezone.utc):
        _reject("denied", "APPROVAL_EXPIRED_OR_NOT_YET_VALID")


def _png_dimensions(data: bytes) -> tuple[int, int]:
    # Inspect signature and a CRC-checked IHDR only; do not claim a full decode.
    if (type(data) is not bytes or len(data) < 45 or len(data) > MAX_REFERENCE_BYTES
            or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[8:16] != b"\x00\x00\x00\rIHDR"):
        _reject("error", "REFERENCE_PNG_HEADER_OR_SIZE_INVALID")
    if zlib.crc32(data[12:29]) & 0xFFFFFFFF != struct.unpack(">I", data[29:33])[0]:
        _reject("error", "REFERENCE_PNG_IHDR_CRC_INVALID")
    width, height = struct.unpack(">II", data[16:24])
    if not (1 <= width <= 8000 and 1 <= height <= 8000) or max(width, height) > 10 * min(width, height):
        _reject("error", "REFERENCE_DIMENSIONS_OUT_OF_RANGE")
    return width, height


class QwenImageProvider:
    def __init__(self, config: ProviderConfig, transport: Optional[Transport] = None,
                 *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if type(config) is not ProviderConfig:
            raise ValueError("typed server ProviderConfig required")
        self.config, self.transport, self.clock = config, transport, clock

    @staticmethod
    def fingerprint(request: ImageRequest) -> str:
        """A server approval service may bind an exact validated request to policy."""
        if not isinstance(request, ImageRequest):
            raise ValueError("typed ImageRequest required")
        data = {
            "task_ref": request.task_ref, "task_version": request.task_version,
            "operation": request.operation, "purpose": request.purpose, "prompt": request.prompt,
            "references": [{"asset_ref": ref.asset_ref, "sha256": hashlib.sha256(ref.content_bytes).hexdigest(),
                            "mime_type": ref.mime_type, "contains_product": ref.contains_product,
                            "source_kind": ref.source_kind} for ref in request.references],
            "size": request.size, "n": request.n, "seed": request.seed,
            "negative_prompt": request.negative_prompt, "prompt_extend": request.prompt_extend,
            "enable_thinking": request.enable_thinking, "watermark": request.watermark,
            "adapter_model": MODEL, "adapter_contract": "dashscope_sync_direct_v1",
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def _prepare(self, request: ImageRequest, policy: ImagePolicy) -> ProviderRequest:
        cfg = self.config
        if not isinstance(cfg, ProviderConfig) or not isinstance(request, ImageRequest) or not isinstance(policy, ImagePolicy):
            _reject("denied", "SERVER_TYPED_POLICY_AND_CONFIG_REQUIRED")
        if policy.mode == "competition_strict":
            _reject("denied", "COMPETITION_STRICT_IMA_ORIGINALS_REQUIRED")
        if policy.mode not in {"concept_preview", "creative_authorized"}:
            _reject("denied", "GENERATION_MODE_NOT_AUTHORIZED")
        if policy.allow_generation is not True or policy.allow_prompt_disclosure is not True:
            _reject("denied", "GENERATION_OR_PROMPT_DISCLOSURE_NOT_AUTHORIZED")
        if any(not isinstance(v, str) or not v.strip() for v in (
                policy.tenant_ref, policy.actor_ref, policy.authorization_ref, policy.purpose_ref,
                policy.destination_ref, request.task_ref, request.task_version)):
            _reject("denied", "AUTHORIZATION_SCOPE_MISSING")
        _period(policy.valid_from, policy.valid_until, self.clock())
        if (request.task_ref, request.task_version) != (policy.task_ref, policy.task_version):
            _reject("denied", "TASK_VERSION_NOT_AUTHORIZED")
        if (cfg.region, cfg.credential_region, policy.region) != (REGION, REGION, REGION):
            _reject("denied", "MODEL_ENDPOINT_KEY_REGION_MISMATCH")
        if cfg.model != MODEL or (policy.provider, policy.model) != (PROVIDER, MODEL):
            _reject("denied", "PROVIDER_OR_MODEL_NOT_AUTHORIZED")
        if not cfg.destination_ref or policy.destination_ref != cfg.destination_ref:
            _reject("denied", "DESTINATION_NOT_AUTHORIZED")
        if not isinstance(cfg.workspace_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", cfg.workspace_id):
            _reject("error", "WORKSPACE_ID_INVALID")
        if cfg.enabled is not True:
            _reject("error", "PROVIDER_DISABLED")
        if type(cfg.timeout_seconds) is not int or not 1 <= cfg.timeout_seconds <= 1200:
            _reject("error", "CLIENT_TIMEOUT_INVALID")
        if (type(cfg.allowed_result_hosts) is not tuple or not cfg.allowed_result_hosts
                or any(type(host) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.aliyuncs\.com", host)
                       for host in cfg.allowed_result_hosts)):
            _reject("error", "RESULT_HOST_ALLOWLIST_INVALID")
        if type(cfg.contract_test_mode) is not bool or type(cfg.live_calls_enabled) is not bool:
            _reject("error", "CALL_MODE_INVALID")
        if cfg.contract_test_mode:
            if cfg.live_calls_enabled or self.transport is None or getattr(self.transport, "is_simulated", None) is not True:
                _reject("denied", "CONTRACT_TEST_REQUIRES_SIMULATED_TRANSPORT_ONLY")
            key = "synthetic-contract-test-key-not-a-live-credential"
        else:
            if not isinstance(cfg.api_key, str) or not cfg.api_key.strip():
                _reject("error", "CREDENTIALS_NOT_CONFIGURED")
            if any(char.isspace() for char in cfg.api_key):
                _reject("error", "CREDENTIAL_FORMAT_INVALID")
            if not cfg.live_calls_enabled:
                _reject("denied", "LIVE_CALLS_NOT_ENABLED")
            if self.transport is None:
                _reject("error", "REVIEWED_TRANSPORT_NOT_CONFIGURED")
            if getattr(self.transport, "is_simulated", None) is not False:
                _reject("denied", "LIVE_MODE_REQUIRES_REVIEWED_LIVE_TRANSPORT")
            key = cfg.api_key
        if type(request.prompt) is not str or not request.prompt.strip() or len(request.prompt) > 18000:
            _reject("error", "PROMPT_EMPTY_OR_ADAPTER_CHARACTER_LIMIT_EXCEEDED")
        if type(request.negative_prompt) is not str or len(request.negative_prompt) > 18000:
            _reject("error", "NEGATIVE_PROMPT_INVALID")
        if type(request.n) is not int or not 1 <= request.n <= 6:
            _reject("error", "OUTPUT_COUNT_OUT_OF_RANGE")
        if type(policy.max_output_images) is not int or not 1 <= policy.max_output_images <= 6 or request.n > policy.max_output_images:
            _reject("denied", "OUTPUT_COUNT_EXCEEDS_APPROVAL")
        if request.seed is not None and (type(request.seed) is not int or not 0 <= request.seed <= 2147483647):
            _reject("error", "SEED_OUT_OF_RANGE")
        if any(type(v) is not bool for v in (request.prompt_extend, request.enable_thinking, request.watermark)):
            _reject("error", "BOOLEAN_PARAMETER_REQUIRED")
        if request.enable_thinking and not request.prompt_extend:
            _reject("error", "THINKING_REQUIRES_PROMPT_EXTEND")
        if type(request.references) is not tuple or any(type(ref) is not ReferenceImage for ref in request.references):
            _reject("denied", "SERVER_REFERENCE_OBJECTS_REQUIRED")
        if request.operation == "text_to_image":
            if request.references or request.purpose != "background_without_product":
                _reject("denied", "TEXT_MODE_RESTRICTED_TO_BACKGROUND_WITHOUT_REFERENCE")
        elif request.operation == "image_edit":
            if not 1 <= len(request.references) <= 3 or request.purpose != "authorized_reference_edit":
                _reject("error", "EDIT_REQUIRES_ONE_TO_THREE_AUTHORIZED_REFERENCES")
            if policy.allow_reference_upload is not True:
                _reject("denied", "REFERENCE_UPLOAD_NOT_AUTHORIZED")
        else:
            _reject("error", "UNSUPPORTED_OPERATION")
        if request.size is not None:
            if (type(request.size) is not tuple or len(request.size) != 2
                    or any(type(v) is not int or v <= 0 for v in request.size)):
                _reject("error", "OUTPUT_SIZE_INVALID")
            width, height = request.size
            if not 512 * 512 <= width * height <= 2048 * 2048 or max(width, height) > 8 * min(width, height):
                _reject("error", "OUTPUT_SIZE_OUT_OF_RANGE")
        approved = dict(policy.approved_asset_hashes)
        if len(approved) != len(policy.approved_asset_hashes):
            _reject("denied", "DUPLICATE_REFERENCE_APPROVAL")
        content = []
        for ref in request.references:
            if not ref.asset_ref or type(ref.contains_product) is not bool:
                _reject("denied", "REFERENCE_METADATA_INVALID")
            if ref.source_kind not in {"ima_original", "user_authorized", "licensed_reference", "synthetic_fixture"}:
                _reject("denied", "REFERENCE_PROVENANCE_UNVERIFIED")
            if ref.contains_product and policy.allow_product_reference_upload is not True:
                _reject("denied", "PRODUCT_REFERENCE_DISCLOSURE_NOT_AUTHORIZED")
            if ref.mime_type != "image/png":
                _reject("error", "ADAPTER_SUPPORTS_PNG_REFERENCES_ONLY")
            _png_dimensions(ref.content_bytes)
            if approved.get(ref.asset_ref) != hashlib.sha256(ref.content_bytes).hexdigest():
                _reject("denied", "EXACT_REFERENCE_BYTES_NOT_AUTHORIZED")
            content.append({"image": "data:image/png;base64," + base64.b64encode(ref.content_bytes).decode("ascii")})
        if policy.request_fingerprint != self.fingerprint(request):
            _reject("denied", "EXACT_REQUEST_NOT_AUTHORIZED")
        text = BACKGROUND_INSTRUCTION + request.prompt if request.operation == "text_to_image" else request.prompt
        content.append({"text": text})
        parameters = {"n": request.n, "prompt_extend": request.prompt_extend,
                      "prompt_extend_mode": "direct", "enable_thinking": request.enable_thinking,
                      "watermark": request.watermark}
        if request.size is not None:
            parameters["size"] = f"{request.size[0]}*{request.size[1]}"
        if request.seed is not None:
            parameters["seed"] = request.seed
        if request.negative_prompt:
            parameters["negative_prompt"] = request.negative_prompt
        return ProviderRequest(
            url=f"https://{cfg.workspace_id}.cn-beijing.maas.aliyuncs.com" + API_PATH,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
            json_body={"model": MODEL, "input": {"messages": [{"role": "user", "content": content}]},
                       "parameters": parameters},
        )

    def _artifact_url(self, value: object) -> str:
        if not isinstance(value, str) or len(value) > 16000 or any(ord(char) < 33 for char in value):
            _reject("error", "PROVIDER_ARTIFACT_URL_REJECTED")
        if self.config.api_key and self.config.api_key in value:
            _reject("error", "PROVIDER_ARTIFACT_URL_REJECTED")
        try:
            url = urlsplit(value)
            host, port = url.hostname, url.port
        except ValueError:
            _reject("error", "PROVIDER_ARTIFACT_URL_REJECTED")
        if (url.scheme != "https" or url.username or url.password or not host or port not in {None, 443}
                or url.fragment or host not in self.config.allowed_result_hosts or "%" in host):
            _reject("error", "PROVIDER_ARTIFACT_URL_REJECTED")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if host == "localhost" or not host.endswith(".aliyuncs.com"):
                _reject("error", "PROVIDER_ARTIFACT_URL_REJECTED")
        else:
            _reject("error", "PROVIDER_ARTIFACT_URL_REJECTED")
        return value

    def _response_request_id(self, response: object) -> Optional[str]:
        if type(response) is not TransportResponse or type(response.json_body) is not dict or type(response.headers) is not dict:
            return None
        request_id = _token(response.json_body.get("request_id"), secret=self.config.api_key)
        if request_id:
            return request_id
        return _token(next((v for k, v in response.headers.items() if str(k).lower() == "x-request-id"), None),
                      secret=self.config.api_key)

    def _parse(self, response: TransportResponse, request: ImageRequest) -> ImageResult:
        if (type(response) is not TransportResponse or type(response.status_code) is not int
                or type(response.json_body) is not dict or type(response.headers) is not dict):
            _reject("error", "MALFORMED_PROVIDER_RESPONSE")
        try:
            if len(json.dumps(response.json_body, allow_nan=False).encode()) > MAX_RESPONSE_BYTES:
                _reject("error", "PROVIDER_RESPONSE_TOO_LARGE")
        except (TypeError, ValueError):
            _reject("error", "MALFORMED_PROVIDER_RESPONSE")
        body = response.json_body
        request_id = self._response_request_id(response)
        if response.status_code != 200 or body.get("code") or body.get("error"):
            return ImageResult("error", "PROVIDER_REJECTED_REQUEST", request_id=request_id,
                               provider_error_code=_token(body.get("code"), secret=self.config.api_key),
                               provider_http_status=response.status_code,
                               remote_execution_state="PROVIDER_ERROR_RESPONSE",
                               contract_test_only=self.config.contract_test_mode)
        if request_id is None:
            _reject("error", "PROVIDER_REQUEST_ID_MISSING_OR_UNSAFE")
        output, usage = body.get("output"), body.get("usage")
        if not isinstance(output, dict) or not isinstance(output.get("choices"), list) or not output["choices"]:
            _reject("error", "MALFORMED_PROVIDER_OUTPUT")
        urls = []
        for choice in output["choices"]:
            if (not isinstance(choice, dict) or choice.get("finish_reason") != "stop"
                    or not isinstance(choice.get("message"), dict)):
                _reject("error", "PROVIDER_FINISH_NOT_COMPLETE")
            message = choice["message"]
            if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
                _reject("error", "MALFORMED_PROVIDER_OUTPUT")
            for item in message["content"]:
                if not isinstance(item, dict) or set(item) != {"image"}:
                    _reject("error", "UNSUPPORTED_PROVIDER_OUTPUT_CONTENT")
                urls.append(self._artifact_url(item["image"]))
        if len(urls) != request.n or len(set(urls)) != len(urls):
            _reject("error", "PROVIDER_IMAGE_COUNT_MISMATCH")
        integer_fields = ("output_width", "output_height", "input_image_count", "output_image_count")
        if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in integer_fields):
            _reject("error", "PROVIDER_USAGE_MISSING_OR_INVALID")
        width, height = usage["output_width"], usage["output_height"]
        if (not 512 * 512 <= width * height <= 2048 * 2048 or min(width, height) < 1
                or max(width, height) > 8 * min(width, height)
                or usage["input_image_count"] != len(request.references) or usage["output_image_count"] != len(urls)):
            _reject("error", "PROVIDER_USAGE_INCONSISTENT")
        if request.size is not None and (width, height) != request.size:
            _reject("error", "PROVIDER_OUTPUT_SIZE_MISMATCH")
        approved_usage = {key: usage[key] for key in integer_fields}
        for key, allowed in (("input_image_type", {"qima_input_1k", "qima_input_2k"}),
                             ("output_image_type", {"qima_output_1k", "qima_output_2k"})):
            if usage.get(key) not in allowed:
                _reject("error", "PROVIDER_USAGE_MISSING_OR_INVALID")
            approved_usage[key] = usage[key]
        tier = "1k" if width * height <= 2_250_000 else "2k"
        if (usage["input_image_type"] != "qima_input_" + tier
                or usage["output_image_type"] != "qima_output_" + tier):
            _reject("error", "PROVIDER_USAGE_TIER_INCONSISTENT")
        fingerprint = self.fingerprint(request)
        artifacts = tuple(ArtifactCandidate("qwen_candidate_" + hashlib.sha256(
            f"{fingerprint}:{request_id}:{index}:{url}".encode()).hexdigest()[:24], url)
                          for index, url in enumerate(urls))
        return ImageResult("ready", "UNREVIEWED_ARTIFACT_CANDIDATES_ONLY", artifacts, request_id,
                           approved_usage, provider_http_status=response.status_code,
                           remote_execution_state="SYNC_RESPONSE_RECEIVED",
                           contract_test_only=self.config.contract_test_mode)

    def generate(self, request: ImageRequest, policy: ImagePolicy,
                 *, cancelled: Callable[[], bool] = lambda: False) -> ImageResult:
        submitted = False
        response = None
        try:
            if cancelled():
                return ImageResult("cancelled", "CANCELLED_BEFORE_SUBMISSION",
                                   contract_test_only=self.config.contract_test_mode)
            prepared = self._prepare(request, policy)
            if cancelled():
                return ImageResult("cancelled", "CANCELLED_BEFORE_SUBMISSION",
                                   contract_test_only=self.config.contract_test_mode)
            submitted = True
            response = self.transport.send(prepared, timeout_seconds=self.config.timeout_seconds, cancelled=cancelled)
            if cancelled():
                return ImageResult("cancelled", "CANCELLED_WAITING_REMOTE_STATE_UNKNOWN",
                                   request_id=self._response_request_id(response),
                                   remote_execution_state="UNKNOWN_MAY_STILL_RUN_OR_BE_CHARGED",
                                   contract_test_only=self.config.contract_test_mode)
            _period(policy.valid_from, policy.valid_until, self.clock())
            return self._parse(response, request)
        except _Rejected as rejected:
            return ImageResult(rejected.status, rejected.reason,
                               request_id=self._response_request_id(response),
                               remote_execution_state="RESPONSE_UNUSABLE" if submitted else "NOT_SUBMITTED",
                               contract_test_only=self.config.contract_test_mode)
        except TimeoutError:
            return ImageResult("timeout", "WAIT_TIMEOUT_REMOTE_STATE_UNKNOWN",
                               remote_execution_state="UNKNOWN_MAY_STILL_RUN_OR_BE_CHARGED" if submitted else "NOT_SUBMITTED",
                               contract_test_only=self.config.contract_test_mode)
        except Exception:
            # Never reflect transport exception strings: they may contain keys or input data.
            return ImageResult("error", "TRANSPORT_OR_INTERNAL_ERROR_REDACTED",
                               remote_execution_state="UNKNOWN_MAY_STILL_RUN_OR_BE_CHARGED" if submitted else "NOT_SUBMITTED",
                               contract_test_only=self.config.contract_test_mode)

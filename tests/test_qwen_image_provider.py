"""Offline adapter contracts only: no API key, network, model billing or images.

Tiny PNGs and provider responses are synthetic test fixtures. No result is a
live Qwen output, an ima original, a licensed reference or an exportable poster.
"""

import base64
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import struct
import unittest
import zlib
from zoneinfo import ZoneInfo

from services.image_provider import (
    ArtifactCandidate, ImagePolicy, ImageRequest, ProviderConfig, QwenImageProvider,
    ReferenceImage, TransportResponse,
)
from services.image_provider.qwen_image import API_PATH, DEFAULT_RESULT_HOST, MODEL, PROVIDER


NOW = datetime(2026, 10, 18, 10, tzinfo=timezone.utc)


def tiny_png(width=1, height=1):
    """Synthetic PNG bytes, never read a user's reference or image file."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    # Tests of dimension limits intentionally inspect header only, not decode.
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff\xff")) + chunk(b"IEND", b""))


def response(n=1, inputs=0, width=1024, height=1024):
    tier = "1k" if width * height <= 2_250_000 else "2k"
    return TransportResponse(200, {
        "request_id": "synthetic-provider-request-id",
        "output": {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": [
            {"image": f"https://{DEFAULT_RESULT_HOST}/synthetic-{i}.png?Expires=example&Signature=synthetic"}
            for i in range(n)]}}]},
        "usage": {"output_width": width, "output_height": height,
                  "input_image_count": inputs, "input_image_type": "qima_input_" + tier,
                  "output_image_count": n, "output_image_type": "qima_output_" + tier},
    })


class FakeTransport:
    is_simulated = True

    def __init__(self, result=None, failure=None, after_send=None):
        self.result = result or response()
        self.failure, self.after_send, self.calls = failure, after_send, []

    def send(self, request, *, timeout_seconds, cancelled):
        self.calls.append((request, timeout_seconds))
        if self.after_send:
            self.after_send()
        if self.failure:
            raise self.failure
        return self.result


def base_request():
    return ImageRequest("synthetic-image-task", "1", "text_to_image", "background_without_product",
                        "Abstract pale blue and white background with blank composition space.")


def approval(request, **changes):
    values = dict(tenant_ref="synthetic-tenant", actor_ref="synthetic-actor", task_ref=request.task_ref,
                  task_version=request.task_version, mode="concept_preview",
                  authorization_ref="synthetic-approval-not-live-permission",
                  request_fingerprint=QwenImageProvider.fingerprint(request),
                  valid_from=NOW - timedelta(minutes=5), valid_until=NOW + timedelta(minutes=5),
                  purpose_ref="synthetic-concept-review", destination_ref="aliyun_bailian_qwen_image_cn_beijing",
                  provider=PROVIDER, model=MODEL, region="cn-beijing",
                  allow_generation=True, allow_prompt_disclosure=True)
    values.update(changes)
    return ImagePolicy(**values)


def config(**changes):
    values = dict(workspace_id="synthetic-workspace", credential_region="cn-beijing",
                  enabled=True, contract_test_mode=True)
    values.update(changes)
    return ProviderConfig(**values)


class QwenImageProviderTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.request = base_request()
        self.policy = approval(self.request)
        self.provider = QwenImageProvider(config(), self.transport, clock=lambda: NOW)

    def run_request(self, request=None, policy=None, provider=None):
        return (provider or self.provider).generate(request or self.request, policy or self.policy)

    def edit(self, *, contains_product=True, source_kind="ima_original", count=1):
        refs = tuple(ReferenceImage(f"synthetic-reference-{i}", tiny_png(), contains_product=contains_product,
                                    source_kind=source_kind) for i in range(count))
        request = replace(self.request, operation="image_edit", purpose="authorized_reference_edit", references=refs)
        policy = approval(request, mode="creative_authorized", allow_reference_upload=True,
                          allow_product_reference_upload=True,
                          approved_asset_hashes=tuple((r.asset_ref, hashlib.sha256(r.content_bytes).hexdigest()) for r in refs))
        return request, policy

    def test_text_to_image_uses_official_dashscope_endpoint_and_structure(self):
        result = self.run_request()
        self.assertEqual(result.status, "ready")
        outbound, timeout = self.transport.calls[0]
        self.assertEqual(outbound.method, "POST")
        self.assertEqual(outbound.url, "https://synthetic-workspace.cn-beijing.maas.aliyuncs.com" + API_PATH)
        self.assertNotIn("images/edits", outbound.url)
        self.assertEqual(outbound.json_body["model"], MODEL)
        messages = outbound.json_body["input"]["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(list(messages[0]["content"][0]), ["text"])
        self.assertIn("background only", messages[0]["content"][0]["text"])
        self.assertEqual(outbound.json_body["parameters"]["size"], "1024*1024")
        self.assertEqual(timeout, 600)
        self.assertEqual(outbound.headers["Content-Type"], "application/json")

    def test_no_actual_key_no_live_transport_call(self):
        provider = QwenImageProvider(config(contract_test_mode=False, live_calls_enabled=True),
                                     self.transport, clock=lambda: NOW)
        result = self.run_request(provider=provider)
        self.assertEqual(result.reason, "CREDENTIALS_NOT_CONFIGURED")
        self.assertEqual(self.transport.calls, [])

    def test_disabled_or_missing_reviewed_transport_does_not_call(self):
        disabled = QwenImageProvider(config(enabled=False), self.transport, clock=lambda: NOW)
        self.assertEqual(self.run_request(provider=disabled).reason, "PROVIDER_DISABLED")
        no_transport = QwenImageProvider(config(), clock=lambda: NOW)
        self.assertEqual(self.run_request(provider=no_transport).reason, "CONTRACT_TEST_REQUIRES_SIMULATED_TRANSPORT_ONLY")
        self.assertEqual(self.transport.calls, [])

    def test_simulation_cannot_be_used_as_live_or_with_live_flag(self):
        provider = QwenImageProvider(config(live_calls_enabled=True), self.transport, clock=lambda: NOW)
        self.assertEqual(self.run_request(provider=provider).reason, "CONTRACT_TEST_REQUIRES_SIMULATED_TRANSPORT_ONLY")
        provider = QwenImageProvider(config(contract_test_mode=False, live_calls_enabled=True, api_key="synthetic-not-live-key"),
                                     self.transport, clock=lambda: NOW)
        self.assertEqual(self.run_request(provider=provider).reason, "LIVE_MODE_REQUIRES_REVIEWED_LIVE_TRANSPORT")
        self.assertEqual(self.transport.calls, [])

    def test_competition_strict_cannot_replace_ima_images(self):
        result = self.run_request(policy=replace(self.policy, mode="competition_strict"))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.reason, "COMPETITION_STRICT_IMA_ORIGINALS_REQUIRED")
        self.assertEqual(self.transport.calls, [])

    def test_generation_prompt_and_destination_permissions_are_independent(self):
        for changes in [dict(allow_generation=False), dict(allow_prompt_disclosure=False),
                        dict(destination_ref="another-destination"), dict(model="another-model"),
                        dict(provider="another-provider"), dict(region="ap-southeast-1")]:
            with self.subTest(changes=changes):
                self.assertEqual(self.run_request(policy=replace(self.policy, **changes)).status, "denied")
        self.assertEqual(self.transport.calls, [])

    def test_key_endpoint_model_regions_must_match(self):
        for cfg in [config(region="ap-southeast-1"), config(credential_region="ap-southeast-1"),
                    config(model="qwen-image-3.0"), config(workspace_id="evil.example/credential")]:
            provider = QwenImageProvider(cfg, self.transport, clock=lambda: NOW)
            self.assertNotEqual(self.run_request(provider=provider).status, "ready")
        self.assertEqual(self.transport.calls, [])

    def test_exact_payload_and_task_version_are_bound_to_approval(self):
        changed = replace(self.request, prompt="Different external disclosure")
        self.assertEqual(self.run_request(request=changed).reason, "EXACT_REQUEST_NOT_AUTHORIZED")
        self.assertEqual(self.run_request(request=replace(self.request, task_version="2")).reason, "TASK_VERSION_NOT_AUTHORIZED")
        self.assertEqual(self.transport.calls, [])

    def test_approval_expiry_uses_utc_even_across_dst_fold(self):
        expired = replace(self.policy, valid_until=NOW)
        self.assertEqual(self.run_request(policy=expired).reason, "APPROVAL_EXPIRED_OR_NOT_YET_VALID")
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 1, 50, tzinfo=zone, fold=0)
        end = datetime(2026, 11, 1, 1, 20, tzinfo=zone, fold=1)
        now = datetime(2026, 11, 1, 1, 0, tzinfo=zone, fold=1)
        provider = QwenImageProvider(config(), self.transport, clock=lambda: now)
        self.assertEqual(self.run_request(provider=provider, policy=replace(self.policy, valid_from=start, valid_until=end)).status, "ready")

    def test_reference_edit_is_png_base64_single_user_turn(self):
        request, policy = self.edit()
        transport = FakeTransport(response(inputs=1))
        provider = QwenImageProvider(config(), transport, clock=lambda: NOW)
        result = self.run_request(request, policy, provider)
        self.assertEqual(result.status, "ready")
        content = transport.calls[0][0].json_body["input"]["messages"][0]["content"]
        self.assertEqual(list(content[0]), ["image"])
        encoded = content[0]["image"]
        self.assertTrue(encoded.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(encoded.split(",", 1)[1]), tiny_png())
        self.assertEqual(list(content[1]), ["text"])

    def test_one_to_three_reference_images_supported_but_four_rejected(self):
        for count in [1, 3]:
            request, policy = self.edit(count=count)
            transport = FakeTransport(response(inputs=count))
            provider = QwenImageProvider(config(), transport, clock=lambda: NOW)
            self.assertEqual(self.run_request(request, policy, provider).status, "ready")
        request, policy = self.edit(count=4)
        self.assertEqual(self.run_request(request, policy).reason, "EDIT_REQUIRES_ONE_TO_THREE_AUTHORIZED_REFERENCES")

    def test_general_generation_approval_does_not_allow_product_photo_upload(self):
        request, policy = self.edit()
        policy = replace(policy, allow_product_reference_upload=False)
        self.assertEqual(self.run_request(request, policy).reason, "PRODUCT_REFERENCE_DISCLOSURE_NOT_AUTHORIZED")
        policy = replace(policy, allow_reference_upload=False)
        self.assertEqual(self.run_request(request, policy).reason, "REFERENCE_UPLOAD_NOT_AUTHORIZED")
        self.assertEqual(self.transport.calls, [])

    def test_reference_source_and_exact_bytes_require_approval(self):
        request, policy = self.edit()
        self.assertEqual(self.run_request(request, replace(policy, approved_asset_hashes=())).reason, "EXACT_REFERENCE_BYTES_NOT_AUTHORIZED")
        changed_ref = replace(request.references[0], content_bytes=tiny_png(2, 1))
        self.assertEqual(self.run_request(replace(request, references=(changed_ref,)), policy).reason, "EXACT_REFERENCE_BYTES_NOT_AUTHORIZED")
        request, policy = self.edit(source_kind="unverified")
        self.assertEqual(self.run_request(request, policy).reason, "REFERENCE_PROVENANCE_UNVERIFIED")
        self.assertEqual(self.transport.calls, [])

    def test_reference_file_urls_and_other_formats_not_implemented(self):
        request, policy = self.edit()
        bad = replace(request.references[0], content_bytes=b"https://private.example/asset", mime_type="image/png")
        request = replace(request, references=(bad,))
        self.assertEqual(self.run_request(request, approval(request, allow_reference_upload=True, allow_product_reference_upload=True)).reason,
                         "REFERENCE_PNG_HEADER_OR_SIZE_INVALID")
        bad = replace(bad, mime_type="image/jpeg")
        request = replace(request, references=(bad,))
        self.assertEqual(self.run_request(request, approval(request, allow_reference_upload=True, allow_product_reference_upload=True)).reason,
                         "ADAPTER_SUPPORTS_PNG_REFERENCES_ONLY")

    def test_reference_dimensions_and_crc_validated_without_decoding(self):
        for data, reason in [(tiny_png(8001, 1), "REFERENCE_DIMENSIONS_OUT_OF_RANGE"),
                             (tiny_png(100, 1), "REFERENCE_DIMENSIONS_OUT_OF_RANGE"),
                             (tiny_png()[:29] + b"bad!" + tiny_png()[33:], "REFERENCE_PNG_IHDR_CRC_INVALID")]:
            request, policy = self.edit()
            ref = replace(request.references[0], content_bytes=data)
            request = replace(request, references=(ref,))
            self.assertEqual(self.run_request(request, approval(request, allow_reference_upload=True, allow_product_reference_upload=True)).reason, reason)

    def test_official_parameter_ranges_and_strict_boolean_types(self):
        for changes in [dict(n=0), dict(n=7), dict(n=True), dict(seed=-1), dict(seed=2147483648),
                        dict(size=(511, 511)), dict(size=(4096, 4096)), dict(size=(256, 4096)),
                        dict(size=[1024, 1024]), dict(prompt_extend="true"), dict(enable_thinking=True),
                        dict(prompt=""), dict(prompt="x" * 18001)]:
            with self.subTest(changes=changes):
                request = replace(self.request, **changes)
                self.assertNotEqual(self.run_request(request, approval(request, max_output_images=6)).status, "ready")
        self.assertEqual(self.transport.calls, [])

    def test_optional_parameters_and_auto_size_are_mapped(self):
        request = replace(self.request, size=None, seed=2147483647, negative_prompt="No logos", prompt_extend=True,
                          enable_thinking=True)
        result = self.run_request(request, approval(request))
        self.assertEqual(result.status, "ready")
        parameters = self.transport.calls[0][0].json_body["parameters"]
        self.assertNotIn("size", parameters)
        self.assertEqual(parameters["seed"], 2147483647)
        self.assertEqual(parameters["negative_prompt"], "No logos")
        self.assertEqual(parameters["prompt_extend_mode"], "direct")
        self.assertIs(parameters["enable_thinking"], True)

    def test_multi_output_count_must_be_authorized_and_match_response(self):
        request = replace(self.request, n=2)
        self.assertEqual(self.run_request(request, approval(request)).reason, "OUTPUT_COUNT_EXCEEDS_APPROVAL")
        transport = FakeTransport(response(n=2))
        provider = QwenImageProvider(config(), transport, clock=lambda: NOW)
        result = self.run_request(request, approval(request, max_output_images=2), provider)
        self.assertEqual(len(result.artifacts), 2)
        self.assertEqual(result.usage["output_image_count"], 2)
        self.assertEqual(self.run_request(request, approval(request, max_output_images=2)).reason, "PROVIDER_IMAGE_COUNT_MISMATCH")

    def test_response_is_unreviewed_ai_candidate_with_no_signed_url_in_safe_view(self):
        result = self.run_request()
        safe = result.safe_view()
        rendered = json.dumps(safe)
        self.assertEqual(result.request_id, "synthetic-provider-request-id")
        self.assertTrue(safe["contract_test_only"])
        self.assertNotIn("https://", rendered)
        self.assertNotIn("Signature", rendered)
        self.assertFalse(safe["export_allowed"])
        self.assertEqual(safe["visual_review_status"], "NOT_RUN")
        artifact = safe["artifact_candidates"][0]
        self.assertEqual(artifact["provenance"], "ai_generated_candidate")
        self.assertEqual(artifact["rights_status"], "UNVERIFIED")
        self.assertFalse(artifact["exact_expiry_verified"])
        self.assertNotIn("synthetic-0.png", repr(result.artifacts[0]))

    def test_response_urls_never_fetched_and_arbitrary_or_local_urls_rejected(self):
        for url in ["http://127.0.0.1/admin", "https://169.254.169.254/secret", "https://evil.example/image.png",
                    f"https://user:password@{DEFAULT_RESULT_HOST}/x.png", f"https://{DEFAULT_RESULT_HOST}:8443/x.png",
                    f"https://{DEFAULT_RESULT_HOST}/x.png#fragment", "file:///Users/private/file.png"]:
            body = copy.deepcopy(response().json_body)
            body["output"]["choices"][0]["message"]["content"][0]["image"] = url
            transport = FakeTransport(TransportResponse(200, body))
            result = self.run_request(provider=QwenImageProvider(config(), transport, clock=lambda: NOW))
            self.assertEqual(result.reason, "PROVIDER_ARTIFACT_URL_REJECTED")
            self.assertEqual(len(transport.calls), 1)  # generation only; no fetch/poll

    def test_provider_error_and_transport_exceptions_do_not_reflect_keys_or_inputs(self):
        secret = "synthetic-do-not-print-key"
        body = {"request_id": "safe-request-id", "code": "InvalidApiKey", "message": secret + self.request.prompt}
        transport = FakeTransport(TransportResponse(401, body))
        provider = QwenImageProvider(config(api_key=secret), transport, clock=lambda: NOW)
        result = self.run_request(provider=provider)
        self.assertEqual(result.provider_error_code, "InvalidApiKey")
        self.assertEqual(result.provider_http_status, 401)
        self.assertNotIn(secret, str(result.safe_view()))
        self.assertNotIn(self.request.prompt, str(result.safe_view()))
        transport = FakeTransport(failure=RuntimeError(secret + " raw request and signed URL"))
        result = self.run_request(provider=QwenImageProvider(config(api_key=secret), transport, clock=lambda: NOW))
        self.assertEqual(result.reason, "TRANSPORT_OR_INTERNAL_ERROR_REDACTED")
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(secret, repr(config(api_key=secret)))

    def test_cancel_before_submission_and_after_submission_are_different(self):
        result = self.provider.generate(self.request, self.policy, cancelled=lambda: True)
        self.assertEqual(result.reason, "CANCELLED_BEFORE_SUBMISSION")
        self.assertEqual(self.transport.calls, [])
        flag = [False]
        transport = FakeTransport(after_send=lambda: flag.__setitem__(0, True))
        provider = QwenImageProvider(config(), transport, clock=lambda: NOW)
        result = provider.generate(self.request, self.policy, cancelled=lambda: flag[0])
        self.assertEqual(result.reason, "CANCELLED_WAITING_REMOTE_STATE_UNKNOWN")
        self.assertEqual(result.remote_execution_state, "UNKNOWN_MAY_STILL_RUN_OR_BE_CHARGED")
        self.assertEqual(result.artifacts, ())

    def test_timeout_never_promises_remote_cancellation_or_retries(self):
        transport = FakeTransport(failure=TimeoutError("possibly secret context"))
        result = self.run_request(provider=QwenImageProvider(config(), transport, clock=lambda: NOW))
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.remote_execution_state, "UNKNOWN_MAY_STILL_RUN_OR_BE_CHARGED")
        self.assertEqual(len(transport.calls), 1)

    def test_late_response_cannot_bypass_expired_approval_and_keeps_safe_request_id(self):
        tick = [NOW]
        transport = FakeTransport(after_send=lambda: tick.__setitem__(0, NOW + timedelta(minutes=10)))
        provider = QwenImageProvider(config(), transport, clock=lambda: tick[0])
        result = self.run_request(provider=provider)
        self.assertEqual(result.reason, "APPROVAL_EXPIRED_OR_NOT_YET_VALID")
        self.assertEqual(result.request_id, "synthetic-provider-request-id")
        self.assertEqual(result.artifacts, ())
        self.assertEqual(result.remote_execution_state, "RESPONSE_UNUSABLE")

    def test_incomplete_response_usage_or_unknown_content_cannot_pass(self):
        for change, reason in [("finish", "PROVIDER_FINISH_NOT_COMPLETE"), ("usage", "PROVIDER_USAGE_MISSING_OR_INVALID"),
                               ("content", "UNSUPPORTED_PROVIDER_OUTPUT_CONTENT"), ("tier", "PROVIDER_USAGE_TIER_INCONSISTENT"),
                               ("request_id", "PROVIDER_REQUEST_ID_MISSING_OR_UNSAFE"), ("size", "PROVIDER_OUTPUT_SIZE_MISMATCH")]:
            with self.subTest(change=change):
                body = copy.deepcopy(response().json_body)
                if change == "finish":
                    body["output"]["choices"][0]["finish_reason"] = "content_filter"
                elif change == "usage":
                    body.pop("usage")
                elif change == "content":
                    body["output"]["choices"][0]["message"]["content"].append({"text": "Unverified claim"})
                elif change == "tier":
                    body["usage"]["output_image_type"] = "qima_output_2k"
                elif change == "request_id":
                    body.pop("request_id")
                else:
                    body["usage"]["output_width"] = 1023
                transport = FakeTransport(TransportResponse(200, body))
                result = self.run_request(provider=QwenImageProvider(config(), transport, clock=lambda: NOW))
                self.assertEqual(result.reason, reason)
                self.assertEqual(result.artifacts, ())

    def test_no_public_signed_url_or_ima_source_upgrade_for_edited_product(self):
        request, policy = self.edit()
        transport = FakeTransport(response(inputs=1))
        result = self.run_request(request, policy, QwenImageProvider(config(), transport, clock=lambda: NOW))
        safe = result.safe_view()
        self.assertEqual(safe["artifact_candidates"][0]["provenance"], "ai_generated_candidate")
        self.assertNotIn("ima_original", json.dumps(safe))
        self.assertFalse(safe["export_allowed"])


if __name__ == "__main__":
    unittest.main()

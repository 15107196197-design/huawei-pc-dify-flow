"""Local knowledge reader with short-lived scope and optional ima file matching.

Source documents are untrusted data. Only an injected server-owned verifier may
read ima originals; request URLs are never accepted. This module neither solves
real quotations nor treats an image index as publication approval.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit


MATRIX = "P1-产品参数库/00-全库横向索引/全型号参数联合矩阵.csv"
IMAGE_MATRIX = "P1-产品参数库/00-全库横向索引/全部图片联合检索表.csv"
KINDS = {"product_intro", "marketing", "quote", "sales_script", "full_package"}
CHANNELS = {None, "wechat_article", "xiaohongshu", "moments", "store_poster"}
MODEL_NODES = {"product_intro", "fact_compliance_review", "article_write", "poster_copy",
               "platform_strategy", "visual_layout", "visual_review", "quote_explain", "sales_demo"}
TEXT_FIELDS = {"product_query", "audience", "usage_scenario", "purchase_stage", "problem",
               "content_goal", "sales_platform", "purchase_stage_basis"}
LIST_FIELDS = {"hard_requirements", "required_fact_fields"}
QUOTE_TEXT_LIMITS = {"region": 256, "as_of": 64, "rule_timezone": 64, "currency": 16}
CLAIMED_ELIGIBILITY_STATES = {"unknown", "user_claimed", "needs_verification"}
FACT_FIELDS = {"操作系统", "尺寸与重量", "屏幕", "处理器", "存储", "内存", "显卡", "无线连接",
               "电池", "接口", "键盘和触控板", "键盘触控板", "摄像头", "音频", "特色应用", "包装清单"}


class BridgeError(Exception):
    def __init__(self, code, message, status="error", http_status=400):
        super().__init__(message)
        self.code, self.message, self.status, self.http_status = code, message, status, http_status


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def normalize(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("huawei", "").replace("华为", "")
    return re.sub(r"[\s()（）·｜|_\-]+", "", value)


@dataclass
class Config:
    root: Path
    token: str = field(repr=False)
    allowed_destinations: list = field(default_factory=list)
    proof_ttl: int = 120
    signing_key: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)
    actor_id: str = "local_developer"
    tenant_id: str = "development_only"
    store_id: str = "local_single_store"
    purpose_ref: str = "local_product_content"
    destination_ref: str = "local_dify"
    region: str = "CN"
    default_source_mode: str = "local_snapshot"
    enable_ima_verification: bool = False

    def __post_init__(self):
        self.root = Path(self.root).expanduser()
        if self.root.is_symlink() or not self.root.is_dir():
            raise BridgeError("INVALID_ROOT", "Configured source must be a real local directory.")
        self.root = self.root.resolve(strict=True)
        if not isinstance(self.token, str) or len(self.token) < 24:
            raise BridgeError("INVALID_CONFIG", "HUAWEI_TOOL_TOKEN must contain at least 24 characters.")
        if type(self.proof_ttl) is not int or not 1 <= self.proof_ttl <= 900:
            raise BridgeError("INVALID_CONFIG", "Proof lifetime must be 1–900 seconds.")
        if self.default_source_mode not in {"local_snapshot", "hybrid_verified"}:
            raise BridgeError("INVALID_CONFIG", "Unsupported default source mode.")
        if type(self.enable_ima_verification) is not bool:
            raise BridgeError("INVALID_CONFIG", "IMA verification enablement must be a boolean.")
        if not isinstance(self.allowed_destinations, list):
            raise BridgeError("INVALID_CONFIG", "Model destination allowlist must be an array.")
        required = {"node_id", "provider", "model", "purpose_ref", "destination_ref", "region"}
        seen = set()
        for row in self.allowed_destinations:
            if not isinstance(row, dict) or set(row) != required:
                raise BridgeError("INVALID_CONFIG", "Every destination must have exactly the six documented fields.")
            if any(not isinstance(row[k], str) or not row[k].strip() or len(row[k]) > 256 for k in required):
                raise BridgeError("INVALID_CONFIG", "Destination fields must be nonempty strings.")
            if row["node_id"] not in MODEL_NODES:
                raise BridgeError("INVALID_CONFIG", "Unknown model node in destination allowlist.")
            key = tuple(row[k] for k in sorted(required))
            if key in seen:
                raise BridgeError("INVALID_CONFIG", "Duplicate model destination.")
            seen.add(key)

    @classmethod
    def from_env(cls):
        root, token = os.environ.get("HUAWEI_KB_ROOT"), os.environ.get("HUAWEI_TOOL_TOKEN", "")
        if not root:
            raise BridgeError("INVALID_CONFIG", "Set HUAWEI_KB_ROOT to the authorized local source directory.")
        try:
            allow = json.loads(os.environ.get("HUAWEI_ALLOWED_MODEL_DESTINATIONS_JSON", "[]"))
        except (ValueError, TypeError):
            raise BridgeError("INVALID_CONFIG", "Model allowlist is not valid JSON.") from None
        enabled = os.environ.get("HUAWEI_ENABLE_IMA_VERIFICATION", "0")
        if enabled not in {"0", "1"}:
            raise BridgeError("INVALID_CONFIG", "IMA verification enablement must be 0 or 1.")
        return cls(Path(root), token, allow,
                   default_source_mode=os.environ.get("HUAWEI_SOURCE_MODE", "local_snapshot"),
                   enable_ima_verification=enabled == "1")


class LocalSource:
    MAX_FILES = 20000
    MAX_TOTAL_BYTES = 256 * 1024 * 1024
    MAX_TEXT_BYTES = 4 * 1024 * 1024

    def __init__(self, root):
        self.root = root
        self.root_identity = (root.stat().st_dev, root.stat().st_ino)

    def read_bytes(self, relative, max_bytes=MAX_TEXT_BYTES):
        """Open each component relative to a no-follow root fd, never arbitrary URLs."""
        if not isinstance(relative, str) or "\\" in relative or "\x00" in relative:
            raise BridgeError("SOURCE_PATH_REJECTED", "Invalid source locator.", "denied", 403)
        path = PurePosixPath(relative)
        if path.is_absolute() or not path.parts or any(x in {"..", "."} for x in path.parts) or ":" in relative:
            raise BridgeError("SOURCE_PATH_REJECTED", "Invalid source locator.", "denied", 403)
        fd = None
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != self.root_identity:
                raise BridgeError("SOURCE_CHANGED", "Source root was replaced.", "needs_source", 409)
            for part in path.parts[:-1]:
                new_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            leaf = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                st = os.fstat(leaf)
                if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
                    raise BridgeError("SOURCE_PATH_REJECTED", "Source is not an allowed regular file.", "denied", 403)
                with os.fdopen(leaf, "rb", closefd=False) as stream:
                    data = stream.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise BridgeError("SOURCE_LIMIT", "Source file exceeds the read limit.", "needs_source", 413)
                return data
            finally:
                os.close(leaf)
        except OSError:
            raise BridgeError("SOURCE_PATH_REJECTED", "Source locator is unavailable or contains a symlink.", "denied", 403) from None
        finally:
            if fd is not None:
                os.close(fd)

    def text(self, relative):
        try:
            return self.read_bytes(relative).decode("utf-8-sig")
        except UnicodeError:
            raise BridgeError("SOURCE_PARSE_ERROR", "Source text is not UTF-8.", "needs_source", 409) from None

    def rows(self, relative):
        rows = list(csv.DictReader(io.StringIO(self.text(relative))))
        if any(None in row for row in rows):
            raise BridgeError("SOURCE_PARSE_ERROR", "CSV row width is inconsistent.", "needs_source", 409)
        return rows

    def snapshot(self):
        entries, total = [], 0
        if self.root.is_symlink() or (self.root.stat().st_dev, self.root.stat().st_ino) != self.root_identity:
            raise BridgeError("SOURCE_CHANGED", "Source root was replaced.", "needs_source", 409)
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            for name in dirs + files:
                file = Path(directory) / name
                if file.is_symlink():
                    raise BridgeError("SOURCE_SYMLINK", "Source tree contains a symlink; it is not followed.", "needs_source", 409)
            for name in files:
                file = Path(directory) / name
                st = file.stat(follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    raise BridgeError("SOURCE_PATH_REJECTED", "Source tree contains a nonregular file.", "denied", 403)
                total += st.st_size
                if len(entries) >= self.MAX_FILES or total > self.MAX_TOTAL_BYTES:
                    raise BridgeError("SOURCE_LIMIT", "Source tree exceeds configured limits.", "needs_source", 413)
                relative = file.relative_to(self.root).as_posix()
                raw = self.read_bytes(relative, max_bytes=self.MAX_TOTAL_BYTES)
                # Metadata changes also invalidate prior scope, even when bytes are unchanged.
                entries.append((relative, st.st_size, st.st_mtime_ns, st.st_ino, digest(raw)))
        return "snapshot_" + digest(canonical(sorted(entries)).encode())

    def models(self):
        models = []
        for row in self.rows(MATRIX):
            relative = row.get("本地事实源", "")
            if not re.fullmatch(r"P1-产品参数库/(01-鸿蒙电脑|02-MateBook-Windows)/[^/]+/产品事实\.md", relative):
                raise BridgeError("SOURCE_PATH_REJECTED", "Matrix contains an unapproved facts locator.", "denied", 403)
            raw = self.text(relative)
            title = raw.splitlines()[0].lstrip("# ").removesuffix(" - 产品事实").strip()
            models.append({"product_ref": "product_" + digest(relative.encode())[:24], "name": title,
                           "alias": row.get("型号", ""), "path": relative, "raw": raw})
        return models

    def resolve_model(self, query):
        if not isinstance(query, str) or not query.strip():
            return None, []
        if len(query) > 512 or re.search(r"https?://|file:|\.\.[/\\]", query, re.I):
            raise BridgeError("INVALID_INPUT", "Product query must be a model name, not a path or URL.")
        q = normalize(query)
        models = self.models()
        exact = [m for m in models if normalize(m["name"]) == q]
        if len(exact) == 1:
            return exact[0], []
        candidates = [m for m in models if any(q in normalize(v) for v in [m["name"], m["alias"]])]
        if len(candidates) == 1:
            return candidates[0], []
        return None, [{"product_ref": m["product_ref"], "product_display_name": m["name"]} for m in candidates]

    @staticmethod
    def quarantined(model):
        blocked = {}
        if any(x in model["path"] for x in ["/MateBook D 14/", "/MateBook D 16/", "/MateBook D 16 SE 版/", "/MateBook X系列/"]):
            blocked["尺寸与重量"] = "suspected_field_mapping_error"
        if "/HUAWEI MateBook 14/" in model["path"]:
            blocked.update({"操作系统": "conflicting_snapshot_versions", "内存": "conflicting_sales_configuration"})
        return blocked

    def facts(self, model):
        lines = model["raw"].splitlines()
        headings = [(i, line[3:].strip()) for i, line in enumerate(lines) if line.startswith("## ")]
        urls = []
        for value in re.findall(r"https://[^\s<>]+", model["raw"]):
            url = value.rstrip(".,;；。)")
            parsed = urlsplit(url)
            if parsed.netloc == "consumer.huawei.com" and not parsed.query and not parsed.fragment:
                urls.append(url)
        date = re.search(r"抓取日期[：:]\s*(\d{4}-\d{2}-\d{2})", model["raw"])
        content_hash = digest(self.read_bytes(model["path"]))
        if digest(model["raw"].encode()) != digest(self.text(model["path"]).encode()):
            raise BridgeError("SOURCE_CHANGED", "Product source changed during retrieval.", "needs_source", 409)
        blocked = self.quarantined(model)
        facts, refs, omitted = [], [], []
        global_refs, global_conditions = [], []
        # Preserve preamble scope/date/variant limitations and explicit document-wide notes.
        global_spans = [(1, headings[0][0], "文档适用条件")] if headings else []
        for index, (start, heading) in enumerate(headings):
            if heading not in FACT_FIELDS and re.search(r"免责|适用条件|全局|注意事项|脚注|限制", heading):
                stop = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
                global_spans.append((start, stop, heading))
        for start, stop, heading in global_spans:
            excerpt = "\n".join(lines[start:stop]).strip()
            if not excerpt:
                continue
            ref = "source_" + digest(f"{content_hash}:global:{start}:{stop}".encode())[:24]
            global_refs.append(ref)
            global_conditions.append(excerpt)
            refs.append({"source_ref_id": ref, "source_title": model["name"] + " / " + heading,
                         "document_id": "document_" + digest(model["path"].encode())[:24],
                         "content_hash": content_hash, "section_heading": heading,
                         "line_start": start + 1, "line_end": stop,
                         "source_urls": sorted(set(urls)), "captured_at": date.group(1) if date else None,
                         "source_excerpt": excerpt, "source_type": "local_p1_mandatory_conditions"})
        for index, (start, heading) in enumerate(headings):
            if heading not in FACT_FIELDS:
                continue
            stop = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
            for cursor in range(start + 1, stop):
                if lines[cursor].strip() == "即将离开consumer.huawei.com":
                    stop = cursor
                    break
            raw = "\n".join(lines[start + 1:stop]).strip()
            if not raw:
                continue
            if heading in blocked:
                omitted.append({"field": heading, "reason": blocked[heading],
                                "source_title": model["name"] + " / " + heading,
                                "line_start": start + 1, "line_end": stop, "content_hash": content_hash})
                continue
            suffix = digest(f"{content_hash}:{start}:{stop}".encode())[:24]
            source_id, fact_id = "source_" + suffix, "fact_" + suffix
            refs.append({"source_ref_id": source_id, "source_title": model["name"] + " / " + heading,
                         "document_id": "document_" + digest(model["path"].encode())[:24],
                         "content_hash": content_hash, "section_heading": heading,
                         "line_start": start + 1, "line_end": stop,
                         "source_urls": sorted(set(urls)), "captured_at": date.group(1) if date else None,
                         "source_excerpt": raw, "source_type": "local_p1_product_facts"})
            facts.append({"fact_id": fact_id, "product_ref": model["product_ref"],
                          "product_display_name": model["name"], "sku_scope": "model_variants_only",
                          "field_name": heading, "raw_value": raw, "source_ref_ids": [source_id] + global_refs,
                          "conditions": global_conditions + [line for line in raw.splitlines() if line.startswith("*")],
                          "verification_state": "local_source_claim_only"})
        return facts, refs, omitted

    def assets(self, model):
        """Candidates only: no image bytes, fetch URL, or filesystem path to an LLM."""
        try:
            rows = self.rows(IMAGE_MATRIX)
        except BridgeError:
            return []
        assets = []
        for row in rows:
            if normalize(row.get("产品型号", "")) != normalize(model["name"]):
                continue
            directory, filename = row.get("本地目录", ""), row.get("文件名", "")
            if directory != str(PurePosixPath(model["path"]).parent):
                raise BridgeError("SOURCE_PATH_REJECTED", "Asset index is outside its approved model directory.", "denied", 403)
            if not filename or "/" in filename or "\\" in filename:
                raise BridgeError("SOURCE_PATH_REJECTED", "Invalid asset locator.", "denied", 403)
            relative = directory + "/images/" + filename
            raw = self.read_bytes(relative, 32 * 1024 * 1024)
            assets.append({"asset_ref": "asset_" + digest(raw), "product_ref": model["product_ref"],
                           "caption": row.get("画面说明", ""), "content_hash": digest(raw),
                           "verification_state": "candidate_unverified", "rights_state": "unverified",
                           "model_scope_state": "unverified", "approved_for_publication": False,
                           "ima_provenance": "unverified"})
        return assets


class Bridge:
    def __init__(self, config, clock=time.time, *, hybrid_verifier=None):
        self.config, self.clock = config, clock
        self.hybrid_verifier = hybrid_verifier
        self.source = LocalSource(config.root)
        self.contexts = {}
        self.lock = threading.Lock()

    def authenticate(self, authorization):
        expected = "Bearer " + self.config.token
        if not isinstance(authorization, str) or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise BridgeError("AUTH_REQUIRED", "Valid service authentication is required.", "denied", 401)

    def _scope(self):
        c = self.config
        return {"actor_id": c.actor_id, "tenant_id": c.tenant_id, "store_id": c.store_id,
                "purpose_ref": c.purpose_ref, "destination_ref": c.destination_ref, "region": c.region}

    def _check_scope(self, body):
        for key, value in self._scope().items():
            if key in body and body[key] != value:
                raise BridgeError("SCOPE_MISMATCH", "Requested identity or disclosure scope is not authorized.", "denied", 403)

    def clean_task(self, raw):
        if not isinstance(raw, dict):
            raise BridgeError("INVALID_TASK", "task must be an object.")
        # Only an explicit product_intro may use the limited no-purchase-plan route.
        kind = raw.get("task_kind")
        if not isinstance(kind, str) or kind not in KINDS:
            raise BridgeError("INVALID_TASK", "Unsupported task kind.")
        task = {"task_kind": kind}
        delivery_scope = raw.get("delivery_scope", "complete_package")
        if not isinstance(delivery_scope, str) or delivery_scope not in {"content_only", "complete_package"}:
            raise BridgeError("INVALID_TASK", "Unsupported delivery scope.")
        if delivery_scope == "content_only" and kind != "marketing":
            raise BridgeError("INVALID_TASK", "Content-only scope requires an explicit marketing task.")
        if "delivery_scope" in raw:
            task["delivery_scope"] = delivery_scope
        for key in TEXT_FIELDS:
            value = raw.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 2048):
                raise BridgeError("INVALID_TASK", "Task text fields must be short strings or null.")
            task[key] = value
        channel = raw.get("content_channel")
        if channel is not None and (not isinstance(channel, str) or channel not in CHANNELS):
            raise BridgeError("INVALID_TASK", "Unknown content channel.")
        if kind in {"marketing", "full_package"} and channel is None:
            raise BridgeError("INVALID_TASK", "Marketing tasks require an explicit content channel.")
        task["content_channel"] = channel
        for key in LIST_FIELDS:
            value = raw.get(key, [])
            if not isinstance(value, list) or len(value) > 20 or any(not isinstance(x, str) or len(x) > 512 for x in value):
                raise BridgeError("INVALID_TASK", "Task requirements must be short string arrays.")
            task[key] = value
        for key in ["quote_required", "script_required", "purchase_plan_required", "recommendation_requested"]:
            if key in raw and type(raw[key]) is not bool:
                raise BridgeError("INVALID_TASK", "Task flags must be booleans.")
        inputs = raw.get("quote_inputs", {})
        if not isinstance(inputs, dict) or set(inputs) - (set(QUOTE_TEXT_LIMITS) | {"quantity", "eligibility"}):
            raise BridgeError("INVALID_TASK", "quote_inputs contains unsupported fields.")
        quote_inputs = {}
        for key, limit in QUOTE_TEXT_LIMITS.items():
            value = inputs.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > limit):
                raise BridgeError("INVALID_TASK", "Quote input text must be a short nonempty string or null.")
            quote_inputs[key] = value
        quantity = inputs.get("quantity")
        if quantity is not None and (type(quantity) is not int or quantity <= 0):
            raise BridgeError("INVALID_TASK", "Quote quantity must be a positive integer or null.")
        quote_inputs["quantity"] = quantity
        eligibility = inputs.get("eligibility", [])
        if not isinstance(eligibility, list) or len(eligibility) > 20:
            raise BridgeError("INVALID_TASK", "Eligibility claims must be a bounded array.")
        quote_inputs["eligibility"] = []
        for claim in eligibility:
            if not isinstance(claim, dict) or set(claim) - {"kind", "claimed_status", "evidence_ref"}:
                raise BridgeError("INVALID_TASK", "Unsupported eligibility claim fields.")
            claim_kind, state, ref = claim.get("kind"), claim.get("claimed_status"), claim.get("evidence_ref")
            if not isinstance(claim_kind, str) or not claim_kind.strip() or len(claim_kind) > 128:
                raise BridgeError("INVALID_TASK", "Eligibility kind must be a short nonempty string.")
            if not isinstance(state, str) or state not in CLAIMED_ELIGIBILITY_STATES:
                raise BridgeError("INVALID_TASK", "Only unverified eligibility claim states are accepted.")
            if ref is not None and (not isinstance(ref, str) or not ref.strip() or len(ref) > 512):
                raise BridgeError("INVALID_TASK", "Eligibility evidence_ref must be a short string or null.")
            # A reference is a user-supplied claim, never a service verification or authorization.
            quote_inputs["eligibility"].append({"kind": claim_kind, "claimed_status": state, "evidence_ref": ref})
        task["quote_inputs"] = quote_inputs
        task["recommendation_requested"] = raw.get("recommendation_requested", False)
        content_only = kind == "marketing" and delivery_scope == "content_only"
        if content_only and any(raw.get(key, False) for key in ("quote_required", "purchase_plan_required", "script_required")):
            raise BridgeError("INVALID_TASK", "Content-only scope conflicts with a price or script request.")
        task["purchase_plan_required"] = raw.get("purchase_plan_required", False) or kind == "full_package" or (kind == "marketing" and not content_only)
        task["script_required"] = raw.get("script_required", False) or kind in {"sales_script", "full_package"}
        intent = " ".join(str(task.get(x) or "") for x in ["content_goal", "problem", "usage_scenario"])
        intent = re.sub(r"不需要报价|不要报价|不含报价|不报价|无报价|不含价格|不要价格", "", intent)
        price_intent = bool(re.search(r"报价|多少钱|最低实付|到手价|优惠金额|补贴金额|含价格", intent))
        if content_only and price_intent:
            raise BridgeError("INVALID_TASK", "Content-only scope conflicts with the requested price content.")
        task["quote_required"] = raw.get("quote_required", False) or task["purchase_plan_required"] or task["script_required"] or kind == "quote" or price_intent
        return task

    @staticmethod
    def check_development_stage(task, source_mode, stage):
        if stage is None:
            return
        if (stage != "platform_strategy" or source_mode != "local_snapshot" or
                task.get("task_kind") != "marketing" or task.get("delivery_scope") != "content_only" or
                any(task.get(key) is not False for key in ("quote_required", "purchase_plan_required", "script_required"))):
            raise BridgeError("DEVELOPMENT_STAGE_INVALID", "Only explicit local, no-price marketing strategy development is supported.", "denied", 403)

    def policy(self, task=None, source_mode="local_snapshot", development_stage=None):
        scope = self._scope()
        destinations = [dict(row) for row in self.config.allowed_destinations
                        if all(row[key] == scope[key] for key in ["purpose_ref", "destination_ref", "region"])]
        required_nodes = {"fact_compliance_review"}
        kind = task["task_kind"] if task else "product_intro"
        if kind in {"marketing", "full_package"}:
            writer = "poster_copy" if task["content_channel"] == "store_poster" else "article_write"
            required_nodes.update({writer, "platform_strategy", "visual_layout", "visual_review"})
        elif kind == "product_intro":
            required_nodes.add("product_intro")
        if task and task["quote_required"]:
            required_nodes.add("quote_explain")
        if task and task["script_required"]:
            required_nodes.add("sales_demo")
        approved_nodes = {row["node_id"] for row in destinations}
        policy = {"llm_payload_allowed": required_nodes.issubset(approved_nodes),
                "required_model_nodes": sorted(required_nodes), "allowed_model_destinations": destinations,
                "source_mode": source_mode, "competition_eligible": False, "export_allowed": False,
                "development_single_user_only": True, "multi_store_authorization_implemented": False}
        if development_stage is not None:
            self.check_development_stage(task, source_mode, development_stage)
            policy["stage_authorization"] = {
                "stage": development_stage, "allowed": "platform_strategy" in approved_nodes,
                "current_model_nodes": ["platform_strategy"],
                **{key: scope[key] for key in ("purpose_ref", "destination_ref", "region")},
                "development_only": True, "export_allowed": False, "competition_eligible": False}
        return policy

    def _sign(self, payload):
        encoded = base64.urlsafe_b64encode(canonical(payload).encode()).rstrip(b"=")
        signature = hmac.new(self.config.signing_key, encoded, hashlib.sha256).digest()
        return (encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()

    def _verify(self, ref, proof):
        if not isinstance(ref, str) or not isinstance(proof, str) or len(proof) > 4096:
            raise BridgeError("CONTEXT_INVALID", "A valid bound source context is required.", "denied", 403)
        try:
            encoded, signed = proof.encode("ascii").split(b".")
            expected = base64.urlsafe_b64encode(hmac.new(self.config.signing_key, encoded, hashlib.sha256).digest()).rstrip(b"=")
            if not hmac.compare_digest(signed, expected):
                raise ValueError
            payload = json.loads(base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4)))
        except (ValueError, TypeError, UnicodeError):
            raise BridgeError("CONTEXT_INVALID", "Source context proof is invalid.", "denied", 403) from None
        with self.lock:
            context = self.contexts.get(ref)
        if (not context or payload != context["proof_payload"] or payload.get("scope") != self._scope() or
                payload.get("task_hash") != digest(canonical(context["task"]).encode())):
            raise BridgeError("SCOPE_MISMATCH", "Source context is not authorized for this scope.", "denied", 403)
        if self.clock() >= payload["expires_at"]:
            raise BridgeError("CONTEXT_EXPIRED", "Resolve a new source context.", "needs_source", 409)
        if payload["snapshot"] != self.source.snapshot():
            raise BridgeError("SOURCE_CHANGED", "Source changed; previous context and evidence are invalid.", "needs_source", 409)
        if payload.get("source_mode") == "hybrid_verified":
            from services.ima_adapter.hybrid import FactReceipt
            receipt = context.get("fact_receipt")
            model, _ = self.source.resolve_model(context["task"].get("product_query"))
            try:
                raw = (self.source.read_bytes(receipt.relative_path)
                       if type(receipt) is FactReceipt and model is not None and receipt.relative_path == model["path"]
                       else b"")
                valid = (type(receipt) is FactReceipt and model is not None and
                         receipt.product_ref == model["product_ref"] and receipt.relative_path == model["path"] and
                         receipt.byte_length == len(raw) and
                         receipt.manifest_hash() == payload.get("fact_receipt_hash") and
                         receipt.source_context_ref == ref and receipt.snapshot_ref == payload["snapshot"] and
                         receipt.task_hash == payload["task_hash"] and
                         receipt.scope_hash == digest(canonical(self._scope()).encode()) and
                         receipt.verified_at <= self.clock() < receipt.expires_at and
                         receipt.sha256 == digest(raw))
            except (AttributeError, TypeError, ValueError, BridgeError):
                valid = False
            if not valid:
                raise BridgeError("IMA_FACT_RECEIPT_INVALID", "Re-resolve and verify the selected source file.", "needs_source", 409)
        return context

    @staticmethod
    def quote_state(required, purchase_plan_required=False):
        return {"quote_required": required, "quote_status": "BLOCKED_SOURCE_UNVERIFIED" if required else None,
                "purchase_plan_required": purchase_plan_required,
                "quote_ref": None, "client_quote_allowed": False, "customer_quote_summary": None,
                "local_delivery_ref": None}

    def resolve(self, body):
        self._check_scope(body)
        mode = body.get("source_mode", self.config.default_source_mode)
        if not isinstance(mode, str) or mode not in {"local_snapshot", "ima_live", "hybrid_verified"}:
            raise BridgeError("INVALID_INPUT", "Unknown source mode.")
        if mode == "ima_live" or (mode == "hybrid_verified" and self.hybrid_verifier is None):
            return "needs_source", {"reason": "SOURCE_MODE_NOT_IMPLEMENTED", "source_mode": mode,
                                    "competition_eligible": False, "llm_payload_allowed": False}
        task = self.clean_task(body.get("task"))
        development_stage = body.get("development_stage")
        self.check_development_stage(task, mode, development_stage)
        snapshot = self.source.snapshot()
        ref = "context_" + secrets.token_urlsafe(24)
        payload = {"ref": ref, "scope": self._scope(), "snapshot": snapshot,
                   "task_hash": digest(canonical(task).encode()), "source_mode": mode,
                   "expires_at": int(self.clock()) + self.config.proof_ttl}
        if development_stage is not None:
            payload["development_stage"] = development_stage
        receipt = None
        if mode == "hybrid_verified":
            model, candidates = self.source.resolve_model(task.get("product_query"))
            if model is None:
                return "needs_input", {"reason": "PRODUCT_AMBIGUOUS_OR_MISSING", "candidates": candidates,
                                       "competition_eligible": False, "llm_payload_allowed": False}
            try:
                receipt = self.hybrid_verifier.verify(
                    relative_path=model["path"], local_bytes=self.source.read_bytes(model["path"]),
                    product_ref=model["product_ref"], source_context_ref=ref, scope=self._scope(),
                    task_hash=payload["task_hash"], snapshot_ref=snapshot, ttl=self.config.proof_ttl)
            except Exception as error:
                from services.ima_adapter.reader import ImaAdapterError
                reason = ("IMA_DAILY_SOURCE_LIMIT_REACHED" if isinstance(error, ImaAdapterError) and
                          error.code == "IMA_DAILY_SOURCE_LIMIT_REACHED" else "IMA_FACT_VERIFICATION_FAILED")
                return "needs_source", {"reason": reason, "source_mode": mode,
                                       "competition_eligible": False, "llm_payload_allowed": False}
            # A changed local tree must never get a proof for an earlier snapshot.
            if snapshot != self.source.snapshot():
                raise BridgeError("SOURCE_CHANGED", "Source changed during ima verification.", "needs_source", 409)
            payload["fact_receipt_hash"] = receipt.manifest_hash()
            payload["expires_at"] = min(int(self.clock()) + self.config.proof_ttl, receipt.expires_at)
        with self.lock:
            now = self.clock()
            self.contexts = {k: v for k, v in self.contexts.items() if v["proof_payload"]["expires_at"] > now}
            if len(self.contexts) >= 1024:
                raise BridgeError("CONTEXT_LIMIT", "Too many active contexts.", "error", 429)
            self.contexts[ref] = {"task": task, "proof_payload": payload, "fact_receipt": receipt}
        # Apply identical receipt checks before issuing a proof, not only on consumption.
        self._verify(ref, self._sign(payload))
        return "ready", {"source_context_ref": ref, "source_context_proof": self._sign(payload),
                         "source_snapshot_ref": snapshot, "source_mode": mode,
                         "purpose_ref": self.config.purpose_ref, "destination_ref": self.config.destination_ref,
                         "expires_at": payload["expires_at"], "policy": self.policy(task, mode, development_stage),
                         **self.quote_state(task["quote_required"], task["purchase_plan_required"])}

    def evidence(self, body, proof):
        self._check_scope(body)
        context = self._verify(body.get("source_context_ref"), proof)
        development_stage = context["proof_payload"].get("development_stage")
        if body.get("development_stage") != development_stage:
            raise BridgeError("DEVELOPMENT_STAGE_MISMATCH", "The development stage must match its bound source context.", "denied", 403)
        for key in ["need_pricing_rules", "need_product_facts", "need_images"]:
            if key in body and type(body[key]) is not bool:
                raise BridgeError("INVALID_INPUT", "Evidence flags must be booleans.")
        task = context["task"]
        if "task" not in body or self.clean_task(body["task"]) != task:
            raise BridgeError("TASK_MISMATCH", "Task changed; resolve a new source context.", "denied", 403)
        for key in ["product_query", "content_channel", "sales_platform"]:
            if key in body and body[key] != task.get(key):
                raise BridgeError("TASK_MISMATCH", "Evidence request differs from its bound task.", "denied", 403)
        if body.get("need_pricing_rules", False) or task["quote_required"]:
            return "needs_source", {"reason": "FOUR_LEVELS_PENDING",
                                    **self.quote_state(True, task["purchase_plan_required"]), "task_bundle": None}
        mode = context["proof_payload"]["source_mode"]
        policy = self.policy(task, mode, development_stage)
        if development_stage is not None and body.get("need_images", False):
            raise BridgeError("DEVELOPMENT_STAGE_IMAGE_REQUEST_FORBIDDEN", "Strategy development returns textual evidence only.", "denied", 403)
        stage_allowed = policy.get("stage_authorization", {}).get("allowed") is True
        if not policy["llm_payload_allowed"] and not stage_allowed:
            return "needs_source", {"reason": "MODEL_DESTINATION_NOT_APPROVED", "policy": policy,
                                    **self.quote_state(False), "task_bundle": None}
        model, candidates = self.source.resolve_model(task.get("product_query"))
        if model is None:
            return "needs_input", {"reason": "PRODUCT_AMBIGUOUS_OR_MISSING", "candidates": candidates,
                                   "questions": ["请确认完整型号、年份/系统版本及相关配置。"], "task_bundle": None}
        facts, refs, omitted = self.source.facts(model)
        receipt = context.get("fact_receipt")
        provenance = "unverified"
        ima_verification = None
        if mode == "hybrid_verified":
            if (receipt.product_ref != model["product_ref"] or receipt.relative_path != model["path"] or
                    any(row["content_hash"] != receipt.sha256 for row in refs)):
                raise BridgeError("IMA_FACT_RECEIPT_INVALID", "Evidence differs from the verified file.", "needs_source", 409)
            provenance = "selected_fact_file_original_hash_matched"
            ima_verification = receipt.manifest()
            for row in refs:
                row["ima_provenance"] = provenance
            for row in facts:
                row["verification_state"] = "source_original_matched_fact_truth_not_asserted"
        requirements = " ".join(task["required_fact_fields"] + task["hard_requirements"] +
                                [str(task.get(k) or "") for k in ["usage_scenario", "problem", "content_goal"]])
        needed = set(task["required_fact_fields"])
        for pattern, field_name in [(r"尺寸|厚度|长度|宽度|重量|轻薄|便携", "尺寸与重量"),
                                    (r"操作系统|系统版本|兼容|软件|HarmonyOS", "操作系统"),
                                    (r"内存|\d+\s*GB", "内存")]:
            if re.search(pattern, requirements, re.I):
                needed.add(field_name)
        conflicts = [row for row in omitted if row["field"] in needed]
        if conflicts:
            return "conflict", {"reason": "REQUIRED_FACT_CONFLICT", "product_ref": model["product_ref"],
                                "conflicts": conflicts, "task_bundle": None, **self.quote_state(False)}
        missing = sorted(set(task["required_fact_fields"]) - {row["field_name"] for row in facts})
        if missing or not facts:
            return "needs_source", {"reason": "REQUIRED_FACT_MISSING", "missing_fact_fields": missing,
                                    "task_bundle": None, **self.quote_state(False)}
        # No unverified candidate is promoted into allowed_assets.
        candidates = self.source.assets(model) if body.get("need_images", False) else []
        snapshot = context["proof_payload"]["snapshot"]
        if snapshot != self.source.snapshot():
            raise BridgeError("SOURCE_CHANGED", "Source changed during retrieval.", "needs_source", 409)
        bundle = {"trusted_context": {"source_context_ref": body["source_context_ref"],
                                      "source_mode": mode, "source_snapshot_ref": snapshot,
                                      "competition_eligible": False, "ima_provenance": provenance,
                                      "ima_verification": ima_verification,
                                      "development_single_user_only": True},
                  "task": task, "evidence": {"facts": facts, "source_refs": refs, "business_rules": []},
                  "allowed_assets": [], "policy": policy,
                  "quote_context": self.quote_state(False)}
        if development_stage is not None:
            bundle["trusted_context"].update(development_stage=development_stage, export_allowed=False)
        return "ready", {"task_bundle": bundle, "asset_candidates": candidates,
                         "omitted_fact_fields": omitted, "source_mode": mode,
                         "competition_eligible": False, **self.quote_state(False)}

    def handle(self, method, path, body, authorization, proof=None):
        self.authenticate(authorization)
        if not isinstance(body, dict):
            raise BridgeError("INVALID_INPUT", "JSON body must be an object.")
        if method != "POST":
            raise BridgeError("NOT_IMPLEMENTED", "This endpoint is not implemented.", "error", 501)
        if path == "/v1/contexts/resolve":
            return self.resolve(body)
        if path == "/v1/kb/evidence":
            return self.evidence(body, proof)
        if path == "/v1/quotes/solve":
            self._check_scope(body)
            context = self._verify(body.get("source_context_ref"), proof)
            return "needs_source", {"reason": "FOUR_LEVELS_PENDING",
                                    **self.quote_state(True, context["task"]["purchase_plan_required"])}
        raise BridgeError("NOT_IMPLEMENTED", "This endpoint is not implemented.", "error", 501)

    def audit(self):
        snapshot = self.source.snapshot()
        counts, total = {}, 0
        for directory, _, files in os.walk(self.config.root, followlinks=False):
            for name in files:
                file = Path(directory) / name
                counts[file.suffix.lower() or "<none>"] = counts.get(file.suffix.lower() or "<none>", 0) + 1
                total += file.stat().st_size
        models = self.source.models()
        templates = 0
        p4_files = list((self.config.root / "P4-价格政策库（机密）").glob("*.md"))
        for file in p4_files:
            raw = self.source.text(file.relative_to(self.config.root).as_posix())
            section = raw.split("## 登记字段", 1)[-1].split("\n## ", 1)[0]
            fields = [line for line in section.splitlines() if line.startswith("- ")]
            if ("受控模板" in raw and "v0.1（空模板）" in raw and fields and
                    all(line.rstrip().endswith("：") for line in fields)):
                templates += 1
        if snapshot != self.source.snapshot():
            raise BridgeError("SOURCE_CHANGED", "Source changed during audit.", "needs_source", 409)
        return {"source_snapshot_ref": snapshot, "file_count": sum(counts.values()), "types": counts,
                "bytes": total, "product_count": len(models), "source_mode": "local_snapshot",
                "competition_eligible": False, "real_quote_enabled": False,
                "quote_status": "BLOCKED_SOURCE_UNVERIFIED", "p4_file_count": len(p4_files),
                "p4_unfilled_template_count": templates, "multi_store_authorization_implemented": False}

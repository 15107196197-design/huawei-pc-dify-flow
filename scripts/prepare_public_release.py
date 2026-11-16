#!/usr/bin/env python3
"""Check or stage an exact, sanitized public source package. Never publish.

Default/--check performs an in-memory check without writing files. --out NEW_DIR
writes only the explicit allowlist plus a hash manifest, refusing an existing
directory. No git, network, credential discovery, user-KB access, generated DSL,
browser state, installed dependencies or upstream sources are included.

The only private files read (if present) are THIS PROJECT'S service-token and
Dify infra .env listed in PRIVATE_SECRET_FILES. Their sensitive values are used
in memory for exact-match checks, never printed, hashed into a public manifest,
copied or searched in other credential stores. Generic identifiers such as
kb_id/token in application code are not secrets and are preserved.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
from urllib.parse import parse_qsl, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2_000_000
PRIVATE_SECRET_FILES = (
    ".local/knowledge-bridge/service-token",
    ".local/dify/upstream/docker/.env",
)

# Each entry is reviewed source, not a recursive directory glob. New files must
# be deliberately added; putting a document under docs/ does not grant release.
ALLOWED_FILES = (
    ".gitignore",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "QUICKSTART.md",
    "apps/README.md",
    "apps/full-workflow.candidate.yml",
    "apps/product-intro.candidate.yml",
    "apps/product-intro-revise.candidate.yml",
    "apps/stage-model.candidate.yml",
    "apps/vision-probe.candidate.yml",
    ".github/workflows/offline-contracts.yml",
    "docs/acceptance-cases.csv",
    "docs/agent-development-guide.md",
    "docs/dify-local-deployment.md",
    "docs/dify-prompt-binding-guide.md",
    "docs/HOW-TO-CONFIGURE.md",
    "docs/knowledge-source-modes.md",
    "docs/local-bridge-network-plan.md",
    "docs/local-knowledge-bridge.md",
    "docs/modelscope-space-readme.md",
    "docs/multi-model-design.md",
    "docs/platform-workflow-build-guide.md",
    "docs/prompt-design-notes.md",
    "docs/quote-optimization-design.md",
    "docs/requirements-design.md",
    "docs/sales-demo-script-design.md",
    "docs/tooling-and-connectors.md",
    "prompts/article-system.md",
    "prompts/layout-system.md",
    "prompts/platform-strategy-system.md",
    "prompts/poster-system.md",
    "prompts/product-intro-system.md",
    "prompts/quote-explain-system.md",
    "prompts/review-system.md",
    "prompts/sales-demo-system.md",
    "prompts/scene-parse-system.md",
    "prompts/visual-review-system.md",
    "specs/business-tool-contract.md",
    "specs/commerce-rule-candidate.example.json",
    "specs/model-routing.example.json",
    "specs/prompt-registry.json",
    "specs/quote-configuration.example.json",
    "services/__init__.py",
    "services/knowledge_bridge/__init__.py",
    "services/knowledge_bridge/__main__.py",
    "services/knowledge_bridge/bridge.py",
    "services/poster_renderer/__init__.py",
    "services/poster_renderer/renderer.py",
    "services/quote_engine/__init__.py",
    "services/quote_engine/engine.py",
    "services/image_provider/__init__.py",
    "services/image_provider/qwen_image.py",
    "scripts/build_dify_bundle.py",
    "scripts/build_full_dify_bundle.py",
    "scripts/run_local_bridge.py",
    "scripts/prepare_public_release.py",
    "tests/test_bridge_squid_policy.py",
    "tests/test_dify_bundle.py",
    "tests/test_full_dify_bundle.py",
    "tests/test_knowledge_bridge.py",
    "tests/test_poster_renderer.py",
    "tests/test_quote_engine.py",
    "tests/test_qwen_image_provider.py",
    "deploy/dify-local/README.md",
    "deploy/dify-local/dify-local.sh",
    "deploy/dify-local/disk_guard.py",
    "deploy/dify-local/docker-compose.override.yaml",
    "deploy/dify-local/generate-bridge-squid.py",
    "deploy/dify-local/preflight.py",
    "deploy/dify-local/probe-bridge-network.py",
    "deploy/dify-local/squid-bridge.conf.template",
)

EXCLUDED = (
    ".local/", "research/", "submission/", "workflows/", "user knowledge sources and original media",
    "runtime/import DSL and generated bundles", "env/credentials/tokens/private keys",
    "upstream/runtime/VM/dependency files", "bytecode/cache/output files",
)
PRIVATE_LINK_PARTS = {".local", ".private", "research", "submission", "workflows"}
MD_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)]+)\)")
URL = re.compile(r"https?://[^\s<>\"'`）)]+")
PRIVATE_QUERY_KEYS = {
    "shareid", "share_id", "knowledge_base_id", "kb_id", "knowledgebaseid",
    "token", "access_token", "api_key", "signature", "expires", "x-oss-signature",
    "x-amz-signature", "x-amz-credential", "ossaccesskeyid",
}
PUBLIC_NOTE = (
    "> 公开源码副本：不包含用户知识库、原图、私有取证底稿、运行时DSL或凭证。"
    "本机应用链接已改为自行部署后的工作室入口；具体能力以本仓库README当前状态为准。\n\n"
)


def _regular_path(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_relative_to(ROOT) or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts):
        raise ValueError("UNSAFE_RELATIVE_PATH")
    current = ROOT
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("SYMLINK_SOURCE_REJECTED")
    if not path.is_file():
        raise ValueError("REQUIRED_SOURCE_FILE_MISSING")
    return path


def _secret_values() -> tuple[list[bytes], int]:
    values, count = set(), 0
    for relative in PRIVATE_SECRET_FILES:
        candidate = ROOT / relative
        if not candidate.exists() and not candidate.is_symlink():
            continue
        path = _regular_path(relative)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("PRIVATE_COMPARISON_FILE_TOO_LARGE")
        text = path.read_text(encoding="utf-8")
        count += 1
        if path.name == "service-token":
            value = text.strip()
            if value:
                values.add(value.encode())
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw = line.removeprefix("export ").split("=", 1)
            if not re.search(r"(?:^|_)(?:SECRET|PASSWORD|TOKEN|API_KEY|ACCESS_KEY|PRIVATE_KEY)(?:_|$)", name.upper()):
                continue
            value = raw.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if not value or "${" in value:
                continue  # unresolved variable references are not credential values
            values.add(value.encode())
    return sorted(values, key=len, reverse=True), count


def _synthetic_or_placeholder(value: str) -> bool:
    normalized = unquote(value).lower()
    return (not value or any(word in normalized for word in (
        "synthetic", "example", "placeholder", "your_", "your-", "<", ">", "{", "}", "xxx"
    )) or len(set(normalized)) <= 1)


def _private_url(value: str) -> bool:
    if value.startswith(("https://[^", "http://[^")):
        return False  # URL-matching regular expression source, not a literal URL
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            if (parsed.username, parsed.password) == ("user", "password") and (parsed.hostname or "").startswith("{"):
                return False  # explicit synthetic rejection test with a format placeholder
            return True
        return any(name.lower() in PRIVATE_QUERY_KEYS and not _synthetic_or_placeholder(item)
                   for name, item in parse_qsl(parsed.query, keep_blank_values=True))
    except ValueError:
        return True


def _sanitize_markdown(relative: str, text: str) -> tuple[str, dict]:
    changes = {}

    def mark(name):
        changes[name] = changes.get(name, 0) + 1

    def link(match):
        image, label, raw_target = match.groups()
        target = raw_target.strip().strip("<>")
        if target.startswith("#"):
            return match.group()
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            if target.startswith("file:") or _private_url(target):
                mark("private_link_replaced")
                return label + "（私有来源链接未公开）"
            if re.match(r"https?://(?:localhost|127\.0\.0\.1):8080/app/[^/]+/workflow", target):
                mark("local_app_id_removed")
                return f"[{label}](http://localhost:8080/apps)"
            return match.group()
        path_only = unquote(target.split("#", 1)[0].split("?", 1)[0])
        resolved = posixpath.normpath(posixpath.join(str(PurePosixPath(relative).parent), path_only))
        if (set(PurePosixPath(resolved).parts) & PRIVATE_LINK_PARTS or path_only.startswith("/")
                or resolved not in ALLOWED_FILES):
            mark("unpublished_local_link_replaced")
            return label + "（本地记录或生成材料，未随公开源码发布）"
        return match.group()

    text = MD_LINK.sub(link, text)
    # Match a description, not a hardcoded private owner's/library name.
    text, count = re.subn(r"已加入[“\"][^”\"\n]{1,120}知识库[”\"]", "已加入“<IMA_KNOWLEDGE_BASE_NAME>”", text)
    if count:
        changes["private_kb_name_replaced"] = count
    personal_home = str(Path.home())
    if personal_home not in {"/", "/root"}:
        text, count = re.subn(re.escape(personal_home) + r"[^\s`\"'<>）)；，。]*", "<LOCAL_PATH>", text)
        if count:
            changes["absolute_personal_path_replaced"] = count

    def private_url(match):
        if _private_url(match.group()):
            mark("private_url_replaced")
            return "<PRIVATE_SOURCE_URL>"
        return match.group()

    text = URL.sub(private_url, text)
    if relative == "README.md":
        title_end = text.find("\n")
        text = text[:title_end + 1] + "\n" + PUBLIC_NOTE + text[title_end + 1:].lstrip("\n")
        mark("public_boundary_note_added")
    return text, changes


def _find_issues(relative: str, text: str, data: bytes, secrets: list[bytes]) -> list[str]:
    issues = []
    if any(value in data for value in secrets):
        issues.append("KNOWN_PRIVATE_SECRET_MATCH")
    personal_home = str(Path.home())
    if personal_home not in {"/", "/root"} and personal_home in text:
        issues.append("ABSOLUTE_PERSONAL_PATH")
    if any(_private_url(match.group()) for match in URL.finditer(text)):
        issues.append("PRIVATE_OR_SIGNED_URL")
    # Detect actual literal IDs, not field names, regex syntax or parameter docs.
    identifier_pattern = r"(?:knowledge_base_id|knowledgeBaseId|kb_id|shareId|share_id)\s*[=:]\s*[\"']([A-Za-z0-9_-]{8,})[\"']"
    if any(not _synthetic_or_placeholder(value) for value in re.findall(identifier_pattern, text)):
        issues.append("LITERAL_PRIVATE_KB_IDENTIFIER")
    credential_patterns = (r"sk-[A-Za-z0-9]{24,}", r"gh[pousr]_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{40,}")
    if any(not _synthetic_or_placeholder(match.group())
           for pattern in credential_patterns for match in re.finditer(pattern, text)):
        issues.append("CREDENTIAL_LITERAL_PATTERN")
    if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{64,}-----END", text):
        issues.append("PRIVATE_KEY_BLOCK")
    if relative.endswith(".md"):
        for match in MD_LINK.finditer(text):
            target = match.group(3).strip().strip("<>")
            if target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            resolved = posixpath.normpath(posixpath.join(str(PurePosixPath(relative).parent), unquote(target.split("#", 1)[0])))
            if resolved not in ALLOWED_FILES:
                issues.append("UNRESOLVED_LOCAL_LINK")
    return sorted(set(issues))


def prepare() -> tuple[dict[str, bytes], dict]:
    if len(set(ALLOWED_FILES)) != len(ALLOWED_FILES):
        raise ValueError("DUPLICATE_ALLOWLIST_ENTRY")
    secrets, private_source_count = _secret_values()
    prepared, manifests, issues, transformed = {}, [], [], []
    for relative in ALLOWED_FILES:
        path = _regular_path(relative)
        before = path.stat()
        if before.st_size > MAX_FILE_BYTES:
            raise ValueError("SOURCE_FILE_TOO_LARGE:" + relative)
        data = path.read_bytes()
        after = path.stat()
        if (before.st_mtime_ns, before.st_size, before.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino):
            raise ValueError("SOURCE_CHANGED_RETRY:" + relative)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("NON_UTF8_SOURCE_REJECTED:" + relative) from None
        changes = {}
        if relative.endswith(".md"):
            text, changes = _sanitize_markdown(relative, text)
            data = text.encode("utf-8")
        found = _find_issues(relative, text, data, secrets)
        if found:
            issues.append({"path": relative, "reasons": found})
        if changes:
            transformed.append({"path": relative, "changes": changes})
        if relative.endswith(".json"):
            try:
                json.loads(text)
            except (ValueError, TypeError):
                issues.append({"path": relative, "reasons": ["INVALID_JSON"]})
        if relative.endswith(".py"):
            try:
                compile(text, relative, "exec")
            except SyntaxError:
                issues.append({"path": relative, "reasons": ["INVALID_PYTHON"]})
        prepared[relative] = data
        manifests.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                          "mode": "0755" if relative.endswith(".sh") else "0644"})
    report = {
        "status": "PASS" if not issues else "BLOCKED", "mode": "check",
        "files": len(manifests), "known_private_secret_matches": sum(
            "KNOWN_PRIVATE_SECRET_MATCH" in row["reasons"] for row in issues),
        "private_secret_sources_compared": private_source_count,
        "issues": issues, "sanitized_files": transformed, "excluded": list(EXCLUDED),
        "manifest": manifests,
    }
    # No secret values or their digests are included in the public report.
    return prepared, report


def _new_output(path: Path) -> Path:
    path = path.absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("OUTPUT_MUST_BE_A_NEW_DIRECTORY")
    if not path.parent.is_dir():
        raise ValueError("OUTPUT_PARENT_MUST_ALREADY_EXIST")
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            raise ValueError("SYMLINK_OUTPUT_PARENT_REJECTED")
    return path


def stage(path: Path, prepared: dict[str, bytes], report: dict) -> None:
    path = _new_output(path)
    path.mkdir(mode=0o755)
    manifest = {"format_version": "1", "created_at": datetime.now(timezone.utc).isoformat(),
                "scope": "sanitized_source_only_no_user_knowledge_or_runtime_credentials",
                "files": report["manifest"], "sanitized_files": report["sanitized_files"],
                "known_private_secret_matches": 0, "excluded": report["excluded"]}
    payloads = dict(prepared)
    payloads["PUBLIC_RELEASE_MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    for relative, data in payloads.items():
        destination = path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755 if relative.endswith(".sh") else 0o644)
        with os.fdopen(fd, "wb") as output:
            output.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="read-only check (the default)")
    modes.add_argument("--out", type=Path, help="stage into a NEW directory; never git/network/publish")
    args = parser.parse_args()
    try:
        if args.out is not None:
            _new_output(args.out)  # refuse overwrite before private-file reads
        prepared, report = prepare()
        if report["status"] == "PASS" and args.out is not None:
            stage(args.out, prepared, report)
            report["mode"] = "staged"
            report["output_directory_name"] = args.out.name
            report["hash_manifest"] = "PUBLIC_RELEASE_MANIFEST.json"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "PASS" else 2
    except (ValueError, OSError) as error:
        # OSError text may contain local paths; never echo it.
        reason = str(error) if isinstance(error, ValueError) else "FILESYSTEM_OPERATION_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": reason}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())

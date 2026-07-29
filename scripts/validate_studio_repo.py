#!/usr/bin/env python3
"""Validate a Leo Studio repository manifest and release contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


REPOSITORY_RE = re.compile(r"^(?:[A-Z][A-Za-z0-9]*_Studio|Studio_App_Template)$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
CONTAINER_RE = re.compile(
    r"^ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9]+(?:-[a-z0-9]+)*$"
)
BASE_FILES = (
    "studio.json",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "SECURITY.md",
    ".env.example",
    ".gitignore",
    ".dockerignore",
)
RELEASE_FILES = BASE_FILES + (
    "Dockerfile",
    "compose.yaml",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
)
HIGH_CONFIDENCE_SECRET_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,}|"
    r"AKIA[0-9A-Z]{16}"
)
APACHE_2_NORMALIZED_SHA256 = "60418cdfd5cf14184d9dc03c717f14b0cbd864e98de40bcc239f989212e27db2"


def normalized_license(value: str) -> str:
    return value.replace("\r\n", "\n").strip()


def load_manifest(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append("studio.json is missing.")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"studio.json is invalid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("studio.json must contain a JSON object.")
        return {}
    return value


def validate_manifest(manifest: dict[str, Any], errors: list[str]) -> None:
    required = {
        "schemaVersion",
        "displayName",
        "repository",
        "slug",
        "version",
        "license",
        "container",
        "defaultPort",
        "healthEndpoint",
        "dataDirectory",
        "aiProfile",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        errors.append(f"studio.json missing keys: {', '.join(missing)}")
        return

    if manifest["schemaVersion"] != 1:
        errors.append("schemaVersion must be 1.")
    display = manifest["displayName"]
    repository = manifest["repository"]
    slug = manifest["slug"]
    version = manifest["version"]
    container = manifest["container"]
    if not isinstance(display, str) or not display.endswith(" Studio"):
        errors.append("displayName must end with ' Studio'.")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        errors.append("repository must use Product_Studio or Studio_App_Template.")
    if isinstance(display, str) and isinstance(repository, str) and repository != "Studio_App_Template":
        expected_repository = display.removesuffix(" Studio").replace(" ", "") + "_Studio"
        if repository != expected_repository:
            errors.append(f"repository must match displayName: expected {expected_repository}.")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        errors.append("slug must be lowercase kebab case.")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        errors.append("version must be valid SemVer.")
    if manifest["license"] != "Apache-2.0":
        errors.append("license must be Apache-2.0.")
    if not isinstance(container, str) or not CONTAINER_RE.fullmatch(container):
        errors.append("container must be a lowercase ghcr.io owner/image path.")
    elif isinstance(slug, str) and not container.endswith(f"/{slug}"):
        errors.append("container image name must equal slug.")
    port = manifest["defaultPort"]
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        errors.append("defaultPort must be an integer from 1 through 65535.")
    health = manifest["healthEndpoint"]
    if not isinstance(health, str) or not health.startswith("/"):
        errors.append("healthEndpoint must begin with '/'.")
    data_dir = manifest["dataDirectory"]
    if not isinstance(data_dir, str) or not data_dir.startswith("/"):
        errors.append("dataDirectory must be an absolute container path.")
    if isinstance(slug, str) and manifest["aiProfile"] != slug:
        errors.append("aiProfile must equal slug unless the standard documents an exception.")


def validate_license(root: Path, errors: list[str]) -> None:
    license_path = root / "LICENSE"
    if not license_path.exists():
        return
    normalized = normalized_license(license_path.read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if actual_hash != APACHE_2_NORMALIZED_SHA256:
        errors.append("LICENSE does not match the bundled unmodified Apache 2.0 text.")


def validate_version_alignment(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    version = manifest.get("version")
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        python_version = (pyproject.get("project") or {}).get("version")
        if python_version != version:
            errors.append(f"pyproject.toml version must equal studio.json version ({version}).")
    web_package_path = root / "web" / "package.json"
    if web_package_path.exists():
        web_package = json.loads(web_package_path.read_text(encoding="utf-8"))
        if web_package.get("version") != version:
            errors.append(f"web/package.json version must equal studio.json version ({version}).")


def tracked_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return [root / item.decode() for item in result.stdout.split(b"\0") if item]


def scan_current_tree(root: Path, errors: list[str], warnings: list[str]) -> None:
    files = tracked_files(root)
    relative = {str(path.relative_to(root)) for path in files}
    if ".env" in relative:
        errors.append("A real .env file is tracked by Git.")
    for path in files:
        try:
            if path.stat().st_size > 2_000_000:
                continue
            value = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if HIGH_CONFIDENCE_SECRET_RE.search(value):
            errors.append(f"Possible high-confidence secret in {path.relative_to(root)}.")
    if (root / ".git").exists():
        warnings.append("Run a dedicated full Git history secret scan before public visibility.")


def validate_repository(root: Path, mode: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest = load_manifest(root / "studio.json", errors)
    if manifest:
        validate_manifest(manifest, errors)
        validate_version_alignment(root, manifest, errors)
    required = RELEASE_FILES if mode == "release" else BASE_FILES
    for relative in required:
        if not (root / relative).exists():
            errors.append(f"Required file is missing: {relative}")
    validate_license(root, errors)
    scan_current_tree(root, errors, warnings)
    third_party = root / "THIRD_PARTY_NOTICES.md"
    if third_party.exists() and "Replace or remove this row" in third_party.read_text(encoding="utf-8"):
        errors.append("THIRD_PARTY_NOTICES.md still contains its template row.")
    for relative in ("NOTICE", "TRADEMARKS.md"):
        path = root / relative
        if path.exists() and re.search(r"\[[A-Z_]+\]", path.read_text(encoding="utf-8")):
            errors.append(f"{relative} still contains template placeholders.")
    return {
        "ok": not errors,
        "mode": mode,
        "root": str(root),
        "manifest": manifest,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--mode", choices=("prepare", "release"), default="release")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    result = validate_repository(Path(args.path).resolve(), args.mode)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Studio repository validation: " + ("PASS" if result["ok"] else "FAIL"))
        for error in result["errors"]:
            print(f"ERROR: {error}")
        for warning in result["warnings"]:
            print(f"WARN: {warning}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

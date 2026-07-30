#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "PRIVATE_KEY_BLOCK": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GITHUB_TOKEN": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9_]{20,}\b"),
    "OPENAI_API_KEY": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "AWS_ACCESS_KEY_ID": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "SLACK_TOKEN": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
}
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
}
SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
WRITE_API_RE = re.compile(r"\bgh\s+api\b.*(?:-X|--method)\s+(?:POST|PUT|PATCH|DELETE)\b", re.I)


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"])
    return [ROOT / p.decode("utf-8") for p in raw.split(b"\0") if p]


def line_numbers(text: str, pattern: re.Pattern[str]) -> list[int]:
    return [i for i, line in enumerate(text.splitlines(), 1) if pattern.search(line)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/repository-safety/repository_safety_audit.json")
    args = ap.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    workflow_findings: list[dict] = []
    secret_findings: list[dict] = []

    workflows = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    for path in workflows:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(ROOT))
        lines = text.splitlines()
        contents_write = [i for i, line in enumerate(lines, 1) if re.match(r"^\s*contents\s*:\s*write\s*(?:#.*)?$", line)]
        git_push = [i for i, line in enumerate(lines, 1) if re.search(r"\bgit\s+push\b", line)]
        git_commit = [i for i, line in enumerate(lines, 1) if re.search(r"\bgit\s+commit\b", line)]
        write_api = [i for i, line in enumerate(lines, 1) if WRITE_API_RE.search(line)]
        pr_merge = [i for i, line in enumerate(lines, 1) if re.search(r"\bgh\s+pr\s+merge\b", line)]
        set_plus_e = [i for i, line in enumerate(lines, 1) if re.search(r"\bset\s+\+e\b", line)]
        exit_zero = [i for i, line in enumerate(lines, 1) if re.search(r"\bexit\s+0\b", line)]
        or_true = [i for i, line in enumerate(lines, 1) if "|| true" in line]
        explicit_fail = [i for i, line in enumerate(lines, 1) if re.search(r"\bexit\s+1\b", line)]
        captures_rc = any(re.search(r"(?:^|\s)(?:code|rc|exit_code|[A-Z0-9_]*EXIT)=\$\?", line) for line in lines)

        write_capable = bool(contents_write or git_push or git_commit or write_api or pr_merge)
        if write_capable:
            errors.append(f"write-capable workflow: {rel}")
        if set_plus_e and not (captures_rc and explicit_fail):
            warnings.append(f"set +e without obvious capture+final-fail pair: {rel}")

        if any((contents_write, git_push, git_commit, write_api, pr_merge, set_plus_e, exit_zero, or_true)):
            workflow_findings.append({
                "path": rel,
                "contents_write_lines": contents_write,
                "git_push_lines": git_push,
                "git_commit_lines": git_commit,
                "write_api_lines": write_api,
                "pr_merge_lines": pr_merge,
                "set_plus_e_lines": set_plus_e,
                "exit_zero_lines": exit_zero,
                "or_true_lines": or_true,
                "explicit_fail_lines": explicit_fail,
                "captures_exit_code": captures_rc,
            })

    for path in tracked_files():
        rel = str(path.relative_to(ROOT))
        if path.name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
            secret_findings.append({"path": rel, "line": None, "type": "SENSITIVE_FILENAME"})
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            raw = path.read_bytes()
            if b"\0" in raw:
                continue
            text = raw.decode("utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            for line_no in line_numbers(text, pattern):
                secret_findings.append({"path": rel, "line": line_no, "type": label})

    if secret_findings:
        errors.extend(f"possible secret exposure: {x['path']}:{x['line']} [{x['type']}]" for x in secret_findings)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "gate": "PUBLIC_REPOSITORY_AND_WORKFLOW_SAFETY",
        "pass": not errors,
        "workflow_count": len(workflows),
        "write_capable_workflow_count": sum(1 for x in workflow_findings if any((x['contents_write_lines'],x['git_push_lines'],x['git_commit_lines'],x['write_api_lines'],x['pr_merge_lines']))),
        "workflow_findings": workflow_findings,
        "secret_findings": secret_findings,
        "warnings": warnings,
        "errors": errors,
        "secret_values_redacted": True,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "gate": report["gate"],
        "pass": report["pass"],
        "workflow_count": report["workflow_count"],
        "write_capable_workflow_count": report["write_capable_workflow_count"],
        "secret_finding_count": len(secret_findings),
        "warning_count": len(warnings),
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

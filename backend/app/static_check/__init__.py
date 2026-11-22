"""Static check of *authorized* files (team-owned, organizer-provided or otherwise authorized).

Flags suspected hardcoded passwords, API keys and tokens without executing anything. Detection uses
known key formats, secret-like names and a randomness (Shannon entropy) check for long strings.
Only category, rule, file, line, column, time and review status are stored: never the value, never
printed, never exported, never used for training, and credentials are never tested.

    python -m app.static_check [--root DIR ...] [--host HOST]
"""
from __future__ import annotations

import argparse
import fnmatch
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import settings
from app.db import db, utcnow

EXTS = {".html", ".htm", ".js", ".mjs", ".cjs", ".ts", ".json", ".env", ".yaml", ".yml", ".xml", ".config", ".ini",
        ".txt", ".php", ".properties", ".toml", ".cfg", ".conf"}
MAX_BYTES = 5_000_000
RULES: list[tuple[str, str, re.Pattern]] = [
    ("aws_access_key", "aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws_secret_key", "aws-secret-assignment", re.compile(r"aws.{0,20}secret.{0,20}[\"'][A-Za-z0-9/+=]{40}[\"']", re.I)),
    ("google_api_key", "google-api-key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("stripe_key", "stripe-secret-key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{20,}\b")),
    ("github_token", "github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("slack_token", "slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private_key", "pem-private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("jwt", "json-web-token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}")),
    ("generic_secret", "secret-name-assignment", re.compile(
        r"(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key|auth[_-]?token|token|client[_-]?secret|private[_-]?key)"
        r"[\"']?\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']", re.I)),
]
QUOTED_RE = re.compile(r"[\"']([A-Za-z0-9+/=_\-]{24,})[\"']")


@dataclass
class Finding:
    category: str
    rule: str
    file_path: str
    line: int
    col: int


def shannon(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def scan_text(text: str, rel: str) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    for ln, line in enumerate(text.splitlines(), start=1):
        for category, rule, rx in RULES:
            for m in rx.finditer(line):
                key = (ln, m.start())
                if key in seen:
                    continue
                seen.add(key)
                out.append(Finding(category, rule, rel, ln, m.start() + 1))
        for m in QUOTED_RE.finditer(line):
            val = m.group(1)
            if (ln, m.start()) in seen or any(f.line == ln and abs(f.col - 1 - m.start()) < 40 for f in out):
                continue
            classes = sum(bool(re.search(p, val)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
            if shannon(val) >= 4.2 and classes == 3 and not val.startswith(("http", "data")):
                out.append(Finding("high_entropy_string", "entropy>=4.2", rel, ln, m.start() + 1))
    return out


def _host_map(root: Path) -> list[tuple[str, str]]:
    manifest = root / "manifest.yaml"
    if not manifest.is_file():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return [(str(k), str(v)) for k, v in (data.get("related_hosts") or {}).items()]


def scan_roots(roots: list[Path], host: str | None = None, store: bool = True) -> list[Finding]:
    findings: list[Finding] = []
    for root in roots:
        root = root.resolve()
        if not root.is_dir():
            continue
        hosts = _host_map(root)
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in EXTS or path.name == "manifest.yaml":
                continue
            if path.stat().st_size > MAX_BYTES:
                continue
            rel = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            file_findings = scan_text(text, f"{root.name}/{rel}")
            related = host or next((h for pat, h in hosts if fnmatch.fnmatch(rel, pat)), None)
            findings.extend(file_findings)
            if store and file_findings:
                with db() as conn:
                    for f in file_findings:
                        conn.execute(
                            "INSERT INTO static_findings (category, rule, file_path, line, col, related_host, "
                            "detected_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                            (f.category, f.rule, f.file_path, f.line, f.col, related, utcnow()))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", help="authorized directory (repeatable)")
    ap.add_argument("--host", help="site these files belong to (for the case brief)")
    args = ap.parse_args(argv)
    roots = [Path(r) for r in (args.root or settings.static_authorized_dirs)]
    findings = scan_roots(roots, args.host)
    print(f"static check: {len(findings)} suspected secrets in {len({f.file_path for f in findings})} files "
          f"(values are never stored or printed)")
    for f in findings:
        print(f"  {f.category:20s} {f.file_path}:{f.line}:{f.col}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

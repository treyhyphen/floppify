#!/usr/bin/env python3
"""Reject files containing common high-confidence credential patterns."""

import argparse
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "generic secret assignment": re.compile(
        r"(?im)^\s*(?:password|passwd|client_secret|api_key|access_token)\s*[=:]\s*['\"]?[^\s'\"#]{8,}"
    ),
}


def staged_files() -> list[Path]:
    """Return added or modified files staged in Git."""
    output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], text=True
    )
    return [Path(line) for line in output.splitlines() if line]


def main() -> int:
    """Scan explicit paths or the current staged file set."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    failed = False
    for path in args.paths or staged_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                print(f"Potential {label} in {path}; refusing commit (value suppressed).")
                failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

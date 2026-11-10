#!/usr/bin/env python3
"""Check that every relative link in every tracked Markdown file resolves.

Usage: check_links.py [REPO_ROOT]   (default: current directory)

Checks inline links [text](target) and images ![alt](target). Ignores URLs
(http, https, mailto and any other scheme) and pure #fragments, skips fenced
code blocks and inline code spans. A target starting with "/" is relative to
the repository root, as on GitHub. Exit 0 when all links resolve, 1 otherwise.
"""
import os
import re
import subprocess
import sys
from urllib.parse import unquote

# Matches the "](target)" part, so nested [![alt](img)](link) yields both links.
LINK = re.compile(r"""\]\(\s*<?([^)>\s]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)""")
FENCE = re.compile(r"^\s*(```+|~~~+)")
CODE_SPAN = re.compile(r"`+[^`]*`+")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def tracked_markdown(root):
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z", "--", "*.md"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def links_in(text):
    """Yield (line_number, target) for each link outside fenced code."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        m = FENCE.match(line)
        if m:
            marker = m.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence:
            continue
        for found in LINK.finditer(CODE_SPAN.sub("", line)):
            yield number, found.group(1)


def check(root):
    problems = []
    for rel in tracked_markdown(root):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for number, target in links_in(text):
            if target.startswith("#") or SCHEME.match(target):
                continue
            file_part = unquote(re.split(r"[?#]", target, maxsplit=1)[0])
            if not file_part:
                continue
            base = root if file_part.startswith("/") else os.path.dirname(path)
            resolved = os.path.join(base, file_part.lstrip("/"))
            if not os.path.exists(resolved):
                problems.append(f"{rel}:{number}: broken link '{target}' (no such file or directory)")
    return problems


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    problems = check(root)
    for p in problems:
        print(p)
    if problems:
        print(f"FAIL: {len(problems)} broken relative link(s)")
        return 1
    print("OK: all relative Markdown links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Block commits that carry a credential or force-add an ignored file.

Why: 2026-03-13 commit 72efc36 force-added the git-ignored config/llm_config.json with four real
OpenRouter keys in it (dead by 2026-10, but the same slip with a live key would be a leak). There
were no hooks to stop it.

Checks the staged change only:
  1. a staged file that .gitignore says is ignored (i.e. added with `git add -f`)
  2. an added line that holds a credential: a known key shape, a private-key block, or a
     secret-named JSON/env field with a long literal value

A line that is deliberately fake can carry the marker `secret-scan: allow`.
Install:  git config core.hooksPath scripts/git-hooks
Stdlib only; never prints the credential itself, only file, line and the first 4 characters.
"""
import re
import subprocess
import sys
from typing import Iterable, List, Tuple

KEY_SHAPES = [
    ("API key (sk-...)", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
# "api_key": "<literal>", SECRET_TOKEN=<literal> ...
FIELD = re.compile(
    r"""(?ix)["']?[\w.-]*(api[_-]?key|secret|token|password|authorization)[\w.-]*["']?\s*[:=]\s*["']?([A-Za-z0-9_\-+/=.]{24,})["']?""")
PLACEHOLDER = re.compile(r"(?i)your|example|placeholder|changeme|xxxx|dummy|fake|\$\{|<[a-z_ -]+>|env:|key_var|redacted")
ALLOW = "secret-scan: allow"


DATA_SUFFIXES = (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".conf")


def is_data_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(DATA_SUFFIXES) or name.startswith(".env") or ".env." in name


def scan_line(line: str, generic: bool = True) -> List[Tuple[str, str]]:
    """(kind, first-4-chars) for every credential-looking token on the line.

    `generic` enables the secret-named-field rule; code files turn it off because
    `self.api_key` / `config.password` are references, not values.
    """
    if ALLOW in line:
        return []
    found = []
    for kind, rx in KEY_SHAPES:
        for m in rx.finditer(line):
            if not PLACEHOLDER.search(m.group(0)):
                found.append((kind, m.group(0)[:4]))
    for m in (FIELD.finditer(line) if generic else ()):
        value = m.group(2)
        if not PLACEHOLDER.search(value) and not PLACEHOLDER.search(m.group(0)):
            found.append((f"literal value for '{m.group(1).lower()}'", value[:4]))
    return found


def scan_diff(diff_text: str) -> List[Tuple[str, int, str, str]]:
    """(file, line_no, kind, first4) for each added line of a unified diff that looks like a credential."""
    hits, path, lineno = [], "?", 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) - 1 if m else 0
        elif line.startswith("+"):
            lineno += 1
            for kind, first4 in scan_line(line[1:], generic=is_data_file(path)):
                hits.append((path, lineno, kind, first4))
        elif not line.startswith("-"):
            lineno += 1
    return hits


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def ignored_among(paths: Iterable[str]) -> List[str]:
    out = []
    for p in paths:
        # --no-index: report a path as ignored even though it is being added to the index
        if subprocess.run(["git", "check-ignore", "--no-index", "-q", p]).returncode == 0:
            out.append(p)
    return out


def main(argv: List[str]) -> int:
    if "--staged" not in argv:
        print(__doc__)
        return 2
    problems = []
    staged = [p for p in _git("diff", "--cached", "--name-only", "--diff-filter=AM").splitlines() if p]
    for p in ignored_among(staged):
        problems.append(f"{p}: matches .gitignore but is staged (git add -f?). Ignored files hold local config and secrets.")
    for path, lineno, kind, first4 in scan_diff(_git("diff", "--cached", "--unified=0", "--no-color")):
        problems.append(f"{path}:{lineno}: {kind} (starts '{first4}...'). Use key_var/env, or mark a deliberate fake with 'secret-scan: allow'.")
    if problems:
        print("commit blocked by scripts/secret_scan.py:\n  " + "\n  ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

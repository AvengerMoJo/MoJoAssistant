"""Shell-command parsing shared by the SecurityGate (cost) and bash_exec (blocklist).

A command string is split into its simple commands at ``| ; & && || ( )``
and newlines, so that ``ls && rm x`` is seen as two commands, not one.
"""
import os
import shlex
from typing import List, Optional

# Commands that only observe.  Anything not listed here is not read-only.
READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "stat", "file", "tree", "du",
    "grep", "egrep", "fgrep", "rg", "find", "diff", "sort", "uniq", "cut",
    "tr", "nl", "echo", "pwd", "basename", "dirname", "realpath", "readlink",
    "git",
}
READ_ONLY_GIT = {"status", "log", "diff", "show", "ls-files", "grep", "rev-parse", "blame"}
# find actions that run or write.
_FIND_WRITES = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
# Exit codes that mean "no result", not "failed".
_NO_MATCH_RC = {"grep": 1, "egrep": 1, "fgrep": 1, "rg": 1, "diff": 1}


def split_commands(command: str) -> Optional[List[List[str]]]:
    """Return the simple commands in ``command`` as token lists, operators
    removed; None when it cannot be parsed or uses a backtick substitution."""
    if "`" in command:
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    commands: List[List[str]] = [[]]
    for tok in tokens:
        if tok and set(tok) <= set("|;&()"):
            commands.append([])
        else:
            commands[-1].append(tok)
    return [c for c in commands if c]


def base_name(tokens: List[str]) -> str:
    """First word of a simple command, skipping ``VAR=value`` prefixes."""
    for tok in tokens:
        if "=" in tok and not tok.startswith(("/", ".", "-")) and tok.split("=", 1)[0].isidentifier():
            continue
        return os.path.basename(tok) if tok.startswith("/") else tok
    return ""


def is_read_only(command: str) -> bool:
    """True only when every simple command in ``command`` is known to observe
    and nothing writes (no redirect, substitution, find action, ``sort -o``)."""
    commands = split_commands(command)
    if not commands or "$(" in command or ">" in command or "<" in command:
        return False
    for tokens in commands:
        name = base_name(tokens)
        if name not in READ_ONLY_COMMANDS or tokens[0] != name:
            return False
        args = tokens[1:]
        if name == "find" and any(a in _FIND_WRITES for a in args):
            return False
        if name == "sort" and any(a == "-o" or a.startswith("--output") for a in args):
            return False
        if name == "git" and (not args or args[0] not in READ_ONLY_GIT):
            return False
    return True


def all_read_only(commands) -> bool:
    """``bash_exec`` takes a string or a list of strings."""
    if isinstance(commands, str):
        commands = [commands]
    if not isinstance(commands, list) or not commands:
        return False
    return all(isinstance(c, str) and is_read_only(c) for c in commands)


def is_no_match(command: str, returncode: int) -> bool:
    """grep/rg/diff exit 1 means "nothing found" / "differs", not an error."""
    parts = split_commands(command)
    if not parts:
        return False
    return returncode == _NO_MATCH_RC.get(base_name(parts[-1]), -1)

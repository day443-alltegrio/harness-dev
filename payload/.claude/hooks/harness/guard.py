#!/usr/bin/env python3
"""PreToolUse guard hook for Claude Code: the agent's action boundaries (QG0).

Reads the hook event from stdin (Claude Code JSON) and answers with JSON:
  deny    - blocked, with a reason the agent sees;
  ask     - a confirmation prompt for the human;
  nothing - the normal permission rules apply.

Rules (each one grew out of a real failure; project patterns live in the "guard"
section of .claude/harness-hooks.json):
  git-destructive    git stash, reset, checkout, restore, clean, switch: the working
                     tree always holds uncommitted work, these commands lose it;
  git-coauthor       a commit with a Co-Authored-By trailer (commit rule, optional);
  secrets-read       reading secret files: by a command (readers, input redirection,
                     uploads, interpreter one-liners), with Read or with Grep;
  secrets-write      writing a secret file with Edit or Write: people type secrets;
  secret-in-content  Edit or Write text that holds a key or a token;
  git-push           push only after a human confirms;
  outbound           data leaving the perimeter: curl, wget, scp, rsync or ssh to a
                     host not in internal_hosts, publishing tools, gh calls that create
                     content, network code in interpreter one-liners;
  deploy             shipping code to machines;
  boundaries         the agent's own settings, hooks and MCP servers changed by Edit,
                     Write or a shell command (Claude Code protects .claude/ for its
                     own tools only);
  kit-files          edits of kit-owned files: a change goes to harness-dev;
  obfuscated         code decoded or downloaded and run at once (base64 | sh, eval of
                     a decoded string, curl | sh);
  reviewer-readonly  a reviewer subagent (agent_type in reviewers) only reads;
  repeat-budget      the same command for the N-th time in a row: the agent is looping
                     on one fix and should stop and ask.

A script the agent wrote or changed (untracked or modified in git) is read before it
runs and checked with the same rules, line by line for shell, by its code for Python,
Node, Perl and Ruby; committed scripts were reviewed. A script may load secrets (source
or EnvironmentFile) but not print them.

A failure of the hook itself blocks the action: settings.json ends the command with
`|| exit 2`. Decision log (time, tool, agent, rule, decision, id; never the command
text): .claude/hooks/harness/log/<date>.jsonl, outside git. The id is also in the
reason, so a human can mark a false block (harness/core/scripts/hook_review.py).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
# Tests point this at a temporary folder so they never write the real log.
HOOKS = Path(os.environ.get("HARNESS_HOOKS_DIR") or HERE)
CONFIG = Path(os.environ.get("HARNESS_HOOKS_CONFIG") or ROOT / ".claude" / "harness-hooks.json")

DEFAULTS: dict = {
    "rules": {"git-destructive": True, "git-coauthor": True, "secrets-read": True,
              "secrets-write": True, "secret-in-content": True, "git-push": True,
              "outbound": True, "deploy": True, "boundaries": True, "kit-files": True,
              "obfuscated": True, "reviewer-readonly": True, "repeat-budget": True},
    # Folders (with a trailing slash) and file names that hold secrets; the last three
    # are the machine's own credentials (keys, cloud tokens).
    "secret_dirs": ["secrets/", ".secrets/", ".ssh/", ".aws/", ".gnupg/"],
    "secret_files": [r"[\w.-]*\.env", r"secrets\.env"],
    # Commands that ship code to machines: asked, never blocked.
    "deploy": [r"(^|[\s/])deploy/[\w.-]*(sync|deploy|release)[\w.-]*\.sh\b",
               r"harness/core/scripts/deploy\.sh\b",
               r"(^|[;&|(]\s*|\s)kubectl\s+(apply|delete|replace|rollout|scale|set)\b",
               r"(^|[;&|(]\s*|\s)helm\s+(install|upgrade|uninstall|rollback)\b",
               r"(^|[;&|(]\s*|\s)terraform\s+(apply|destroy|import)\b",
               r"(^|[;&|(]\s*|\s)ansible-playbook\b",
               r"(^|[;&|(]\s*|\s)docker\s+push\b"],
    # Hosts inside the perimeter (regex per host); everything else is outbound.
    "internal_hosts": [r"127\.0\.0\.1", r"localhost", r"0\.0\.0\.0", r"\[::1\]"],
    # Publishing commands: content leaves the perimeter even without curl.
    "publish": [
        r"(^|[;&|(]\s*|\s)gh\s+(?:pr|issue|release|gist|repo)\s+(?:create|edit|comment|close|merge|delete)",
        r"(^|[;&|(]\s*|\s)gh\s+api\b[^;&|]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)"
        r"|--method\s+(?:POST|PUT|PATCH|DELETE)|-f\s|--field)",
    ],
    # The agent's own boundaries, as repo paths (regex): changes ask.
    "boundary_paths": [r"^\.claude/settings(\.local)?\.json$", r"^\.claude/harness-hooks\.json$",
                       r"^\.claude/hooks/", r"^\.mcp\.json$"],
    # Kit-owned paths (harness-dev): a project never edits them; changes ask.
    "kit_paths": [r"^harness/core/", r"^\.claude/skills/harness-[^/]+/",
                  r"^\.claude/agents/harness-[^/]+\.md$"],
    # Commands that rewrite the agent's settings or hooks through a program: changes ask.
    "boundary_commands": [r"harness/core/scripts/sandbox_config\.py\b[^;&|]*--apply",
                          r"\bharness\.py\s+(?:install|upgrade)\b"],
    # Subagents that only read (agent_type of the hook event) and what they may run.
    "reviewers": ["harness-change-reviewer", "harness-docs-reviewer"],
    "reviewer_bash": [
        r"^git\s+(-C\s+\S+\s+)?(diff|show|log|status|blame|rev-parse|ls-files|merge-base|cat-file)\b",
        r"^python3\s+harness/core/scripts/(preflight|contract_check|gates|commit_scan)\.py\b",
        r"^python3\s+harness/core/scripts/doc_coverage\.py\b(?!.*--accept)",
        r"^(ls|cat|head|tail|wc|grep|rg|diff|stat|file|pwd|echo)\b",
        r"^sed\s+-n\b",
    ],
    # Scripts the agent wrote or changed are read up to this size before they run.
    "script_max_bytes": 262144,
    "repeat_limit": 4,
    "messages": {
        "git-destructive": "git stash/reset/checkout/restore/clean/switch are forbidden: the tree "
                           "holds uncommitted work. Compare with git show HEAD:path or git diff; "
                           "for a clean copy use a separate directory.",
        "git-coauthor": "Commit without Co-Authored-By or session trailers (project commit rule).",
        "secrets-read": "Secrets are never read or printed: scripts load them from the file "
                        "themselves.",
        "secrets-write": "Secret files are written by people, by hand, never by the agent. "
                         "A human confirms.",
        "secret-in-content": "The text looks like a key or a token: secrets never go into files "
                             "the agent writes. A human confirms.",
        "git-push": "Push only when the user says \"push\".",
        "outbound": "Upload outside the perimeter: the data must hold no personal data, internal "
                    "IDs or secrets (scanner: harness/core/scripts/commit_scan.py). A human confirms.",
        "deploy": "Deploying code only after the user's \"yes\" for this deploy.",
        "boundaries": "This changes the agent's own boundaries (settings, hooks, MCP servers). "
                      "A human confirms; a change of boundaries needs a task contract.",
        "kit-files": "Kit-owned file from harness-dev: a project does not edit it, the change goes "
                     "to the kit and comes back with an upgrade. A human confirms.",
        "obfuscated": "Decoded or downloaded code is about to run (base64, eval, curl | sh): "
                      "a human confirms.",
        "reviewer-readonly": "A reviewer subagent only reads: git diff, show, log, files and the "
                             "harness checks.",
        "repeat-budget": "The same command ran {n} times in a row. After the third failed attempt "
                         "at the same fix, stop and ask the human.",
    },
}

GIT_DESTRUCTIVE = re.compile(
    r"(^|[;&|(]|\bsudo|\benv)\s*git\s+(-C\s+\S+\s+)?"
    r"(stash(?!\s+(list|show)\b)|reset|checkout|restore|clean|switch)\b")
GIT_COMMIT = re.compile(r"(^|[;&|(])\s*git\s+(-C\s+\S+\s+)?commit\b")
COAUTHOR = re.compile(r"co-authored-by\s*:", re.I)
GIT_PUSH = re.compile(r"(^|[;&|(])\s*git\s+(-C\s+\S+\s+)?push\b")
# Commands that print or copy what they read. "source" and "." load a file into the
# shell: allowed in a script, not in the agent's own shell.
PRINTERS = ("cat|less|more|head|tail|grep|egrep|fgrep|rg|ag|sed|awk|gawk|strings|xxd|od|hexdump|"
            "base64|cp|scp|nl|bat|open|sort|uniq|cut|tr|wc|diff|cmp|comm|paste|tac|rev|jq|yq|"
            "dd|openssl|gpg|tar|zip|gzip|zstd|bzip2|xz|vi|vim|nano|emacs|code|iconv|column|"
            "fold|xargs|mv|ln|rsync|install|cpio|find|"
            "git\\s+(?:-C\\s+\\S+\\s+)?(?:show|cat-file|grep|log|diff|blame|archive)")
LOADERS = r"source|\."
URL_HOST = re.compile(r"https?://([^/\s:'\"]+)")
NET_TOOL = re.compile(r"(^|[;&|(]\s*|\s)(curl|wget)\b")
COPY_TOOL = re.compile(r"(^|[;&|(]\s*|\s)(scp|rsync)\b[^;&|]*?\s(?:[\w.-]+@)?([\w.-]+):")
# Network code in interpreter one-liners and scripts: Python, Node, Perl, Ruby, PHP.
NETWORK_CODE = re.compile(
    r"\b(?:urllib|requests|httpx|aiohttp|http\.client|socket|paramiko|fabric|smtplib|ftplib|"
    r"telnetlib|pysftp|axios|XMLHttpRequest|LWP|IO::Socket|curl_init|fsockopen)\b"
    r"|\bfetch\s*\(|\bhttps?\.(?:request|get)\s*\(|\bnet\.connect\b|HTTP::Tiny"
    r"|Net::(?:HTTP|SSH|FTP|SMTP)|\bopen-uri\b")
INTERPRETER = re.compile(r"^(python3?(\.\d+)?|node|nodejs|perl|ruby|php)$")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "source", "."}
CODE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".pl", ".rb", ".php")
OBFUSCATED = [
    re.compile(r"\bbase64\s+(?:-\w*[dD]\w*|--decode)\b[^;&]*\|\s*(?:sudo\s+)?(?:[\w./]*/)?"
               r"(?:sh|bash|zsh|dash|ksh|python3?|perl|ruby|node|php)\b"),
    re.compile(r"\b(?:xxd\s+-r|openssl\s+(?:enc|base64)\b[^|]*\s-d)\b[^;&]*\|\s*(?:sudo\s+)?"
               r"(?:sh|bash|zsh|dash|python3?|perl|ruby|node)\b"),
    re.compile(r"\beval\b[^;&]*\$\([^)]*\b(?:base64|xxd|openssl|rev)\b"),
    re.compile(r"\b(?:curl|wget)\b[^;&]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|dash|python3?|perl|ruby|node)\b"),
    re.compile(r"\b(?:exec|eval)\s*\(\s*(?:__import__\(\s*['\"]base64|base64\.|codecs\.decode|"
               r"bytes\.fromhex|zlib\.decompress|atob\s*\(|Buffer\.from)"),
    re.compile(r"\b(?:sh|bash|zsh)\s+-c\s+[\"']?\$\([^)]*\b(?:base64|xxd)\b"),
]
SECRET_CONTENT = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bATATT[A-Za-z0-9_\-=]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}"),
]
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
WRAPPERS = {"sudo", "env", "nohup", "time", "nice", "ionice", "timeout", "exec", "command",
            "builtin", "stdbuf", "doas"}
WRAPPER_VALUE_OPTS = {"-u", "-g", "-n", "-c", "-p", "-C", "-k", "-s"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
WRITERS_ALL = {"tee", "rm", "rmdir", "truncate", "chmod", "chown", "touch", "unlink", "shred"}
WRITERS_LAST = {"cp", "mv", "install", "ln", "rsync"}
SSH_VALUE_OPTS = set("bcDEeFIiJLlmOopQRSWw")
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


# ---------------------------------------------------------------------------
# Reading a shell command
# ---------------------------------------------------------------------------

def split_lines(command: str) -> tuple[list[str], list[str]]:
    """Command lines and heredoc bodies. A newline inside quotes stays in its line, a
    backslash-newline joins lines; heredoc bodies are data, not commands."""
    lines: list[str] = []
    bodies: list[str] = []
    buf: list[str] = []
    quote = None
    rows = command.replace("\\\n", " ").split("\n")
    i = 0
    while i < len(rows):
        row = rows[i]
        i += 1
        for ch in row:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
        buf.append(row)
        if quote:
            continue  # the newline is inside quotes: the line goes on
        line = "\n".join(buf)
        buf = []
        lines.append(line)
        for _, delim in HEREDOC.findall(line):
            body = []
            while i < len(rows) and rows[i].strip() != delim:
                body.append(rows[i])
                i += 1
            i += 1
            bodies.append("\n".join(body))
    if buf:
        lines.append("\n".join(buf))
    return lines, bodies


def tokens(line: str) -> list[str]:
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:
        return line.split()


def segments_of_line(line: str) -> list[list[str]]:
    out: list[list[str]] = []
    cur: list[str] = []
    for tok in tokens(line):
        if tok in SEPARATORS:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        out.append(cur)
    return out


def segments(command: str) -> list[list[str]]:
    """Simple commands as token lists, operators removed, heredoc bodies left out."""
    return [seg for line in split_lines(command)[0] for seg in segments_of_line(line)]


def command_of(seg: list[str]) -> tuple[str, list[str]]:
    """The program and its arguments, past variable assignments and wrappers."""
    i = 0
    while i < len(seg):
        tok = seg[i]
        name = tok.rsplit("/", 1)[-1]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
        elif name in WRAPPERS:
            i += 1
            # Wrapper options and values: sudo -u user, timeout 10, nice -n 5, env -i.
            while i < len(seg) and (seg[i].startswith("-") or re.match(r"^\d+[smhd]?$", seg[i])
                                    or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i])):
                if seg[i] in WRAPPER_VALUE_OPTS and i + 1 < len(seg):
                    i += 1
                i += 1
        else:
            return name, seg[i + 1:]
    return "", []


def write_targets(seg: list[str]) -> list[str]:
    """Paths a simple command writes: redirections, tee, cp/mv targets, sed -i files."""
    out = [seg[i + 1] for i, tok in enumerate(seg[:-1]) if tok in REDIRECTS]
    plain = [t for i, t in enumerate(seg) if t not in REDIRECTS and not (i and seg[i - 1] in REDIRECTS)]
    cmd, args = command_of(plain)
    files = [a for a in args if not a.startswith("-")]
    if cmd in WRITERS_ALL:
        out += files
    elif cmd in WRITERS_LAST and files:
        out.append(files[-1])
    elif cmd == "sed" and any(a.startswith("-i") for a in args):
        out += files[1:]
    elif cmd == "perl" and any(re.match(r"^-\w*i", a) for a in args):
        out += files[1:]
    return out


def ssh_host(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            if len(a) == 2 and a[1] in SSH_VALUE_OPTS:
                i += 1
            i += 1
            continue
        host = a.split("://", 1)[-1].rsplit("@", 1)[-1]
        return host.split(":", 1)[0] or None
    return None


def script_target(cmd: str, args: list[str]) -> str | None:
    """The script file a command runs, if any (sh x.sh, python3 x.py)."""
    if cmd in SHELLS:
        if "-c" in args:
            return None
    elif INTERPRETER.match(cmd):
        if any(a in ("-c", "-e", "-E", "-r", "-m", "-") for a in args):
            return None
    else:
        return None
    files = [a for a in args if not a.startswith("-")]
    return files[0] if files else None


def interpreter_code(command: str) -> list[str]:
    """Code given inline to an interpreter: -c and -e arguments, heredoc bodies."""
    lines, bodies = split_lines(command)
    code: list[str] = []
    heredoc = False
    for line in lines:
        for seg in segments_of_line(line):
            cmd, args = command_of(seg)
            if not INTERPRETER.match(cmd):
                continue
            code += [args[j + 1] for j, a in enumerate(args[:-1]) if a in ("-c", "-e", "-E", "-r")]
            heredoc = heredoc or "<<" in line
    return code + (bodies if heredoc else [])


def changed_in_git(root: Path, rel: str) -> str | None:
    """"new" (untracked, or git cannot tell), "changed" (modified) or None (committed)."""
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=root,
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return "new"
    if r.returncode != 0:
        return "new"
    line = r.stdout.strip()
    if not line:
        return None
    return "new" if line.startswith(("??", "A")) else "changed"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

class Rules:
    """Compiled project rules (the "guard" section of harness-hooks.json over DEFAULTS)."""

    def __init__(self, conf: dict, root: Path | None = None):
        def get(key: str):
            return conf.get(key, DEFAULTS[key])

        # Real paths on both sides: a cwd through a symlink (/var and /private/var on
        # macOS, a linked home folder) still names the same repository file.
        self.root = Path(os.path.realpath(root or ROOT))
        self.on = {**DEFAULTS["rules"], **conf.get("rules", {})}
        self.messages = {**DEFAULTS["messages"], **conf.get("messages", {})}
        files = get("secret_files")
        self.secret_dirs = [d.strip("/") + "/" for d in get("secret_dirs")]
        self.secret_file = re.compile(rf"^(?:{'|'.join(files)})$") if files else None
        # Secret names without what comes before them: a folder or a file name.
        names = [re.escape(d) for d in self.secret_dirs]
        if files:
            names.append(rf"(?:{'|'.join(files)})\b(?!\.example)")
        name = "|".join(names) or r"(?!x)x"
        lead = r"(?:[^|;&]*[\s/'\"=@:])?"  # arguments before the name, ending at a delimiter
        self.secret_print = re.compile(rf"\b(?:{PRINTERS})\s{lead}(?:{name})")
        self.secret_load = re.compile(rf"(?:^|[\s;&|(])(?:{LOADERS})\s{lead}(?:{name})")
        self.secret_redirect = re.compile(rf"(?<![<>])<(?![<(])\s*['\"]?(?:[^\s;&|'\"]*/)?(?:{name})")
        self.secret_upload = re.compile(
            rf"(?:\s@|=@|(?:-T|--upload-file)\s+)['\"]?(?:[^\s;&|'\"]*/)?(?:{name})")
        # A secret folder without its slash ("tar czf b.tgz secrets") counts for commands
        # that copy or pack what they are given, and for find that runs a command on what
        # it finds; for grep the same word is a search pattern.
        folders = "|".join(re.escape(d.rstrip("/")) for d in self.secret_dirs) or r"(?!x)x"
        self.secret_copy = re.compile(
            rf"\b(?:cp|mv|ln|rsync|tar|zip|scp|install|cpio|pax)\s{lead}(?:{folders})(?=[\s;&|)]|$)")
        self.secret_find = re.compile(
            rf"\bfind\s(?:[^|;&]*\s)?['\"]?(?:\./)?(?:{folders})/?['\"]?(?=\s)[^;&]*"
            rf"(?:-exec|-execdir|-ok|-okdir|-fprint|-fls|\|\s*xargs)")
        # In code a secret file is a string or a path ('.env', "secrets/key"), never an
        # attribute like process.env.
        self.secret_in_code = re.compile(rf"['\"/`](?:{name})")
        self.deploy = [re.compile(p) for p in get("deploy")]
        self.internal = re.compile(rf"^(?:{'|'.join(get('internal_hosts'))})$")
        self.publish = [re.compile(p) for p in get("publish")]
        self.boundary = [re.compile(p) for p in get("boundary_paths")]
        self.boundary_cmd = [re.compile(p) for p in get("boundary_commands")]
        self.kit = [re.compile(p) for p in get("kit_paths")]
        self.reviewers = set(get("reviewers"))
        self.reviewer_bash = [re.compile(p) for p in get("reviewer_bash")]
        self.script_max = int(get("script_max_bytes"))
        self.repeat_limit = int(get("repeat_limit"))

    def verdict(self, rule: str, decision: str, **fmt) -> tuple[str, str, str]:
        msg = self.messages[rule]
        return decision, rule, msg.format(**fmt) if fmt else msg

    # -- paths ---------------------------------------------------------------

    def rel(self, path: str, cwd: str | None = None) -> str:
        """The repo path of a file inside the repository, else the normalized path."""
        p = Path(os.path.expanduser(path.replace("\\", "/")))
        if not p.is_absolute():
            p = Path(cwd or self.root) / p
        p = Path(os.path.realpath(p))
        try:
            return p.relative_to(self.root).as_posix()
        except ValueError:
            return p.as_posix()

    def is_secret_path(self, path: str) -> bool:
        p = path.replace("\\", "/")
        in_dir = any(f"/{d}" in p or p.startswith(d) for d in self.secret_dirs)
        name = p.rsplit("/", 1)[-1]
        return in_dir or bool(self.secret_file and self.secret_file.match(name)
                              and not name.endswith(".example"))

    def protected(self, path: str, cwd: str | None = None) -> str | None:
        """"boundaries" or "kit-files" for a path the agent would change, else None."""
        rel = self.rel(path, cwd)
        if self.on["boundaries"] and any(rx.search(rel) for rx in self.boundary):
            return "boundaries"
        if self.on["kit-files"] and any(rx.search(rel) for rx in self.kit):
            return "kit-files"
        return None

    def glob_targets_secrets(self, glob: str) -> bool:
        if not glob:
            return False
        probes = [".env", "prod.env", "secrets.env"] + [f"{d}x" for d in self.secret_dirs]
        pats = [g.strip() for g in re.split(r"[{},]", glob) if g.strip()]
        return any(d in glob for d in self.secret_dirs) or any(
            fnmatch.fnmatch(probe, pat) or fnmatch.fnmatch(probe, pat.split("/")[-1])
            for pat in pats for probe in probes)

    # -- network -------------------------------------------------------------

    def outbound(self, code: str, command: str | None = None) -> bool:
        """Does the command send data outside the perimeter. code is the command
        without heredoc bodies; command, when given, is the full text."""
        command = command if command is not None else code
        if any(p.search(code) for p in self.publish):
            return True
        if NET_TOOL.search(code):
            if any(not self.internal.match(h) for h in URL_HOST.findall(code)):
                return True
        if any(not self.internal.match(m.group(3)) for m in COPY_TOOL.finditer(code)):
            return True
        for seg in segments(command):
            cmd, args = command_of(seg)
            if cmd in ("ssh", "mosh"):
                host = ssh_host(args)
                if host and not self.internal.match(host):
                    return True
        return any(NETWORK_CODE.search(code) for code in interpreter_code(command))

    # -- decisions -----------------------------------------------------------

    def decide_bash(self, command: str, cwd: str | None = None,
                    in_script: bool = False) -> tuple[str, str, str] | None:
        """(decision, rule, reason) or None when the hook stays out."""
        on = self.on
        # Each command line on its own (a newline separates commands too); heredoc
        # bodies are data and stay out, a newline inside quotes stays in its line.
        lines = split_lines(command)[0]
        code = "\n".join(lines)

        def hit(rx: re.Pattern) -> bool:
            return any(rx.search(line) for line in lines)

        if on["git-destructive"] and hit(GIT_DESTRUCTIVE):
            return self.verdict("git-destructive", "deny")
        if on["git-coauthor"] and GIT_COMMIT.search(command) and COAUTHOR.search(command):
            return self.verdict("git-coauthor", "deny")
        if on["secrets-read"]:
            reads, loads, writes = self.secret_uses(command)
            if reads or any(self.secret_in_code.search(c) for c in interpreter_code(command)):
                return self.verdict("secrets-read", "deny")
            if loads:
                # The agent's own shell never loads secrets; a script it wrote may, once a
                # human has seen it.
                return self.verdict("secrets-read", "ask" if in_script else "deny")
            if writes and on["secrets-write"]:
                return self.verdict("secrets-write", "ask")
        if on["obfuscated"] and any(hit(rx) for rx in OBFUSCATED):
            return self.verdict("obfuscated", "ask")
        if on["git-push"] and hit(GIT_PUSH):
            return self.verdict("git-push", "ask")
        if on["outbound"] and self.outbound(code, command):
            return self.verdict("outbound", "ask")
        if on["deploy"] and any(hit(p) for p in self.deploy):
            return self.verdict("deploy", "ask")
        if on["boundaries"] and any(hit(p) for p in self.boundary_cmd):
            return self.verdict("boundaries", "ask")
        for seg in segments(command):
            for target in write_targets(seg):
                rule = self.protected(target, cwd)
                if rule:
                    return self.verdict(rule, "ask")
        return None

    def secret_uses(self, command: str) -> tuple[bool, bool, bool]:
        """(reads, loads, writes) of secret files, one simple command at a time. A copy
        whose only secret is its destination (cp .env.example .env) writes a secret
        file: a person decides, it is not a read."""
        reads = loads = writes = False
        reading = (self.secret_print, self.secret_redirect, self.secret_upload,
                   self.secret_copy, self.secret_find)
        for seg in segments(command):
            cmd, args = command_of(seg)
            files = [a for a in args if not a.startswith("-")]
            if cmd in WRITERS_LAST and len(files) >= 2 and self.is_secret_path(files[-1]) \
                    and not any(self.is_secret_path(f) for f in files[:-1]):
                writes = True
                continue
            text = " ".join(seg)
            reads = reads or any(rx.search(text) for rx in reading)
            loads = loads or bool(self.secret_load.search(text))
        return reads, loads, writes

    def decide_code(self, code: str) -> tuple[str, str, str] | None:
        """A Python, Node, Perl or Ruby script: secrets, network, shell commands in it."""
        on = self.on
        if on["secrets-read"] and self.secret_in_code.search(code):
            # Loading and printing look the same in code: a human looks first.
            return self.verdict("secrets-read", "ask")
        if on["obfuscated"] and any(rx.search(code) for rx in OBFUSCATED):
            return self.verdict("obfuscated", "ask")
        if on["git-destructive"] and re.search(
                r"['\"]git['\"]\s*,\s*['\"](?:stash|reset|checkout|restore|clean|switch)['\"]", code):
            return self.verdict("git-destructive", "deny")
        if on["outbound"] and NETWORK_CODE.search(code):
            return self.verdict("outbound", "ask")
        # Shell commands in string literals: os.system("git push"), execSync("...").
        for double, single in re.findall(r"\"([^\"\n]{4,})\"|'([^'\n]{4,})'", code):
            hit = self.decide_bash(double or single, in_script=True)
            if hit:
                return hit
        return None

    def decide_script(self, command: str, cwd: str | None = None) -> tuple[str, str, str] | None:
        """Scripts this command runs that the agent wrote or changed: their content."""
        base = Path(cwd or self.root)
        for seg in segments(command):
            cmd, args = command_of(seg)
            if cmd in ("cd", "pushd") and args and not args[0].startswith("-"):
                base = Path(os.path.normpath(base / os.path.expanduser(args[0])))
                continue
            target = script_target(cmd, args)
            if target is None and seg and seg[0].startswith(("./", "../")):
                target = seg[0]
            if not target:
                continue
            path = Path(target) if Path(target).is_absolute() else base / target
            rel = self.rel(str(path))
            # Outside the repo, missing, kit-owned (reviewed in harness-dev, hashed in
            # the lock) or committed unchanged: not read.
            state = None if Path(rel).is_absolute() or not path.is_file() \
                or any(rx.search(rel) for rx in self.kit) else changed_in_git(self.root, rel)
            if not state:
                continue
            text = path.read_bytes()[:self.script_max].decode("utf-8", "replace")
            hit = None
            if INTERPRETER.match(cmd) or path.suffix in CODE_SUFFIXES:
                hit = self.decide_code(text)
            else:
                for line in split_lines(text)[0]:
                    hit = self.decide_bash(line, cwd, in_script=True)
                    if hit:
                        break
            # A new script is the agent's own: every rule. An edited file of the project is
            # ordinary work (a service that calls the network): only what is never allowed.
            if hit and (state == "new" or hit[0] == "deny"):
                decision, rule, reason = hit
                how = "wrote" if state == "new" else "changed"
                return decision, rule, f"in {rel}, which the agent {how}: {reason}"
        return None

    def decide_read(self, path: str) -> tuple[str, str, str] | None:
        if self.on["secrets-read"] and self.is_secret_path(path):
            return self.verdict("secrets-read", "deny")
        return None

    def decide_grep(self, args: dict) -> tuple[str, str, str] | None:
        if self.on["secrets-read"] and (self.is_secret_path(args.get("path") or "")
                                        or self.glob_targets_secrets(args.get("glob") or "")):
            return self.verdict("secrets-read", "deny")
        return None

    def decide_edit(self, args: dict, cwd: str | None = None) -> tuple[str, str, str] | None:
        path = args.get("file_path") or args.get("notebook_path") or ""
        if path and self.on["secrets-write"] and self.is_secret_path(path):
            return self.verdict("secrets-write", "ask")
        rule = self.protected(path, cwd) if path else None
        if rule:
            return self.verdict(rule, "ask")
        texts = [args.get("content"), args.get("new_string"), args.get("new_source")]
        texts += [e.get("new_string") for e in args.get("edits") or [] if isinstance(e, dict)]
        if self.on["secret-in-content"] and any(
                rx.search(t) for t in texts if isinstance(t, str) for rx in SECRET_CONTENT):
            return self.verdict("secret-in-content", "ask")
        return None

    def reviewer_allows(self, command: str) -> bool:
        """Every simple command is on the read-only list and nothing is written."""
        segs = segments(command)
        if not segs or any(write_targets(seg) for seg in segs):
            return False
        return all(any(rx.search(" ".join(seg)) for rx in self.reviewer_bash) for seg in segs)

    def is_reviewer(self, agent: str) -> bool:
        return bool(agent) and (agent in self.reviewers or agent.rsplit(":", 1)[-1] in self.reviewers)


def load_rules(path: Path = CONFIG) -> Rules:
    try:
        conf = json.loads(path.read_text(encoding="utf-8")).get("guard", {})
    except FileNotFoundError:
        conf = {}
    return Rules(conf)


def repeat_streak(session: str, command: str, state_dir: Path | None = None) -> int:
    """How many times in a row this session runs the same command (this one included)."""
    state_dir = state_dir or HOOKS / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', session)[:80]}.json"
    digest = hashlib.sha256(command.strip().encode("utf-8")).hexdigest()
    try:
        st = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    streak = st.get("streak", 0) + 1 if st.get("last") == digest else 1
    f.write_text(json.dumps({"last": digest, "streak": streak}), encoding="utf-8")
    return streak


def decision_id(event: dict, rule: str) -> str:
    seed = f"{time.time_ns()}|{event.get('session_id')}|{event.get('tool_use_id')}|{rule}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]


def log(event: dict, decision: str, rule: str, log_dir: Path | None = None,
        did: str | None = None) -> None:
    log_dir = log_dir or HOOKS / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": event.get("tool_name"),
           "agent": event.get("agent_type") or "main", "rule": rule, "decision": decision,
           "session": event.get("session_id"), "id": did}
    with open(log_dir / f"{day}.jsonl", "a", encoding="utf-8") as out:
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")


def handle(event: dict, rules: Rules | None = None) -> dict | None:
    rules = rules or load_rules()
    tool = event.get("tool_name")
    args = event.get("tool_input") or {}
    cwd = event.get("cwd")
    reviewer = rules.on["reviewer-readonly"] and rules.is_reviewer(event.get("agent_type") or "")
    verdict = None
    if tool == "Bash":
        command = args.get("command", "")
        if reviewer and not rules.reviewer_allows(command):
            verdict = rules.verdict("reviewer-readonly", "deny")
        else:
            verdict = rules.decide_bash(command, cwd) or rules.decide_script(command, cwd)
        if (verdict is None and rules.on["repeat-budget"]
                and repeat_streak(event.get("session_id", "none"), command) >= rules.repeat_limit):
            verdict = rules.verdict("repeat-budget", "ask", n=rules.repeat_limit - 1)
    elif tool == "Read":
        verdict = rules.decide_read(args.get("file_path", ""))
    elif tool == "Grep":
        verdict = rules.decide_grep(args)
    elif tool in EDIT_TOOLS:
        verdict = (rules.verdict("reviewer-readonly", "deny") if reviewer
                   else rules.decide_edit(args, cwd))
    if verdict is None:
        return None
    decision, rule, reason = verdict
    did = decision_id(event, rule)
    log(event, decision, rule, did=did)
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": decision,
                                   "permissionDecisionReason": f"[{rule} #{did}] {reason}"}}


def main() -> int:
    out = handle(json.load(sys.stdin))
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

import json
import subprocess
import time
from pathlib import Path

from . import Answer

LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "limit will reset", "too many requests")


def _is_limit(s):
    s = s.lower()
    return any(m in s for m in LIMIT_MARKERS)


# No MCP connectors (Gmail, Drive, ...) and no auto-approval: prompts can carry untrusted email/web text.
LOCKDOWN = ["--strict-mcp-config", "--permission-mode", "default"]


class ClaudeCliProvider:
    def __init__(self, model="sonnet", cwd="~/Claude+Obsidian"):
        self.model, self.cwd = model, str(Path(cwd).expanduser())

    def complete(self, prompt, system=None, timeout=120):
        cmd = ["claude", "-p", prompt, "--model", self.model, "--output-format", "json",
               "--tools", "Read,Grep,Glob", *LOCKDOWN]
        if system:
            cmd += ["--append-system-prompt", system]
        t0 = time.monotonic()

        def done(text, ok, err):
            return Answer(text, "claude_cli", self.model, ok, err, int((time.monotonic() - t0) * 1000))

        try:
            p = subprocess.run(cmd, cwd=self.cwd, capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return done("", False, "timeout")
        except OSError:
            return done("", False, "cli_unavailable")
        out = (p.stdout or "").strip()
        try:
            data = json.loads(out)
            result = str(data.get("result", ""))
            is_err = bool(data.get("is_error"))
        except (ValueError, AttributeError):
            data, result, is_err = None, "", True
        if (is_err or p.returncode != 0) and _is_limit(result + out + (p.stderr or "")):
            return done("", False, "pro_limit")
        if data is None:
            return done("", False, "bad_response")
        if is_err or p.returncode != 0:
            return done("", False, "cli_error")
        return done(result.strip(), True, None)

"""Background skill runs: one at a time, headless `claude -p` (or scripts/run_skill.sh) with cwd = vault."""
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

from bridge.config import ROOT
from bridge.providers.claude_cli import LOCKDOWN

ALLOWED = ("plan-today", "inbox-brief", "morning-intel", "vault-ingest", "vault-lint", "weekly-review")
TIMEOUT = 15 * 60
TOOLS = f"Read,Write,Edit,Glob,Grep,Bash(python3 {ROOT}/scripts/*)"


class Busy(Exception):
    pass


class Jobs:
    def __init__(self, vault, data_dir=None):
        self.vault = Path(vault)
        self.file = Path(data_dir or ROOT / "data") / "jobs.json"
        self.lock = threading.Lock()
        self.jobs = {}
        try:
            self.jobs = json.loads(self.file.read_text())
        except (OSError, ValueError):
            pass
        for j in self.jobs.values():  # a job "running" from a previous process can never finish
            if j.get("state") == "running":
                j.update(state="error", finished=time.time(), error="bridge restarted")

    def _save(self):
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            keep = dict(sorted(self.jobs.items(), key=lambda kv: kv[1]["started"])[-50:])
            self.file.write_text(json.dumps(keep))
        except OSError:
            pass  # state file is a convenience; the in-memory state is authoritative

    def get(self, job_id):
        with self.lock:
            j = self.jobs.get(job_id)
            return dict(j) if j else None

    def start(self, name):
        """Returns job_id. Raises Busy if a job is running, KeyError if the name is not allowed."""
        if name not in ALLOWED:
            raise KeyError(name)
        with self.lock:
            if any(j["state"] == "running" for j in self.jobs.values()):
                raise Busy()
            jid = uuid.uuid4().hex[:12]
            self.jobs[jid] = dict(name=name, state="running", started=time.time(), finished=None,
                                  report_path=None, error=None)
            self._save()
        threading.Thread(target=self._run, args=(jid, name), daemon=True).start()
        return jid

    def _cmd(self, name):
        script = ROOT / "scripts" / "run_skill.sh"
        if script.exists():
            return ["/bin/sh", str(script), name]
        return ["claude", "-p", f"/{name}", "--model", "sonnet", "--tools", "Read,Write,Edit,Glob,Grep,Bash",
                "--allowedTools", TOOLS, *LOCKDOWN]

    def report_path(self, stdout):
        root = self.vault.resolve()
        for line in reversed((stdout or "").strip().splitlines()):
            line = line.strip()
            if line.endswith(".md"):
                try:
                    p = Path(line).expanduser().resolve()
                except OSError:
                    return None
                return str(p) if p.is_relative_to(root) else None
            break  # only the last non-empty line counts
        return None

    def _run(self, jid, name):
        upd = {}
        try:
            p = subprocess.run(self._cmd(name), cwd=str(self.vault), stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=TIMEOUT)
            if p.returncode == 0:
                upd = dict(state="done", report_path=self.report_path(p.stdout))
            else:
                upd = dict(state="error", error=f"exit {p.returncode}")
        except subprocess.TimeoutExpired:
            upd = dict(state="error", error="timeout after 15 min")
        except Exception as exc:  # noqa: BLE001 - never leave a job stuck on "running"
            upd = dict(state="error", error=f"could not start ({type(exc).__name__})")
        with self.lock:
            self.jobs[jid].update(upd, finished=time.time())
            self._save()

"""The one place Keystone finds ~/Ai Workload (AOS_AI_WORKLOAD overrides; imported via sys.path, never modified).
Importing this module puts the repo root (jev_loop.py ...) and src/ (router package) on sys.path."""
import os
import sys
from pathlib import Path

from bridge.config import load_env

AI_WORKLOAD = Path(os.environ.get("AOS_AI_WORKLOAD") or "~/Ai Workload").expanduser()
for _p in (AI_WORKLOAD / "src", AI_WORKLOAD):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def jev_key(env=None):
    """TypeSafe (Jev) key: Keystone .env (or the given env dict) first, then Ai Workload's .env."""
    env = load_env() if env is None else env
    return env.get("TYPESAFE_API_KEY") or load_env(AI_WORKLOAD / ".env").get("TYPESAFE_API_KEY")

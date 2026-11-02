import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path():
    """requests.db location; AOS_DB moves it and, with it, the whole data dir (its parent)."""
    return Path(os.environ["AOS_DB"]) if os.environ.get("AOS_DB") else ROOT / "data" / "requests.db"


def load_config(path=None):
    """config.json; AOS_VAULT (env) overrides `vault_path`."""
    cfg = json.loads((Path(path) if path else ROOT / "config.json").read_text())
    if os.environ.get("AOS_VAULT"):
        cfg["vault_path"] = os.environ["AOS_VAULT"]
    return cfg


def load_env(path=None):
    """Parse KEY=VALUE lines. Returns a dict; never touches os.environ, never logs values."""
    p = Path(path) if path else ROOT / ".env"
    env = {}
    try:
        lines = p.read_text().splitlines()
    except FileNotFoundError:
        return env
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env

"""Jev tier sorter: reuses ~/Ai Workload's JevClient + Rulebook (imported via sys.path, never modified)."""
import os
import shutil
from pathlib import Path

from bridge.awr import jev_key
from bridge.config import ROOT

from router.adapters.typesafe import JevClient, mock_decision  # noqa: E402
from router.rulebook import Rulebook  # noqa: E402

SEED = ROOT / "rulebook.seed.json"


class JevTier:
    def __init__(self, rulebook_path="data/rulebook.json", threshold=0.9):
        self.path = Path(rulebook_path) if Path(rulebook_path).is_absolute() else ROOT / rulebook_path
        self.threshold = threshold
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SEED, self.path)

    def decide(self, text):
        """(choice in T1/T2/T3, p, cost_usd); (None, 0.0, 0.0) means unsure (error, no key, odd answer)."""
        try:
            rb = Rulebook.load(self.path)  # re-read each call so an approved night-school edit applies at once
            key = None if os.environ.get("AOS_OFFLINE") == "1" else jev_key()
            if key:
                d = JevClient(api_key=key).decide(text, rb.render_instructions(), rb.criteria)
            else:
                d = mock_decision(text, rb.criteria)
            if not d.success or d.choice not in rb.criteria:
                return None, 0.0, 0.0
            return d.choice, float(d.top_prob), float(d.cost_usd)
        except Exception:  # noqa: BLE001 - any failure = unsure, cascade takes over
            return None, 0.0, 0.0

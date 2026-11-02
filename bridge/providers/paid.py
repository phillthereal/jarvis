from . import Answer


class PaidProvider:
    def __init__(self, cfg):
        self.enabled = bool(cfg.get("paid_enabled"))

    def complete(self, prompt, system=None, timeout=60):
        err = "not configured" if self.enabled else "paid_disabled"  # v1: no paid backend wired
        return Answer("", "paid", "", False, err, 0)

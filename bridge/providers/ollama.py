import json
import time
import urllib.error
import urllib.request

from . import Answer


class OllamaProvider:
    def __init__(self, model, fallback=None, base="http://127.0.0.1:11434"):
        self.model, self.fallback, self.base = model, fallback, base

    def up(self):
        try:
            with urllib.request.urlopen(self.base + "/api/version", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _call(self, model, prompt, system, timeout, fmt=None):
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = json.dumps({"model": model, "messages": msgs, "stream": False, "think": False,
                           "keep_alive": "5m", **({"format": fmt} if fmt else {})}).encode()
        req = urllib.request.Request(self.base + "/api/chat", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            return str(data["message"]["content"]).strip(), None
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("error", "")
            except Exception:
                detail = ""
            return None, "not_found" if e.code == 404 or "not found" in detail.lower() else f"http_{e.code}"
        except (TimeoutError, OSError) as e:  # URLError and socket.timeout are OSError
            return None, "timeout" if "timed out" in str(e) else "unreachable"
        except (ValueError, KeyError, TypeError):
            return None, "bad_response"

    def complete(self, prompt, system=None, timeout=60, fmt=None):
        """fmt="json" asks Ollama for strict JSON output."""
        t0, model = time.monotonic(), self.model
        text, err = self._call(model, prompt, system, timeout, fmt)
        if err == "not_found" and self.fallback:
            model = self.fallback
            text, err = self._call(model, prompt, system, timeout, fmt)
        ms = int((time.monotonic() - t0) * 1000)
        return Answer(text or "", "ollama", model, err is None, err, ms)

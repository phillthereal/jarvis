import json
import time
import urllib.error
import urllib.request

from . import Answer

# name -> {"remaining": str|None, "ts": epoch}; read by bridge/usage.py
QUOTA = {}
_HEADERS = ("x-ratelimit-remaining-requests", "x-ratelimit-remaining")


def _note_quota(name, headers):
    for h in _HEADERS:
        v = headers.get(h) if headers else None
        if v is not None:
            QUOTA[name] = {"remaining": v, "ts": time.time()}
            return


class FreeCloudProvider:
    def __init__(self, entries, env):
        self.entries, self.env = entries, env

    def complete(self, prompt, system=None, timeout=60):
        t0 = time.monotonic()
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        last, model = "no_key", ""
        for e in self.entries:
            key = self.env.get(e.get("key_env", ""), "")
            if not key:
                continue
            model = e["model"]
            req = urllib.request.Request(
                e["base_url"].rstrip("/") + "/chat/completions",
                json.dumps({"model": model, "messages": msgs}).encode(),
                {"Content-Type": "application/json", "Authorization": "Bearer " + key})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    _note_quota(e["name"], r.headers)
                    text = json.loads(r.read())["choices"][0]["message"]["content"]
                return Answer(str(text).strip(), e["name"], model, True, None, int((time.monotonic() - t0) * 1000))
            except urllib.error.HTTPError as ex:
                _note_quota(e["name"], ex.headers)
                last = f"{e['name']}:http_{ex.code}"  # 429/5xx/4xx: try next entry
            except (ValueError, KeyError, IndexError, TypeError):
                last = f"{e['name']}:bad_response"
            except OSError as ex:
                last = f"{e['name']}:" + ("timeout" if "timed out" in str(ex) else "unreachable")
        return Answer("", "free_cloud", model, False, last, int((time.monotonic() - t0) * 1000))

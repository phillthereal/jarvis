"""Bridge-facing night school API: status + approve. Nothing applies without approve()."""
import shutil
from datetime import datetime, timezone

from night.school import paths, read_json, write_json


def status(cfg):
    p = paths(cfg)
    st = read_json(p["state"], {})
    pending = [dict(id=x["id"], summary=x["summary"]) for x in read_json(p["proposals"], []) if x["status"] == "pending"]
    return dict(last_run=st.get("last_run"), learned=st.get("learned", 0), pending=pending)


def approve(cfg, proposal_id):
    p = paths(cfg)
    props = read_json(p["proposals"], [])
    prop = next((x for x in props if x["id"] == proposal_id), None)
    if prop is None or prop["status"] != "pending":
        return dict(ok=False, message="No pending proposal with that id.")
    now = datetime.now(timezone.utc)
    if prop["kind"] == "rulebook":
        from router.rulebook import Rulebook
        if p["rulebook"].exists():
            if Rulebook.load(p["rulebook"]).content_hash() != prop["payload"]["base_hash"]:
                return dict(ok=False, message="The rulebook changed since this proposal; rerun night school.")
            p["night"].mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p["rulebook"], p["night"] / f"rulebook-{now.strftime('%Y%m%dT%H%M%S')}.json")
        d = prop["payload"]["rulebook"]
        Rulebook(d["version"], d["instructions"], dict(d["criteria"]), list(d.get("notes", []))).save(p["rulebook"])
        msg = "Rulebook updated (previous one backed up in data/night/)."
    elif prop["kind"] == "shortcut":
        shortcuts = read_json(p["shortcuts"], [])
        pl = prop["payload"]
        shortcuts.append(dict(id=prop["id"], pattern=pl["pattern"], lookup=pl["lookup"], added=now.isoformat()))
        write_json(p["shortcuts"], shortcuts)
        msg = "Shortcut saved to data/shortcuts.json."
    else:
        return dict(ok=False, message="Unknown proposal kind.")
    prop["status"], prop["decided"] = "approved", now.isoformat()
    write_json(p["proposals"], props)
    return dict(ok=True, message=msg)

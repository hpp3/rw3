"""When each spell / equipment / component / unit / costume first appeared.

The game's data carries no timestamps (see gameinfo.py — there isn't even a
version string), so "recently added" has to come from us. Two sources, one file:

  * backfill (one-off, re-runnable): replay every committed revision of
    site/data*.json oldest-first and record the commit date at which each name
    first shows up. That gives real history instead of marking the whole
    catalogue "new" on the day this feature shipped.
  * update() (every build): extract.py calls it, so a name that appears in a new
    patch is stamped with that build's date and build id.

Shape (site/history.json) is grouped by date because that is exactly how the
Recent Changes screen renders it, and it keeps the file ~10x smaller than a
name -> date map:

  {"v":1,"branches":{"beta":{
      "builds": {"2026-07-28":"24443072"},        # date -> build id (if known)
      "added":  {"2026-07-28":{"equipment":["Arbiter Cage"],"component":[...]}}}}}

INTENDED INVARIANT, not yet enforced (see ARCHITECTURE.md §18):
Only changes the GAME made belong in Recent changes. What this file actually
records today is "first seen in this dataset", which is not the same thing --
if a parser fix or an extraction change makes new names appear, they are newly
*visible*, not new *content*, and must not surface as a recent change.

`baseline` handles only the coarse case (an entire kind imported at once: the
initial catalogue, or the 72 costumes on the day extraction learned to read the
wardrobe). It does NOT handle a partial extraction change, and one already sits
in the committed history: live 2026-06-09 "221 units" was the extractor widening
its unit sweep, not a patch.

So when you change extraction in a way that shifts which records are emitted,
write the updated data file but KEEP the old first-seen dates for those records:
decide per name whether it is new content or merely newly visible, and let only
real content reach history.json. There is no automation for that judgment --
history.json is sorted, indented, hand-editable JSON precisely so a misfiled
name can be moved back to its true date (or into the branch's baseline).
"""
import os, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = "history.json"

# data file -> branch id. Mirrors gameinfo.data_filename().
TRACKED = {"site/data.json": "live", "site/data.beta.json": "beta"}

# dataset section -> singular kind used in history.json / the frontend
KINDS = [("spells", "spell"), ("equipment", "equipment"),
         ("components", "component"), ("units", "unit"), ("costumes", "costume")]


def names_by_kind(data):
    """{kind: set(names)} for one dataset, tolerating older/newer file shapes."""
    out = {}
    for section, kind in KINDS:
        coll = data.get(section)
        if not coll:
            continue
        names = coll.keys() if isinstance(coll, dict) else [
            i.get("name") for i in coll if isinstance(i, dict)]
        out[kind] = {n for n in names if n}
    return out


def load(site_dir):
    path = os.path.join(site_dir, HISTORY_FILE)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                h = json.load(f)
            if isinstance(h, dict) and isinstance(h.get("branches"), dict):
                return h
        except (OSError, ValueError):
            pass
    return {"v": 1, "branches": {}}


def save(site_dir, hist):
    path = os.path.join(site_dir, HISTORY_FILE)
    for br in hist.get("branches", {}).values():
        br["added"] = {d: {k: sorted(v) for k, v in sorted(kinds.items())}
                       for d, kinds in sorted(br.get("added", {}).items())}
        br["builds"] = dict(sorted(br.get("builds", {}).items()))
        if br.get("baseline"):
            br["baseline"] = dict(sorted(br["baseline"].items()))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def known_names(branch_entry):
    """Every name this branch has ever recorded, as {kind: set(names)}."""
    seen = {}
    for kinds in branch_entry.get("added", {}).values():
        for kind, names in kinds.items():
            seen.setdefault(kind, set()).update(names)
    return seen


def record(hist, branch_id, date, build_id, data):
    """Stamp anything in `data` not seen before on this branch with `date`.
    Returns {kind: [new names]} (empty when nothing is new)."""
    br = hist["branches"].setdefault(branch_id, {"builds": {}, "added": {}})
    if build_id:
        br.setdefault("builds", {})[date] = str(build_id)
    seen = known_names(br)
    fresh = {}
    for kind, names in names_by_kind(data).items():
        new = sorted(names - seen.get(kind, set()))
        if new:
            # The first time a kind is ever recorded it's a bulk import (the
            # initial dataset, or the extractor learning to read costumes), NOT
            # new game content. Flag it so the UI can keep it out of "recent".
            if not seen.get(kind):
                br.setdefault("baseline", {})[kind] = date
            fresh[kind] = new
            bucket = br.setdefault("added", {}).setdefault(date, {})
            bucket[kind] = sorted(set(bucket.get(kind, [])) | set(new))
    return fresh


def update(site_dir, branch_info, data):
    """Called by extract.py after a build. Idempotent: a rebuild of the same
    content adds nothing."""
    hist = load(site_dir)
    fresh = record(hist, branch_info["id"], data.get("generated", ""),
                   branch_info.get("build_id", ""), data)
    save(site_dir, hist)
    return fresh


# ---------------------------------------------------------------------------
# Backfill from git history
# ---------------------------------------------------------------------------
def _git(*args):
    r = subprocess.run(["git", "-C", HERE] + list(args), capture_output=True)
    if r.returncode != 0:
        return ""
    return r.stdout.decode("utf-8", "replace")


def backfill(site_dir):
    """Replay every committed revision of the tracked data files, oldest first.
    Only fills gaps, so running it after update() never rewrites a known date."""
    hist = load(site_dir)
    total = 0
    for path, branch in TRACKED.items():
        log = [l for l in _git("log", "--format=%H\t%cI", "--reverse", "--", path).splitlines() if l.strip()]
        print(f"{path}: {len(log)} revisions")
        for line in log:
            sha, iso = line.split("\t")
            blob = _git("show", f"{sha}:{path}")
            if not blob.strip():
                continue
            try:
                data = json.loads(blob)
            except ValueError:
                print(f"  {sha[:8]} unparseable, skipped")
                continue
            fresh = record(hist, branch, iso[:10], data.get("build_id", ""), data)
            n = sum(len(v) for v in fresh.values())
            total += n
            if n:
                print(f"  {sha[:8]} {iso[:10]}  +{n} " +
                      ", ".join(f"{k}:{len(v)}" for k, v in sorted(fresh.items())))
    # Finally fold in the working-tree files, so uncommitted builds count too.
    for path, branch in TRACKED.items():
        full = os.path.join(HERE, path)
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8") as f:
            data = json.load(f)
        fresh = record(hist, branch, data.get("generated", ""), data.get("build_id", ""), data)
        n = sum(len(v) for v in fresh.values())
        total += n
        if n:
            print(f"  working tree {path} +{n} " +
                  ", ".join(f"{k}:{len(v)}" for k, v in sorted(fresh.items())))
    save(site_dir, hist)
    print(f"wrote {os.path.join(site_dir, HISTORY_FILE)} (+{total} first-seen records)")


def reset(site_dir, branch_id, date=None):
    """Collapse a branch's entire recorded history into a single baseline, so
    Recent changes starts empty and only *future* additions appear.

    Use when the recorded history is dominated by extraction churn rather than
    real patches (see the invariant above) and is not worth untangling entry by
    entry. The names are kept — that's what stops the next build from reporting
    the whole catalogue as new — they're just all filed under one baseline date.
    """
    hist = load(site_dir)
    br = hist["branches"].get(branch_id)
    if not br:
        print(f"no history for branch {branch_id!r}")
        return
    names = {k: v for k, v in known_names(br).items() if v}
    date = date or max(br.get("added", {}), default="") or ""
    before = sum(len(kinds.get(k, [])) for kinds in br.get("added", {}).values() for k in kinds)
    br["added"] = {date: {k: sorted(v) for k, v in names.items()}}
    br["baseline"] = {k: date for k in names}
    save(site_dir, hist)
    print(f"{branch_id}: collapsed {before} first-seen records into a single baseline at {date}; "
          f"kept {sum(len(v) for v in names.values())} names across {len(names)} kinds")


if __name__ == "__main__":
    import sys
    site = os.path.join(HERE, "site")
    if len(sys.argv) > 2 and sys.argv[1] == "reset":
        reset(site, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        backfill(site)

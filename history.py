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

# ---------------------------------------------------------------------------
# Field-level diffs of CHANGED entries (buffs/nerfs/reworks)
# ---------------------------------------------------------------------------
# Derived/plumbing fields: an id shuffle or a new cross-ref is not a balance
# change, so comparing them would report noise on every build.
DERIVED = {"id", "sp_id", "icon", "has_icon", "refs", "btips",
           "mod_stats", "use_stats", "pools", "pool_summons"}

# A single build that rewrites more than this share of a kind is extraction
# churn, not a patch (ARCHITECTURE.md §18) -- record nothing rather than claim
# the game rebalanced everything.
CHURN_LIMIT = 0.30

# Lists of dicts are matched up by name instead of by position, so a reordered
# ability list doesn't read as "everything changed".
def _key_of(item):
    return item.get("name") if isinstance(item, dict) else None


def _fmt(v):
    if v is None:
        return "-"          # field absent on this side (a resist that appeared/vanished)
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float, str)):
        return str(v)
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _diff_value(label, o, n, out, depth=0):
    """Append {f,o,n} records describing how `o` became `n`."""
    if o == n:
        return
    if isinstance(o, dict) and isinstance(n, dict):
        for k in sorted(set(o) | set(n)):
            if k in DERIVED:
                continue
            _diff_value(f"{label}.{k}" if label else k, o.get(k), n.get(k), out, depth + 1)
        return
    if isinstance(o, list) and isinstance(n, list):
        # list of named dicts (upgrades, abilities) -> match by name
        if depth < 2 and (o or n) and all(_key_of(i) for i in o + n):
            om = {_key_of(i): i for i in o}
            nm = {_key_of(i): i for i in n}
            for k in sorted(set(om) - set(nm)):
                out.append({"f": f"{label}: {k}", "o": "present", "n": "removed"})
            for k in sorted(set(nm) - set(om)):
                out.append({"f": f"{label}: {k}", "o": "absent", "n": "added"})
            for k in sorted(set(om) & set(nm)):
                _diff_value(f"{label}: {k}", om[k], nm[k], out, depth + 1)
            return
        # plain list (tags, bonus lines) -> set difference, order ignored
        so, sn = [_fmt(x) for x in o], [_fmt(x) for x in n]
        gone = [x for x in so if x not in sn]
        came = [x for x in sn if x not in so]
        if gone or came:
            out.append({"f": label, "o": "; ".join(gone) or "-", "n": "; ".join(came) or "-"})
        return
    out.append({"f": label, "o": _fmt(o), "n": _fmt(n)})


def diff_entry(old, new):
    out = []
    _diff_value("", old, new, out)
    return out


def entries_by_name(data, section):
    coll = data.get(section)
    if not coll:
        return {}
    if isinstance(coll, dict):
        return dict(coll)
    return {i["name"]: i for i in coll if isinstance(i, dict) and i.get("name")}


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
        if br.get("changed"):
            br["changed"] = {d: {k: dict(sorted(names.items())) for k, names in sorted(kinds.items())}
                             for d, kinds in sorted(br["changed"].items())}
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


def record_changes(hist, branch_id, date, old_data, new_data):
    """Record buffs/nerfs/reworks: entries present in both datasets whose
    game-facing fields differ, with a field-level diff for each.
    Returns {kind: {name: [{f,o,n}]}}."""
    br = hist["branches"].setdefault(branch_id, {"builds": {}, "added": {}})
    result = {}
    for section, kind in KINDS:
        old, new = entries_by_name(old_data, section), entries_by_name(new_data, section)
        shared = set(old) & set(new)
        if not shared:
            continue
        diffs = {}
        for name in shared:
            d = diff_entry(old[name], new[name])
            if d:
                diffs[name] = d
        if not diffs:
            continue
        if len(diffs) > CHURN_LIMIT * len(shared):
            print(f"  ! {kind}: {len(diffs)}/{len(shared)} entries differ -- treating as an "
                  f"extraction change, not a patch; not recorded (see ARCHITECTURE §18)")
            continue
        result[kind] = diffs
        bucket = br.setdefault("changed", {}).setdefault(date, {}).setdefault(kind, {})
        bucket.update(diffs)
    return result


def update(site_dir, branch_info, data, prev_data=None):
    """Called by extract.py after a build. Idempotent: a rebuild of the same
    content adds nothing. `prev_data` is the data file as it was BEFORE this
    build overwrote it, which is what makes the changed-entry diff possible
    without storing a separate snapshot."""
    hist = load(site_dir)
    date = data.get("generated", "")
    fresh = record(hist, branch_info["id"], date, branch_info.get("build_id", ""), data)
    changed = record_changes(hist, branch_info["id"], date, prev_data, data) if prev_data else {}
    save(site_dir, hist)
    return fresh, changed


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


def changes_from_rev(site_dir, branch_id, rev):
    """Record changed-entry diffs by comparing the committed data file at `rev`
    against the working tree's current one. For catching up a build that was
    made before change-tracking existed; both sides must come from the SAME
    extractor, or the diff is extraction noise rather than a patch."""
    path = [p for p, b in TRACKED.items() if b == branch_id]
    if not path:
        print(f"unknown branch {branch_id!r}")
        return
    blob = _git("show", f"{rev}:{path[0]}")
    if not blob.strip():
        print(f"no {path[0]} at {rev}")
        return
    old = json.loads(blob)
    with open(os.path.join(HERE, path[0]), encoding="utf-8") as f:
        new = json.load(f)
    hist = load(site_dir)
    date = new.get("generated", "")
    print(f"{branch_id}: {old.get('build_id')} -> {new.get('build_id')} (recorded under {date})")
    changed = record_changes(hist, branch_id, date, old, new)
    save(site_dir, hist)
    for kind, entries in sorted(changed.items()):
        print(f"  {kind}: {len(entries)} changed -- {', '.join(sorted(entries)[:6])}"
              + (" ..." if len(entries) > 6 else ""))


if __name__ == "__main__":
    import sys
    site = os.path.join(HERE, "site")
    if len(sys.argv) > 2 and sys.argv[1] == "reset":
        reset(site, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif len(sys.argv) > 3 and sys.argv[1] == "changes":
        changes_from_rev(site, sys.argv[2], sys.argv[3])
    else:
        backfill(site)

"""Stable, append-only integer IDs for shareable build URLs.

Maintains `ids.json` (committed) mapping a display name -> small int, per
category ("equipment", "spell"). Assignment is **append-only**:

  * an existing name NEVER changes id,
  * a name that disappears from the game keeps its id reserved (never reused),
  * a new name gets `max(existing) + 1`.

This lets a build be encoded in a URL as a compact list of integers that stays
valid as the game gains content. The display name is the stable key because the
game's own tests enforce that names are unique across all equipment and all
spells, and content *additions* never rename existing entries (a deliberate
rename would orphan the old id — accepted, see ARCHITECTURE.md §3).

`ids.json` is the source of truth and must be committed. The frontend never
fetches it; build emits the resolved `id` onto each entry in `data.json`.

Run directly (`python ids.py`) to (re)assign ids and patch the ids into an
existing `site/data.json` *without* a full game rebuild — handy for bootstrapping
or refreshing after a manual data edit. The full build (`extract.py`) does the
same thing inline on every run.
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
IDS_PATH = os.path.join(HERE, "ids.json")
DATA_PATH = os.path.join(HERE, "site", "data.json")

# data.json key -> ids.json category
CATEGORIES = {"equipment": "equipment", "spells": "spell"}


def load_ids(path=IDS_PATH):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def assign(idmap, category, names):
    """Ensure every name in `names` has an id under `category`; append new ones
    (in sorted order) after the current maximum. Returns the category dict."""
    m = idmap.setdefault(category, {})
    nxt = max(m.values(), default=-1) + 1
    for name in sorted(names):
        if name not in m:
            m[name] = nxt
            nxt += 1
    return m


def sp_key(spell_name, upgrade_name=None):
    """Stable key for the combined spell+upgrade `sp` namespace. A spell is keyed
    by its (game-unique) name; an upgrade by "Spell::Upgrade". The "::" guarantees
    the two key spaces never collide, so spells and upgrades share one compact id
    space (used by the Guide feature's SP track — see ARCHITECTURE.md §15)."""
    return spell_name if upgrade_name is None else f"{spell_name}::{upgrade_name}"


def assign_sp(idmap, spells):
    """Assign + attach combined `sp` ids for every spell AND every upgrade.
    Mutates `spells` (adds `sp_id` to each spell and to each upgrade dict) and
    `idmap`. Append-only like `assign`. Returns the `sp` category dict.
    Forbidden spells (equipment-granted, no SP cost) are skipped — they don't
    belong in the Guide SP track."""
    spells = [s for s in spells if not s.get("forbidden")]
    keys = []
    for s in spells:
        keys.append(sp_key(s["name"]))
        for u in s.get("upgrades", []):
            keys.append(sp_key(s["name"], u["name"]))
    assign(idmap, "sp", keys)
    m = idmap["sp"]
    for s in spells:
        s["sp_id"] = m[sp_key(s["name"])]
        for u in s.get("upgrades", []):
            u["sp_id"] = m[sp_key(s["name"], u["name"])]
    return m


def save_ids(idmap, path=IDS_PATH):
    # Stable on disk: categories alphabetical, entries ordered by id, so diffs
    # only ever show appended lines.
    out = {cat: dict(sorted(m.items(), key=lambda kv: kv[1]))
           for cat, m in sorted(idmap.items())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")


def apply_to_data(data, idmap):
    """Assign+attach ids for every category present in `data` (mutates both)."""
    for data_key, category in CATEGORIES.items():
        entries = data.get(data_key, [])
        if category == "spell":   # forbidden spells get no spell id (see assign_sp)
            entries = [e for e in entries if not e.get("forbidden")]
        assign(idmap, category, [e["name"] for e in entries])
        m = idmap[category]
        for e in entries:
            e["id"] = m[e["name"]]
    # Combined spell+upgrade ids for the Guide SP track (attaches sp_id to each
    # spell and to each upgrade dict in place).
    assign_sp(idmap, data.get("spells", []))
    return idmap


def main():
    idmap = load_ids()
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    apply_to_data(data, idmap)
    save_ids(idmap)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    for cat, m in sorted(idmap.items()):
        print(f"{cat}: {len(m)} ids (max {max(m.values(), default=-1)})")
    print("patched", DATA_PATH)


if __name__ == "__main__":
    main()

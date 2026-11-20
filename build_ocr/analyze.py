"""Stage 4: what winning builds look like.

    python -I analyze.py --builds OUT/builds.jsonl --site ../site --out OUT/analysis.json

Wins only (no losses are posted), so nothing here is a win rate: it is what players who won
took. Three parts:
  1. pick rates: spells and items, normal runs vs all runs, per live-patch era with 95% intervals;
     upgrade take-rates per spell (from builds where that spell has <= 2 upgrades, i.e. chosen),
     plus how often each spell is pushed to 3+ (Evolution / Perfection / Codex of Chaotic Evolution)
  2. carries: the final realm's "Damage to Enemies" list (top 5 + Other) credited to the spell or
     item in that build that dealt it (minions -> their summoner, staff spells -> the staff)
  3. archetypes: builds grouped by their main damage source; core = over-represented in the group
     (lift), utility = common everywhere; each gets a compendium guide link
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from rapidfuzz import fuzz, process

ERAS = [  # live builds in the compendium's history.json; a post belongs to the patch live when posted
    ("Jul 6", dt.date(2026, 7, 6)), ("Jul 19", dt.date(2026, 7, 19)),
    ("Sep 1", dt.date(2026, 9, 1)), ("Oct 12", dt.date(2026, 10, 12)),
]
STATUSES = {"bleed", "poison", "burn", "acid", "fire", "ice", "lightning", "physical", "dark", "holy", "arcane",
            "freeze", "frozen", "petrify", "stun", "doom", "blood", "curse", "rot", "necrosis"}
CARRY_SHARE = 0.35       # top source must hold this share of the listed damage to label an archetype
MIN_GROUP = 15
MIN_SPELL_N = 20


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower().replace("’", "'"))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def era_of(ms: int) -> str:
    d = dt.datetime.fromtimestamp(ms / 1000, dt.UTC).date()
    name = ERAS[0][0]
    for n, start in ERAS:
        if d >= start:
            name = n
    return name


def load_site(site: Path):
    data = json.loads((site / "data.json").read_text(encoding="utf-8"))
    ids = json.loads((site.parent / "ids.json").read_text(encoding="utf-8"))
    hist = json.loads((site / "history.json").read_text(encoding="utf-8"))
    # earliest appearance in either branch (live's own list misses things that came via beta)
    added = {}
    for branch in hist["branches"].values():
        for date, kinds in branch["added"].items():
            for k in ("spell", "equipment"):
                for name in kinds.get(k, []):
                    d = dt.date.fromisoformat(date)
                    added[name] = min(added.get(name, d), d)
    return data, ids, added


class Attributor:
    """Credit a damage-source name to something in the build."""

    # buffs whose damage carries the buff's name, -> spells/granted spells that apply them
    BUFF_SOURCES = {"sharedpain": ["Soul Wind", "Voodoo Binding"]}

    def __init__(self, data: dict, game: Path):
        self.summoned_by = defaultdict(set)   # unit name -> spell/item names that summon it
        self.casts_via = defaultdict(set)     # spell name -> items that cast it (free-cast staves)
        # what each spell/item summons, and what those minions can do: ability names (a summoned
        # wizard's Fireball) and second-hand summons (a Dragon Mage's "Summon Drakes")
        self.summons_of = defaultdict(set)
        for s in data["spells"]:
            self.summons_of[s["name"]] |= {norm(u) for u in (s.get("summons") or []) + (s.get("pool_summons") or [])}
        for e in data["equipment"]:
            self.summons_of[e["name"]] |= {norm(u) for u in (e.get("summons") or []) + (e.get("pool_summons") or [])}
        units = {norm(k): v for k, v in data.get("units", {}).items()}
        self.unit_abilities = {k: {norm(a["name"]) for a in v.get("abilities", [])} for k, v in units.items()}
        self.unit_summons_drakes = {k for k, v in units.items()
                                    if any("drake" in (a.get("desc") or "").lower() and "summon" in (a.get("desc") or "").lower()
                                           for a in v.get("abilities", []))}
        self.upgrade_owner = defaultdict(set)
        for s in data["spells"]:
            for u in s.get("upgrades") or []:
                self.upgrade_owner[norm(u["name"])].add(s["name"])
        # "Damage to Enemies" also counts enemies hurting each other: Mordred's Life Vortex,
        # Devastating Gaze, Annihilation Beam... Boss names are enemy damage, excluded from totals.
        pat = re.compile(r'(?:self\.name|unit\.name|\bname)\s*=\s*"([^"%{}]+)"')
        self.enemy = {norm(n) for n in pat.findall((game / "FinalBosses.py").read_text(encoding="utf-8"))}
        self.monster = set()
        for f in ("Monsters.py", "RareMonsters.py"):
            self.monster |= {norm(n) for n in pat.findall((game / f).read_text(encoding="utf-8"))}
        for s in data["spells"]:
            for u in (s.get("summons") or []) + (s.get("pool_summons") or []):
                self.summoned_by[norm(u)].add(s["name"])
        for e in data["equipment"]:
            for u in (e.get("summons") or []) + (e.get("pool_summons") or []):
                self.summoned_by[norm(u)].add(e["name"])
            for ref, kind in e.get("refs") or []:
                if kind == "spell":
                    self.casts_via[norm(ref)].add(e["name"])

    def owner(self, source: str, build_spells: set[str], build_items: set[str]) -> tuple[str, str]:
        k = norm(source)
        if not k or k == "other":
            return ("other", "Other")
        for pool, kind in ((build_spells, "spell"), (build_items, "item")):
            if pool:
                m = process.extractOne(k, {n: norm(n) for n in pool}, scorer=fuzz.ratio)
                if m and m[1] >= 88:
                    return (kind, m[2])
                # long names are cut off in the pane ("Staff of Heaven's...")
                pre = [n for n in pool if len(k) >= 8 and norm(n).startswith(k)]
                if len(pre) == 1:
                    return (kind, pre[0])
        for who in self.summoned_by.get(k, ()):
            if who in build_spells:
                return ("spell", who)
            if who in build_items:
                return ("item", who)
        for who in self.casts_via.get(k, ()):
            if who in build_items:
                return ("item", who)
        for who in sorted(build_spells) + sorted(build_items):
            minions = self.summons_of.get(who, ())
            if any(k in self.unit_abilities.get(m, ()) for m in minions):
                return ("spell" if who in build_spells else "item", who)
            if k.endswith("drake") and any(m in self.unit_summons_drakes for m in minions):
                return ("spell" if who in build_spells else "item", who)
        for who in self.upgrade_owner.get(k, ()):
            if who in build_spells:
                return ("spell", who)
        for who in self.BUFF_SOURCES.get(k, ()):
            if who in build_spells:
                return ("spell", who)
            for item in self.casts_via.get(norm(who), ()):
                if item in build_items:
                    return ("item", item)
        if k in STATUSES:
            return ("status", source)
        if k in self.enemy:
            return ("enemy", source)
        if k in self.monster:
            return ("monster", source)
        return ("unattributed", source)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", type=Path, required=True)
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--game", type=Path, default=Path("E:/SteamLibrary/steamapps/common/Rift Wizard 3"))
    args = ap.parse_args()
    data, ids, added = load_site(args.site)
    spell_info = {s["name"]: s for s in data["spells"]}
    granted_by = {s["name"]: s["granted_by"] for s in data["spells"] if s.get("granted_by")}
    grants = {v: k for k, v in granted_by.items()}
    builds = [json.loads(l) for l in args.builds.read_text(encoding="utf-8").splitlines()]
    for b in builds:
        b["era"] = era_of(b["posted"])
        b["normal"] = not b.get("challenge")
        b["S"] = {s["name"] for s in b["spells"] if not s.get("unknown")}
        b["I"] = [e["name"] for e in b["equipment"] if e["known"]]
        b["Iset"] = set(b["I"])
    out: dict = {"generated": dt.date.today().isoformat(), "n_builds": len(builds)}

    # ---------------------------------------------------------------- dataset
    era_names = [e for e, _ in ERAS]
    out["dataset"] = {
        "by_era": {e: {"all": sum(b["era"] == e for b in builds), "normal": sum(b["era"] == e and b["normal"] for b in builds)} for e in era_names},
        "normal": sum(b["normal"] for b in builds),
        "challenges": Counter(("weekly" if (b["challenge"] or "").startswith("weekly") else b["challenge"]) for b in builds if b["challenge"]).most_common(),
        "with_damage": sum(1 for b in builds if b["damage_to_enemies"]),
        "first_post": dt.datetime.fromtimestamp(min(b["posted"] for b in builds) / 1000, dt.UTC).date().isoformat(),
        "last_post": dt.datetime.fromtimestamp(max(b["posted"] for b in builds) / 1000, dt.UTC).date().isoformat(),
        "assumed_victory": sum(1 for b in builds if b.get("assumed_victory")),
    }

    # ---------------------------------------------------------------- 1. pick rates
    current = {s["name"] for s in data["spells"]} | {e["name"] for e in data["equipment"]}
    vocab = json.loads((Path(__file__).with_name("vocab.json")).read_text(encoding="utf-8"))
    current |= {n for n, t in vocab["equipment"].items() if t in ("tome", "companion", "source")}

    def pick_table(key: str) -> list[dict]:
        names = Counter(n for b in builds for n in b[key])
        rows = []
        for name, _ in names.most_common():
            row = {"name": name}
            for label, pool in (("normal", [b for b in builds if b["normal"]]), ("all", builds)):
                k = sum(1 for b in pool if name in b[key])
                row[label] = [k, len(pool)]
            first = added.get(name)
            eras = {}
            for e, start in ERAS:
                pool = [b for b in builds if b["normal"] and b["era"] == e]
                if first and first > start:
                    eras[e] = None  # not in the game for the whole era
                    continue
                k = sum(1 for b in pool if name in b[key])
                lo, hi = wilson(k, len(pool))
                eras[e] = [k, len(pool), round(lo, 4), round(hi, 4)]
            row["eras"] = eras
            valid = [v for v in eras.values() if v]
            # trends only for things in the current game with enough picks: removed or renamed
            # names (Banner of the Horde, Orb of Explosions) would fake a fall or a rise
            if len(valid) >= 2 and name in current and row["normal"][0] >= 15:
                a, z = valid[0], valid[-1]
                row["trend"] = "up" if z[2] > a[3] else "down" if z[3] < a[2] else None
            if key == "S":
                row["level"] = spell_info.get(name, {}).get("level")
                row["granted_by"] = granted_by.get(name)
            rows.append(row)
        return rows

    out["spells"] = pick_table("S")
    out["items"] = pick_table("Iset")

    # upgrades: chosen (spell has <= 2) vs pushed (3+); skip Wild Magic, incomplete, left-panel fills
    upg = defaultdict(lambda: {"n": 0, "none": 0, "chosen_n": 0, "pushed": 0, "counts": Counter(), "all_counts": Counter()})
    for b in builds:
        if b["challenge"] == "Wild Magic" or b.get("incomplete"):
            continue
        for s in b["spells"]:
            if s.get("unknown") or s.get("from_left_panel"):
                continue
            u = upg[s["name"]]
            ups = [x for x in s["upgrades"] if x not in (s.get("unknown_upgrades") or [])]
            u["n"] += 1
            u["none"] += not ups
            u["all_counts"].update(ups)
            if len(s["upgrades"]) >= 3:
                u["pushed"] += 1
            else:
                u["chosen_n"] += 1
                u["counts"].update(ups)
    out["upgrades"] = []
    for name, u in sorted(upg.items(), key=lambda kv: -kv[1]["n"]):
        if u["n"] < MIN_SPELL_N:
            continue
        known = [x["name"] for x in spell_info.get(name, {}).get("upgrades", [])]
        out["upgrades"].append({
            "spell": name, "n": u["n"], "chosen_n": u["chosen_n"], "pushed": u["pushed"],
            "none": u["none"],
            "take": [[x, u["counts"][x]] for x in sorted(known, key=lambda x: -u["counts"][x])],
            "take_all": [[x, u["all_counts"][x]] for x in sorted(known, key=lambda x: -u["all_counts"][x])],
        })

    # ---------------------------------------------------------------- 2. carries
    att = Attributor(data, args.game)
    carry = defaultdict(lambda: {"present": 0, "top": 0, "shares": []})
    unattributed = Counter()
    totals = Counter()
    for b in builds:
        dmg = b["damage_to_enemies"]
        if not dmg:
            b["carry"] = None
            continue
        owners = [(v or 0, src, *att.owner(src, b["S"], b["Iset"])) for v, src in dmg]
        total = sum(v for v, _, kind, _ in owners if kind != "enemy") or 1
        by_owner = Counter()
        for v, src, kind, who in owners:
            totals[kind] += v
            if kind in ("unattributed", "monster"):
                unattributed[f"{src} ({kind})"] += 1
            if kind in ("spell", "item"):
                by_owner[(kind, who)] += v
        for key in {("spell", s) for s in b["S"]} | {("item", i) for i in b["Iset"]}:
            c = carry[key]
            c["present"] += 1
            c["shares"].append(by_owner.get(key, 0) / total)
        if by_owner:
            (kind, who), v = by_owner.most_common(1)[0]
            carry[(kind, who)]["top"] += 1
            share = v / total
            b["carry"] = {"kind": kind, "name": who, "share": round(share, 3)}
        else:
            b["carry"] = None
    out["carry_coverage"] = {k: round(v / max(1, sum(totals.values())), 4) for k, v in totals.items()}
    out["unattributed_top"] = unattributed.most_common(25)
    rows = []
    for (kind, name), c in carry.items():
        if c["present"] < MIN_SPELL_N:
            continue
        sh = sorted(c["shares"])
        rows.append({"kind": kind, "name": name, "present": c["present"], "top": c["top"],
                     "top_rate": round(c["top"] / c["present"], 3),
                     "in_top5_rate": round(sum(1 for x in sh if x > 0) / len(sh), 3),
                     "median_share": round(sh[len(sh) // 2], 3)})
    out["carries"] = sorted(rows, key=lambda r: -r["top"])

    # ---------------------------------------------------------------- 3. archetypes
    base_s = Counter(n for b in builds for n in b["S"])
    base_i = Counter(n for b in builds for n in b["Iset"])
    N = len(builds)
    groups = defaultdict(list)
    for b in builds:
        c = b.get("carry")
        if c and c["share"] >= CARRY_SHARE:
            groups[(c["kind"], c["name"])].append(b)
    sp_id = {s["name"]: s.get("sp_id") for s in data["spells"]}
    up_id = {(s["name"], u["name"]): u.get("sp_id") for s in data["spells"] for u in s.get("upgrades", [])}
    eq_id = ids["equipment"]

    def b36(n: int) -> str:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        s = ""
        while True:
            n, r = divmod(n, 36)
            s = digits[r] + s
            if n == 0:
                return s

    def guide_link(title, core_sp, util_sp, core_eq, util_eq, upgrades_for):
        def sp_track(head, spells):
            items = []
            for s in spells:
                if sp_id.get(s) is None:
                    continue
                items.append(b36(sp_id[s]))
                for u in upgrades_for.get(s, []):
                    if up_id.get((s, u)) is not None:
                        items.append(b36(up_id[(s, u)]))
            return (head + ".".join(items)) if items else ""
        def eq_track(head, eqs):
            items = [b36(eq_id[e]) for e in eqs if e in eq_id]
            return (head + ".".join(items)) if items else ""
        eq = eq_track("C", core_eq) + eq_track("U", util_eq)
        sp = sp_track("C", core_sp) + sp_track("U", util_sp)
        clean_title = re.sub(r"[^A-Za-z0-9 '-]", "", title)[:40].strip().replace(" ", "-").lower()
        missing = [e for e in core_eq + util_eq if e not in eq_id] + [s for s in core_sp + util_sp if sp_id.get(s) is None]
        return f"https://hpp3.github.io/rw3/?g=1_{eq}_{sp}_{clean_title}", missing

    archetypes = []
    for (kind, name), members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) < MIN_GROUP:
            continue
        n = len(members)
        cs = Counter(x for b in members for x in b["S"])
        ci = Counter(x for b in members for x in b["Iset"])
        def lift(cnt, base, x):
            return (cnt[x] / n) / (base[x] / N)
        core_sp = [x for x, k in cs.most_common() if k / n >= 0.4 and lift(cs, base_s, x) >= 1.5]
        util_sp = [x for x, k in cs.most_common() if k / n >= 0.2 and lift(cs, base_s, x) < 1.3]
        core_eq = [x for x, k in ci.most_common() if k / n >= 0.25 and lift(ci, base_i, x) >= 1.5]
        util_eq = [x for x, k in ci.most_common() if k / n >= 0.2 and lift(ci, base_i, x) < 1.3]
        if kind == "spell":
            core_sp = [name] + [x for x in core_sp if x != name]
            util_sp = [x for x in util_sp if x != name]
        else:
            core_eq = [name] + [x for x in core_eq if x != name]
            util_eq = [x for x in util_eq if x != name]
        # a book that only grants a spell travels with it
        for s in list(core_sp):
            if s in granted_by and granted_by[s] not in core_eq:
                core_eq.append(granted_by[s])
        upgrades_for = {}
        upgrade_rates = {}
        for s in core_sp + util_sp:
            have = [sp for b in members for sp in b["spells"] if sp["name"] == s and not sp.get("from_left_panel")]
            if not have:
                continue
            uc = Counter(u for sp in have for u in sp["upgrades"])
            upgrade_rates[s] = [[u, round(k / len(have), 3)] for u, k in uc.most_common(6)]
            pick = [u for u, k in uc.most_common() if k / len(have) >= 0.35 and up_id.get((s, u)) is not None]
            upgrades_for[s] = pick[:4]
        title = f"{name} wins"
        link, missing = guide_link(title, core_sp[:8], util_sp[:6], core_eq[:8], util_eq[:6], upgrades_for)
        shares = sorted(b["carry"]["share"] for b in members)
        archetypes.append({
            "carry": name, "kind": kind, "n": n,
            "share_of_carried": round(n / max(1, sum(len(v) for v in groups.values())), 3),
            "median_damage_share": shares[len(shares) // 2],
            "normal_runs": sum(b["normal"] for b in members),
            "challenges": Counter(b["challenge"] or "none" for b in members).most_common(6),
            "eras": {e: sum(b["era"] == e for b in members) for e in era_names},
            "core_spells": [[x, round(cs[x] / n, 3), round(lift(cs, base_s, x), 2)] for x in core_sp[:8]],
            "utility_spells": [[x, round(cs[x] / n, 3)] for x in util_sp[:6]],
            "core_items": [[x, round(ci[x] / n, 3), round(lift(ci, base_i, x), 2) if base_i[x] else None] for x in core_eq[:8]],
            "utility_items": [[x, round(ci[x] / n, 3)] for x in util_eq[:6]],
            "upgrades": upgrade_rates,
            "guide": link, "not_in_compendium": missing,
            "thin": len(core_sp) + len(core_eq) <= 2,
            "members": [b["image"] for b in members],
        })
    out["archetypes"] = archetypes
    labelled = sum(len(v) for v in groups.values())
    out["archetype_coverage"] = {"with_damage": sum(1 for b in builds if b.get("carry") is not None),
                                 "clear_carry": labelled, "in_listed_groups": sum(a["n"] for a in archetypes),
                                 "mixed": sum(1 for b in builds if b.get("carry") and b["carry"]["share"] < CARRY_SHARE)}
    # "always good": supports that show up (>= 20%) across many archetypes rather than one
    spread_s, spread_i = Counter(), Counter()
    for a in archetypes:
        spread_s.update(x for x, _ in a["utility_spells"])
        spread_i.update(x for x, _ in a["utility_items"])
    out["always_good"] = {
        "archetypes": len(archetypes),
        "spells": [[x, k, round(base_s[x] / N, 3)] for x, k in spread_s.most_common(12) if k >= 3],
        "items": [[x, k, round(base_i[x] / N, 3)] for x, k in spread_i.most_common(12) if k >= 3],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n_builds", "dataset", "carry_coverage", "archetype_coverage")}, indent=1))
    print("unattributed:", out["unattributed_top"][:15])
    print("archetypes:", [(a["carry"], a["n"], a["thin"]) for a in archetypes])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

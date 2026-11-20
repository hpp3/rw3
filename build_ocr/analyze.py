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
ENGINE_SHARE = 0.4       # the root spell must hold this share of the run's spell damage to label it
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


def cast_links(data: dict) -> list:
    """(engine spell, upgrade that enables it or None, spell it casts for free), read from the
    compendium's spell and upgrade descriptions: "Watcher Form also casts Chain Lightning each
    turn", "Cast Fireball on each tile Chain Lightning arcs to"."""
    names = sorted({s["name"] for s in data["spells"]}, key=len, reverse=True)
    links = []

    def scan(text, src, up):
        text = re.sub(r"\[([^\]:]+)(?::[^\]]*)?\]", r"\1", text or "")
        for n in names:
            if n != src and re.search(r"\b(?i:casts?)\s+(?:a\s+|an\s+|your\s+)?" + re.escape(n) + r"\b", text):
                links.append((src, up, n))
    for s in data["spells"]:
        scan(s.get("desc"), s["name"], None)
        for u in s.get("upgrades") or []:
            scan(u.get("desc"), s["name"], u["name"])
    return links


def root_chain(spell, build_spells, upgrades, links, seen=None) -> list:
    """Follow free casts upward: Fireball <- Chain Lightning (Chain Fireball) <- Watcher Form
    (Chain Watcher Form). Only links whose engine is in the build, with the enabling upgrade."""
    seen = (seen or set()) | {spell}
    best = [spell]
    for eng, up, target in links:
        if target != spell or eng in seen or eng not in build_spells:
            continue
        if up is not None and up not in upgrades.get(eng, ()):
            continue
        chain = root_chain(eng, build_spells, upgrades, links, seen) + [spell]
        if len(chain) > len(best):
            best = chain
    return best


def improviser_block(builds: list, data: dict, all_upgrades: list) -> dict:
    """Improviser removes a random 75% of the spellbook and of the craftable equipment each run
    (Mutators.py RandomSpellRestriction / RandomEquipmentRestriction), so every spell is on offer
    in about a quarter of runs. Pick rate / 0.25 estimates how often a winner took it when they
    could: a test of the spell on its own, free of the combos people plan in normal runs.
    Upgrades are not restricted, and Improviser players are strong, so their upgrade picks are
    compared with everyone's."""
    imp = [b for b in builds if b.get("challenge") == "Improviser"]
    late = dt.date(2026, 9, 1)  # most Improviser wins are from the Sep 1 and Oct 12 patches
    norm = [b for b in builds if b["normal"] and dt.datetime.fromtimestamp(b["posted"] / 1000, dt.UTC).date() >= late]
    if not imp:
        return {}
    n = len(imp)
    book = len({s["name"] for s in data["spells"]})
    avg_imp = sum(len(b["S"]) for b in imp) / n
    avg_norm = sum(len(b["S"]) for b in norm) / max(1, len(norm))
    base_imp, base_norm = avg_imp / (0.25 * book), avg_norm / book
    level = {s["name"]: s.get("level") for s in data["spells"]}
    granted = {s["name"]: s["granted_by"] for s in data["spells"] if s.get("granted_by")}
    craftable = {e["name"] for e in data["equipment"]}
    cs = Counter(x for b in imp for x in b["S"])
    cn = Counter(x for b in norm for x in b["S"])
    spells = []
    for name, k in cs.most_common():
        lo, hi = wilson(k, n)
        x_imp = (k / (0.25 * n)) / base_imp
        x_norm = (cn[name] / max(1, len(norm))) / base_norm
        role = ("everywhere" if x_imp >= 2.5 and x_norm >= 2.5 else
                "alone" if x_imp >= 2.5 and x_norm <= 1.5 else
                "plan" if x_norm >= 3 and x_imp <= x_norm / 1.6 else None)
        spells.append({"name": name, "level": level.get(name), "k": k, "offered": round(min(1, k / (0.25 * n)), 3),
                       "lo": round(min(1, lo / 0.25), 3), "hi": round(min(1, hi / 0.25), 3),
                       "x_imp": round(x_imp, 2), "x_norm": round(x_norm, 2), "k_norm": cn[name],
                       "granted_by": granted.get(name), "role": role})
    ci = Counter(x for b in imp for x in b["Iset"] if x in craftable)
    items = []
    for name, k in ci.most_common(30):
        lo, hi = wilson(k, n)
        items.append({"name": name, "k": k, "offered": round(min(1, k / (0.25 * n)), 3),
                      "lo": round(min(1, lo / 0.25), 3), "hi": round(min(1, hi / 0.25), 3)})
    # upgrade picks where the player chose 1-2 upgrades: Improviser vs every run
    everyone = {u["spell"]: u for u in all_upgrades}
    per = defaultdict(lambda: {"chosen": 0, "counts": Counter()})
    for b in imp:
        if b.get("incomplete"):
            continue
        for s in b["spells"]:
            ups = [x for x in s["upgrades"] if x not in (s.get("unknown_upgrades") or [])]
            if s.get("unknown") or s.get("from_left_panel") or not ups or len(s["upgrades"]) >= 3:
                continue
            per[s["name"]]["chosen"] += 1
            per[s["name"]]["counts"].update(ups)
    upgrades = []
    for name, p in sorted(per.items(), key=lambda kv: -kv[1]["chosen"]):
        if p["chosen"] < 8 or name not in everyone:
            continue
        e = everyone[name]
        e_rate = {u: k / max(1, e["chosen_n"]) for u, k in e["take"]}
        rows = []
        for u, _ in e["take"]:
            ri = p["counts"][u] / p["chosen"]
            rows.append([u, round(ri, 3), round(e_rate.get(u, 0), 3)])
        rows.sort(key=lambda r: -r[1])
        biggest = max(rows, key=lambda r: abs(r[1] - r[2]))
        upgrades.append({"spell": name, "chosen": p["chosen"], "everyone_chosen": e["chosen_n"], "rows": rows,
                         "differs": abs(biggest[1] - biggest[2]) >= 0.2, "biggest": biggest})
    return {"n": n, "normal_late_n": len(norm), "spellbook": book, "base_imp": round(base_imp, 3),
            "base_norm": round(base_norm, 4), "eras": Counter(b["era"] for b in imp).most_common(),
            "spells": spells, "items": items, "upgrades": upgrades}


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
    ap.add_argument("--only-challenge", help="restrict to one challenge, e.g. Improviser")
    ap.add_argument("--min-group", type=int, default=MIN_GROUP, help="smallest archetype shown")
    args = ap.parse_args()
    data, ids, added = load_site(args.site)
    spell_info = {s["name"]: s for s in data["spells"]}
    granted_by = {s["name"]: s["granted_by"] for s in data["spells"] if s.get("granted_by")}
    grants = {v: k for k, v in granted_by.items()}
    builds = [json.loads(l) for l in args.builds.read_text(encoding="utf-8").splitlines()]
    if args.only_challenge:
        builds = [b for b in builds if (b.get("challenge") or "") == args.only_challenge]
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
                u["pushed"] += 1  # extra upgrades from shrines / the Codex: not a free choice
            elif ups:
                u["chosen_n"] += 1  # the player picked 1-2 upgrades themselves
                u["counts"].update(ups)
    out["upgrades"] = []
    for name, u in sorted(upg.items(), key=lambda kv: -kv[1]["n"]):
        if u["n"] < 15:
            continue
        known = [x["name"] for x in spell_info.get(name, {}).get("upgrades", [])]
        out["upgrades"].append({
            "spell": name, "n": u["n"], "chosen_n": u["chosen_n"], "pushed": u["pushed"],
            "none": u["none"],
            "take": [[x, u["counts"][x]] for x in sorted(known, key=lambda x: -u["counts"][x])],
            "take_all": [[x, u["all_counts"][x]] for x in sorted(known, key=lambda x: -u["all_counts"][x])],
        })

    # upgrades that (almost) always come with their spell, measured where the player chose 1-2
    # upgrades themselves (an unupgraded support or a spell pushed to 3+ says nothing about choice)
    sig = []
    for u in out["upgrades"]:
        if u["chosen_n"] < 12:
            continue
        upgraded = u["n"] - u["none"]
        all_k = dict(u["take_all"])
        for name, k in u["take"]:
            if k / u["chosen_n"] >= 0.7:
                sig.append({"spell": u["spell"], "upgrade": name, "k": k, "chosen_n": u["chosen_n"],
                            "rate": round(k / u["chosen_n"], 3), "n": u["n"],
                            "rate_upgraded": round(all_k.get(name, 0) / max(1, upgraded), 3)})
    out["signature_upgrades"] = sorted(sig, key=lambda r: -r["rate"])

    # ---------------------------------------------------------------- 2. carries
    att = Attributor(data, args.game)
    links = cast_links(data)
    out["cast_links"] = [list(l) for l in links]
    item_rows = defaultdict(lambda: {"present": 0, "listed": 0, "shares": [], "with": Counter()})
    eng_rows = defaultdict(lambda: {"present": 0, "top": 0, "listed": 0, "shares": []})
    unattributed = Counter()
    totals = Counter()
    for b in builds:
        b["engine"] = None
        dmg = b["damage_to_enemies"]
        if not dmg:
            continue
        upgrades = {sp["name"]: set(sp["upgrades"]) for sp in b["spells"]}
        owners = [(v or 0, src, *att.owner(src, b["S"], b["Iset"])) for v, src in dmg]
        total = sum(v for v, _, kind, _ in owners if kind != "enemy") or 1
        by_root, by_chain, by_item = Counter(), Counter(), Counter()
        for v, src, kind, who in owners:
            totals[kind] += v
            if kind in ("unattributed", "monster"):
                unattributed[f"{src} ({kind})"] += 1
            if kind == "spell":
                chain = root_chain(who, b["S"], upgrades, links)
                by_root[chain[0]] += v
                by_chain[" > ".join(chain)] += v
            elif kind == "item":
                by_item[who] += v
        spell_total = sum(by_root.values())
        if by_root:
            root, v = by_root.most_common(1)[0]
            best_chain = max((c for c in by_chain if c.split(" > ")[0] == root), key=lambda c: by_chain[c])
            b["engine"] = {"name": root, "chain": best_chain, "share_of_spells": round(v / spell_total, 3),
                           "share_of_total": round(v / total, 3)}
        for r in {root_chain(x, b["S"], upgrades, links)[0] for x in b["S"]}:
            e = eng_rows[r]
            e["present"] += 1
            e["listed"] += r in by_root
            e["shares"].append(by_root.get(r, 0) / total)
        if b["engine"]:
            eng_rows[b["engine"]["name"]]["top"] += 1
        for i in b["Iset"]:
            it = item_rows[i]
            it["present"] += 1
            if i in by_item:
                it["listed"] += 1
                it["shares"].append(by_item[i] / total)
                if b["engine"]:
                    it["with"][b["engine"]["name"]] += 1
    out["carry_coverage"] = {k: round(v / max(1, sum(totals.values())), 4) for k, v in totals.items()}
    out["unattributed_top"] = unattributed.most_common(25)
    rows = []
    for name, e in eng_rows.items():
        if e["present"] < MIN_SPELL_N:
            continue
        sh = sorted(e["shares"])
        rows.append({"kind": "spell", "name": name, "present": e["present"], "top": e["top"],
                     "top_rate": round(e["top"] / e["present"], 3), "in_top5_rate": round(e["listed"] / e["present"], 3),
                     "median_share": round(sh[len(sh) // 2], 3)})
    out["carries"] = sorted(rows, key=lambda r: -r["top"])
    irows = []
    for name, it in item_rows.items():
        if it["listed"] < 15:
            continue
        sh = sorted(it["shares"])
        irows.append({"name": name, "present": it["present"], "listed": it["listed"],
                      "median_share_when_listed": round(sh[len(sh) // 2], 3),
                      "with": it["with"].most_common(4)})
    out["item_damage"] = sorted(irows, key=lambda r: -r["listed"])

    # ---------------------------------------------------------------- 3. archetypes
    # A run's archetype is the spell at the root of most of its spell damage on the final realm,
    # after following free casts upward (Fireball <- Chain Lightning <- Watcher Form). Items never
    # define an archetype (they augment spells); they are listed as pairings.
    base_s = Counter(n for b in builds for n in b["S"])
    base_i = Counter(n for b in builds for n in b["Iset"])
    N = len(builds)
    groups = defaultdict(list)
    for b in builds:
        e = b.get("engine")
        if e and e["share_of_spells"] >= ENGINE_SHARE:
            groups[e["name"]].append(b)
    sp_id = {x["name"]: x.get("sp_id") for x in data["spells"]}
    up_id = {(x["name"], u["name"]): u.get("sp_id") for x in data["spells"] for u in x.get("upgrades", [])}
    eq_id = ids["equipment"]

    def b36(n: int) -> str:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        out_ = ""
        while True:
            n, r = divmod(n, 36)
            out_ = digits[r] + out_
            if n == 0:
                return out_

    def guide_link(title, core_sp, util_sp, core_eq, util_eq, upgrades_for):
        def sp_track(head, spells):
            items = []
            for x in spells:
                if sp_id.get(x) is None:
                    continue
                items.append(b36(sp_id[x]))
                for u in upgrades_for.get(x, []):
                    if up_id.get((x, u)) is not None:
                        items.append(b36(up_id[(x, u)]))
            return (head + ".".join(items)) if items else ""

        def eq_track(head, eqs):
            items = [b36(eq_id[e]) for e in eqs if e in eq_id]
            return (head + ".".join(items)) if items else ""
        eq = eq_track("C", core_eq) + eq_track("U", util_eq)
        sp = sp_track("C", core_sp) + sp_track("U", util_sp)
        clean_title = re.sub(r"[^A-Za-z0-9 '-]", "", title)[:40].strip().replace(" ", "-").lower()
        missing = [e for e in core_eq + util_eq if e not in eq_id] + [x for x in core_sp + util_sp if sp_id.get(x) is None]
        return f"https://hpp3.github.io/rw3/?g=1_{eq}_{sp}_{clean_title}", missing

    archetypes = []
    for name, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) < args.min_group:
            continue
        n = len(members)
        cs = Counter(x for b in members for x in b["S"])
        ci = Counter(x for b in members for x in b["Iset"])

        def lift(cnt, base, x):
            return (cnt[x] / n) / (base[x] / N)
        chains = Counter(b["engine"]["chain"] for b in members)
        chain_spells = [x for c, _ in chains.most_common(2) for x in c.split(" > ")]
        core_sp = [x for x, k in cs.most_common() if k / n >= 0.4 and lift(cs, base_s, x) >= 1.5]
        util_sp = [x for x, k in cs.most_common() if k / n >= 0.2 and lift(cs, base_s, x) < 1.3]
        core_eq = [x for x, k in ci.most_common() if k / n >= 0.25 and lift(ci, base_i, x) >= 1.5]
        util_eq = [x for x, k in ci.most_common() if k / n >= 0.2 and lift(ci, base_i, x) < 1.3]
        lead = [name] + [x for x in dict.fromkeys(chain_spells) if x != name and cs[x] / n >= 0.3]
        core_sp = lead + [x for x in core_sp if x not in lead]
        util_sp = [x for x in util_sp if x not in core_sp]
        for x in list(core_sp):  # a book that only grants a spell travels with it
            if x in granted_by and granted_by[x] not in core_eq:
                core_eq.append(granted_by[x])
        upgrades_for, upgrade_rates = {}, {}
        for x in core_sp + util_sp:
            have = [sp for b in members for sp in b["spells"] if sp["name"] == x and not sp.get("from_left_panel")]
            if not have:
                continue
            uc = Counter(u for sp in have for u in sp["upgrades"])
            upgrade_rates[x] = [[u, round(k / len(have), 3)] for u, k in uc.most_common(6)]
            upgrades_for[x] = [u for u, k in uc.most_common() if k / len(have) >= 0.35 and up_id.get((x, u)) is not None][:4]
        link, missing = guide_link(f"{name} wins", core_sp[:8], util_sp[:6], core_eq[:8], util_eq[:6], upgrades_for)
        shares = sorted(b["engine"]["share_of_total"] for b in members)
        archetypes.append({
            "carry": name, "kind": "spell", "n": n,
            "chains": [[c, k] for c, k in chains.most_common(4)],
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
            "members": [b["image"] for b in members],
        })
    out["archetypes"] = archetypes
    out["archetype_coverage"] = {
        "with_damage": sum(1 for b in builds if b["damage_to_enemies"]),
        "with_spell_damage": sum(1 for b in builds if b.get("engine")),
        "clear_engine": sum(len(v) for v in groups.values()),
        "in_listed_groups": sum(a["n"] for a in archetypes),
        "mixed": sum(1 for b in builds if b.get("engine") and b["engine"]["share_of_spells"] < ENGINE_SHARE),
    }
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
    if not args.only_challenge:
        out["improviser"] = improviser_block(builds, data, out["upgrades"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n_builds", "dataset", "carry_coverage", "archetype_coverage")}, indent=1))
    print("unattributed:", out["unattributed_top"][:15])
    print("archetypes:", [(a["carry"], a["n"], a["chains"][0]) for a in archetypes])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build vocab.json: every name the build parser may snap OCR text to.

    python -I vocab.py --data ../site/data.json --data ../site/data.beta.json --game "E:/SteamLibrary/steamapps/common/Rift Wizard 3"

Sources: the compendium's extracted data (spells with their upgrades, craftable equipment),
plus things it does not list because they are rewards rather than crafts, read from the game
source: Bookshelf tomes ("<Tag> Tome"), Tavern companions, and the Archmage Trials names.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def companions(game: Path) -> list[str]:
    eq = (game / "Equipment.py").read_text(encoding="utf-8")
    block = eq[eq.index("all_companions = ["):]
    block = block[: block.index("]\n")]
    classes = re.findall(r"Companion\((\w+),", block)
    names = []
    src = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in game.glob("*.py"))
    for cls in classes:
        m = re.search(rf"^def {cls}\(\):(?:\n[ \t].*){{0,12}}?\n[ \t]+\w+\.name = \"([^\"]+)\"", src, re.M)
        names.append(m.group(1) if m else re.sub(r"(?<!^)([A-Z])", r" \1", cls))
    return names


def trials(game: Path) -> list[str]:
    mut = (game / "Mutators.py").read_text(encoding="utf-8")
    block = mut[mut.index("all_trials = ["):]
    block = block[: block.index("]]")]
    return re.findall(r'^\s*\("([^"]+)",', block, re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, action="append", required=True)
    ap.add_argument("--game", type=Path, required=True)
    ap.add_argument("--history", type=Path, help="compendium site/history.json (names from older builds)")
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("vocab.json"))
    args = ap.parse_args()

    spells: dict[str, dict] = {}
    equipment: dict[str, str] = {}
    tags: set[str] = set()
    for path in args.data:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in data["spells"]:
            entry = spells.setdefault(s["name"], {"level": s.get("level"), "tags": s.get("tags", []), "upgrades": []})
            for u in s.get("upgrades", []):
                if u.get("name") and u["name"] not in entry["upgrades"]:
                    entry["upgrades"].append(u["name"])
            tags.update(s.get("tags", []))
        for e in data["equipment"]:
            equipment.setdefault(e["name"], "crafted")
    # names that existed in earlier builds (screenshots go back to June) but were removed or renamed
    if args.history and args.history.exists():
        hist = json.loads(args.history.read_text(encoding="utf-8"))
        for branch in hist["branches"].values():
            for kinds in list(branch.get("added", {}).values()) + list(branch.get("changed", {}).values()):
                for name in kinds.get("spell", []):
                    spells.setdefault(name, {"level": None, "tags": [], "upgrades": [], "removed": True})
                for name in kinds.get("equipment", []):
                    equipment.setdefault(name, "removed")
    for t in sorted(tags):
        equipment.setdefault(f"{t} Tome", "tome")
    for c in companions(args.game):
        equipment.setdefault(c, "companion")
    # non-craftable items the compendium skips (e.g. Necromancer's Locket): every literal name
    # assigned in Equipment.py, plus the FreeCastStaff("Name", ...) staves
    eq_src = (args.game / "Equipment.py").read_text(encoding="utf-8")
    for name in re.findall(r'^\s+self\.name = "([^"{}]+)"', eq_src, re.M) + re.findall(r'FreeCastStaff\("([^"]+)"', eq_src):
        equipment.setdefault(name, "source")

    # seen in equipment columns of real screenshots but absent from the compendium and the live
    # Equipment.py: units granted as companions by rewards (RareMonsters.py) and a removed item
    for name in ("Great Faery", "Shrine Maiden", "Seal of Usmu"):
        equipment.setdefault(name, "observed")
    # spells renamed since June: old name -> current name. Only add a pair after checking a
    # screenshot (e.g. "Shatterstar" looked like one but is an old Dream the Starwhale upgrade).
    aliases: dict[str, str] = {}
    vocab = {
        "spell_aliases": aliases,
        "spells": dict(sorted(spells.items())),
        "equipment": dict(sorted(equipment.items())),
        "trials": trials(args.game),
        "sources": [str(p) for p in args.data] + [str(args.game)],
    }
    args.out.write_text(json.dumps(vocab, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(spells)} spells, {sum(len(v['upgrades']) for v in spells.values())} upgrades, "
          f"{len(equipment)} equipment ({sum(v == 'tome' for v in equipment.values())} tomes, "
          f"{sum(v == 'companion' for v in equipment.values())} companions), {len(vocab['trials'])} trials -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Independent verification that data.json unit resists match the game's bestiary.

Reconstructs every monster from the game's own spawn registries (separately from
extract.py), applies the game's set_default_resistances(), and renders the resist
lines through the game's actual examine-panel logic (RiftWizard3 unit draw:
filter nonzero -> sort by -value -> positive group then negative group, each line
via text.RESIST_VAL). Then renders data.json's stored resists with the SAME
template and compares line-for-line.
"""
import os, sys, json
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

GAME = r"E:\SteamLibrary\steamapps\common\Rift Wizard 3 Demo"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, GAME)
os.chdir(GAME)

import Equipment  # noqa: import order (circular imports) — Equipment first
import Spells, Components  # noqa
import text
from Level import resolve_text, Tags, tag_label, Unit
import Monsters, RareMonsters


def render_resist_lines(resists):
    """Exact replica of RiftWizard3 unit-examine resist rendering (line ~7712)."""
    tags = [t for t in Tags if t in resists and resists[t] != 0]
    tags.sort(key=lambda t: -resists[t])
    lines = []
    for negative in (False, True):
        for t in tags:
            if (resists[t] < 0) != negative:
                continue
            lines.append(resolve_text((text.RESIST_VAL,
                         {"val": resists[t], "tag_label": tag_label(t)})))
    return lines


def tagname_to_tag():
    return {t.name: t for t in Tags}


# --- reconstruct the bestiary roster independently of extract.py ------------
def collect_factories():
    facs = {}
    for entry in Monsters.spawn_options:
        facs.setdefault(entry[0], None)
        if len(entry) > 2 and entry[2]:
            facs.setdefault(entry[2], None)
    for ln in ['MONSTER_PACKS', 'IDOLS', 'SUPER_SPAWNERS', 'SPECIAL_MONSTERS', 'WIZARDS', 'KAIJU']:
        for entry in getattr(RareMonsters, ln, None) or []:
            facs.setdefault(entry[0], None)
    return facs


def game_resists_by_name():
    """name -> game-authoritative resists dict (after set_default_resistances)."""
    out = {}
    for fac in collect_factories():
        try:
            u = fac()
        except Exception:
            continue
        if not isinstance(u, Unit):
            continue
        if u.name in out:
            continue
        u.set_default_resistances()
        out[u.name] = {t: v for t, v in u.resists.items() if v}
    return out


def main():
    data = json.load(open(os.path.join(HERE, 'site', 'data.json'), encoding='utf-8'))
    units = data['units']
    name2tag = tagname_to_tag()

    game = game_resists_by_name()

    checked = mism = 0
    missing_from_data = []
    mismatches = []

    for name, game_res in game.items():
        if name not in units:
            missing_from_data.append(name)
            continue
        checked += 1
        # data.json stores resists keyed by tag *name*; map back to Tag objects.
        data_res = {}
        for tname, v in units[name]['resists'].items():
            if tname in name2tag:
                data_res[name2tag[tname]] = v
        game_lines = render_resist_lines(game_res)
        data_lines = render_resist_lines(data_res)
        if game_lines != data_lines:
            mism += 1
            mismatches.append((name, game_lines, data_lines))

    print(f"monsters reconstructed: {len(game)}")
    print(f"compared (present in data.json): {checked}")
    print(f"PERFECT matches: {checked - mism}")
    print(f"MISMATCHES: {mism}")
    if missing_from_data:
        print(f"\n[!] in game roster but not in data.json ({len(missing_from_data)}): {missing_from_data[:10]}")
    for name, g, d in mismatches[:40]:
        print(f"\n--- {name} ---")
        print("  game :", g)
        print("  data :", d)

    # Spot-print a few well-known units so the output is human-auditable.
    print("\n=== Sample rendered bestiary lines (game == data) ===")
    for name in ['Vampire', 'Skeleton', 'Holy Ghost', 'Bone Knight', 'Ghost']:
        if name in game:
            for ln in render_resist_lines(game[name]):
                print(f"  {name}: {ln}")

    sys.exit(1 if (mism or missing_from_data) else 0)


if __name__ == '__main__':
    main()

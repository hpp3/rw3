"""Independent verification that data.json spell & spell-upgrade descriptions
match what the game's examine panels actually render.

Philosophy mirrors verify_resists.py:
  * Reconstruct the spell roster from the game's own registries
    (Spells.all_player_spell_constructors + forbidden SpellBook grants),
    separately from extract.py.
  * Pull each description straight from the live game objects' own methods
    (get_description / get_tooltip / fmt_dict) -- the source of truth.
  * Re-implement the game's draw_examine_spell / draw_examine_upgrade text
    assembly *from the RiftWizard3 draw code*, not from extract.py.
  * Render through the game's resolve_text + text templates.
  * Compare line-for-line against data.json.

Shared plumbing (not re-derived): the reconstructed `tooltip_colors` and
`TT_ATTRS` tables come from extract -- the game's UI module isn't importable in
this env (no steamworks), exactly why extract mirrors them. They only pick a
template *color variant*; the description content and panel assembly here are
independent.
"""
import os, sys, json
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = r"E:\SteamLibrary\steamapps\common\Rift Wizard 3"
sys.path.insert(0, GAME)
os.chdir(GAME)

import Equipment, Spells, Components  # noqa: import order (circular imports)
import text
from Level import (resolve_text, Tags, Spell, format_attr, tag_label,
                   tag_key, attr_key)

# Shared plumbing only (color variant tables) -- see module docstring.
import importlib.util
_spec = importlib.util.spec_from_file_location('rw3extract', os.path.join(HERE, 'extract.py'))
_ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ex)
tooltip_colors = _ex.tooltip_colors
TT_ATTRS = _ex.TT_ATTRS


def R(value, fmt=None):
    try:
        return resolve_text(value, fmt=fmt)
    except Exception:
        return ""


# --- reproduce RiftWizard3.draw_examine_spell description (line ~7352) -------
def game_spell_desc(spell):
    return R(spell.get_description() or "", fmt=spell.fmt_dict())


# --- reproduce RiftWizard3.draw_examine_upgrade (lines ~7113-7182) -----------
def game_upgrade_desc(up):
    lines = []

    def add(tmpl, **kw):
        s = R((tmpl, kw))
        if s:
            lines.append(s)

    for tag, bonuses in up.tag_bonuses_pct.items():
        for attr, val in bonuses.items():
            add(text.TAG_PCT_BONUS, tag_label=tag_label(tag), tag_key=tag_key(tag),
                val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    for tag, bonuses in up.tag_bonuses.items():
        for attr, val in bonuses.items():
            add(text.TAG_VAL_BONUS, tag_label=tag_label(tag), tag_key=tag_key(tag),
                val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    for spell, bonuses in up.spell_bonuses_pct.items():
        sp = spell()
        for attr, val in bonuses.items():
            if attr not in sp.stats:
                continue
            tmpl = text.GAIN_PCT_COLORED if attr in tooltip_colors else text.GAIN_PCT_PLAIN
            add(tmpl, name=sp.name, val=val, attr_label=format_attr(attr), attr_key=attr_key(attr))
    for spell, bonuses in up.spell_bonuses.items():
        sp = spell()
        for attr, val in bonuses.items():
            if attr not in sp.stats:
                continue
            tmpl = text.GAIN_VAL_COLORED if attr in tooltip_colors else text.GAIN_VAL_PLAIN
            add(tmpl, name=sp.name, val=val, attr_label=format_attr(attr), attr_key=attr_key(attr))
    if hasattr(up, 'new_attributes') and hasattr(up, 'prereq'):
        for attr, val in up.new_attributes.items():
            if attr in TT_ATTRS or attr == 'hp_cost':
                add(text.GAIN_VAL_COLORED, name=up.prereq.name, val=val,
                    attr_label=format_attr(attr), attr_key=attr_key(attr))
    for attr, val in up.global_bonuses_pct.items():
        tmpl = text.ALL_GAIN_PCT if val >= 0 else text.ALL_LOSE_PCT
        add(tmpl, val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    for attr, val in up.global_bonuses.items():
        tmpl = text.ALL_GAIN_VAL if val >= 0 else text.ALL_LOSE_VAL
        add(tmpl, val=int(val), attr_label=format_attr(attr), attr_key=attr_key(attr))
    # Game draws EVERY key in upgrade.resists (no value filter).
    for tag in up.resists:
        add(text.RESIST_VAL, val=up.resists[tag], tag_label=tag_label(tag))

    # Game: desc = get_description() or get_tooltip()
    raw = up.get_description() or up.get_tooltip()
    prose = R(raw or "", fmt=up.fmt_dict())
    if prose:
        lines.append(prose)
    return "\n".join(lines)


def build_roster():
    """name -> (spell instance) for all player + forbidden spells."""
    spells = {}
    for cons in Spells.all_player_spell_constructors:
        s = cons()
        spells.setdefault(s.name, s)
    for s, _eq in _ex.forbidden_granted().values():
        spells.setdefault(s.name, s)
    return spells


def main():
    data = json.load(open(os.path.join(HERE, 'site', 'data.json'), encoding='utf-8'))
    by_name = {e['name']: e for e in data['spells']}

    roster = build_roster()

    spell_checked = spell_bad = 0
    up_checked = up_bad = 0
    tooltip_fallbacks = []   # upgrades where get_description() empty but get_tooltip() not
    spell_mismatches = []
    up_mismatches = []
    missing = []

    for name, s in roster.items():
        if name not in by_name:
            missing.append(name)
            continue
        entry = by_name[name]

        # --- spell description ---
        spell_checked += 1
        g = game_spell_desc(s)
        if g != entry['desc']:
            spell_bad += 1
            spell_mismatches.append((name, g, entry['desc']))

        # --- upgrades ---
        data_ups = {u['name']: u for u in entry.get('upgrades', [])}
        for up in s.spell_upgrades:
            up_checked += 1
            if not (up.get_description()) and up.get_tooltip():
                tooltip_fallbacks.append((name, up.name))
            g = game_upgrade_desc(up)
            d = data_ups.get(up.name, {}).get('desc')
            if up.name not in data_ups:
                up_mismatches.append((name, up.name, g, '<missing upgrade in data.json>'))
                up_bad += 1
            elif g != d:
                up_bad += 1
                up_mismatches.append((name, up.name, g, d))

    print(f"spells compared:   {spell_checked}   PERFECT: {spell_checked - spell_bad}   MISMATCH: {spell_bad}")
    print(f"upgrades compared: {up_checked}   PERFECT: {up_checked - up_bad}   MISMATCH: {up_bad}")
    if missing:
        print(f"\n[!] in roster but not in data.json ({len(missing)}): {missing}")
    if tooltip_fallbacks:
        print(f"\n[i] upgrades using get_tooltip() fallback (extract uses get_description() or ''): "
              f"{len(tooltip_fallbacks)}")
        for sp, up in tooltip_fallbacks:
            print(f"      {sp} :: {up}")

    def show(label, items):
        for a in items[:30]:
            print(f"\n--- {label}: {' :: '.join(str(x) for x in a[:-2])} ---")
            print("  game :", repr(a[-2]))
            print("  data :", repr(a[-1]))

    show("SPELL", spell_mismatches)
    show("UPGRADE", up_mismatches)

    # Human-auditable samples.
    print("\n=== Sample rendered descriptions (game; should equal data.json) ===")
    for name in ['Fireball', 'Magic Missile', 'Lightning Bolt']:
        if name in roster:
            print(f"\n[{name}] {game_spell_desc(roster[name])!r}")
            for up in roster[name].spell_upgrades[:2]:
                print(f"   <{up.name}> {game_upgrade_desc(up)!r}")

    sys.exit(1 if (spell_bad or up_bad or missing) else 0)


if __name__ == '__main__':
    main()

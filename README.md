# Rift Wizard 3 Compendium

A searchable, filterable browser resource for **Rift Wizard 3** spells, equipment, and
crafting components.

## What it does

The static site (`site/`) lets you:

- **Equipment** — browse all 350 craftable items. Filter by **slot**
  (Trinket / Head / Body / Feet / Weapon — slots aren't shown in-game, but are exposed here),
  search by name/effect, and **filter by recipe tag** (e.g. *"show me everything that crafts
  from Dark"*). Each card shows the icon, slot, item tags, full effect/bonus text, and the
  recipe with per-tag counts.
- **Stat search** (Equipment & Spells) — type a stat name or synonym (e.g. `dama`, `minion hp`,
  `charges`) and an autocomplete offers *Modifies X* (grants a bonus to that stat) and
  *Scales with X* (has an effect that uses it), each with a result count. Selecting one clears
  the search box and adds a removable filter chip; plain text stays a substring match until you
  pick a suggestion. Stat tags are derived **programmatically** from each item's bonus dicts
  (`global/tag/spell_bonuses`) and its scaling `stats`, not from description text. *(Boundary:
  effects that add damage through bespoke handlers rather than the engine's stat-bonus system —
  e.g. Boiling Blood's `extra_damage` — are intentionally not tagged, as there's no structured
  signal to read.)*
- **Build / wishlist** — on the Equipment tab, *＋ Build* toggles an item into a sticky build
  bar at the top that aggregates the **total essence (tag) count** needed to craft the whole
  set (specific tags + `Any`), and lists each item with its cost and recipe. It persists across
  reloads (localStorage). Hovering an item name shows its full stat card.
- **Components & inventory** — all 83 component items (tiers 1–3 + rares) with their on-pickup /
  on-craft effects. *＋ Add to pool* collects components into a **"My components"** inventory
  (mental model: *"I have 2 Chaos Seeds and 1 Blood Basin"*), shown as editable chips between
  the search and the list, with the derived essence pool underneath. Persists across reloads.
- **Craft Calculator** — automatically uses the essence pool derived from your component
  inventory and shows **what you can craft**. `Any` recipe requirements are filled by leftover
  essences; an *"Allow missing ≤ N"* option shows items that are almost within reach; results
  can be narrowed by slot and by the same stat search (Modifies/Scales-with) as the other tabs.
- **Spells** — all 186 player spells with level, tags, stats, descriptions, and upgrades.
- **Summon stat sheets** — any spell, item, or component that summons a unit shows the
  unit(s) as chips; hovering one pops a floating stat sheet (HP, tags, resistances,
  movement, abilities with damage/range/cooldown, and passives) for all 191 summonable units.

All text is rendered with the game's own tag/stat coloring.

## Rebuilding the data

The data is extracted directly from the game's Python source (no manual transcription).

```sh
# 1. one-time: create venv with the game's runtime deps
python -m venv .venv
.venv/Scripts/python.exe -m pip install tcod==18.1.0 numpy==2.2.6 pygame==2.6.1 dill==0.4.0

# 2. extract data.json + copy icons into site/
.venv/Scripts/python.exe build.py

# 3. serve
.venv/Scripts/python.exe -m http.server 8777 --directory site
# open http://localhost:8777
```

The build reads **only** from the game install dir
(`E:\SteamLibrary\steamapps\common\Rift Wizard 3 Demo`, set at the top of `extract.py` /
`copy_icons.py`) and writes only into `site/`. Update that path if your install differs.

### Scripts

| file | purpose |
|------|---------|
| `extract.py` | imports the game modules headlessly and dumps `site/data.json` (spells, equipment, components, tag colors). |
| `copy_icons.py` | copies referenced icon PNGs into `site/icons/{spells,equipment,components}/`, lowercasing filenames for web case-sensitivity. |
| `build.py` | runs both of the above. |

## Deploying

`site/` is a plain static folder — drop it on Cloudflare Pages / Netlify / GitHub Pages, or
any static host. No build step is needed on the host.

---

*Unofficial fan resource. Game data & icons © Rift Wizard 3.*

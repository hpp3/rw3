# Rift Wizard 3 Compendium

A searchable, filterable browser resource for **Rift Wizard 3** spells, equipment, and
crafting components.

> Working on the code? Read **[ARCHITECTURE.md](ARCHITECTURE.md)** first — it covers the
> non-obvious build/runtime decisions (extracting from the live game, AST cross-references,
> the crafting model, CSS sprite animation, caching) that aren't apparent from the code alone.

## What it does

The static site (`site/`) lets you:

- **Equipment** — browse all 350 craftable items. Filter by **slot**
  (Trinket / Head / Body / Feet / Weapon — slots aren't shown in-game, but are exposed here),
  search by name/effect, and **filter by recipe tag** (e.g. *"show me everything that crafts
  from Dark"*). Each card shows the icon, slot, item tags, full effect/bonus text, and the
  recipe with per-tag counts. A **Craftable only** toggle restricts the list to what your
  current component inventory can make (combined with all other filters).
- **Stat search** (Equipment & Spells) — type a stat name or synonym (e.g. `dama`, `minion hp`,
  `charges`) and an autocomplete offers *Modifies X* (grants a bonus to that stat) and
  *Scales with X* (has an effect that uses it), each with a result count. Selecting one clears
  the search box and adds a removable filter chip; plain text stays a substring match until you
  pick a suggestion. Stat tags are derived **programmatically** from each item's bonus dicts
  (`global/tag/spell_bonuses`) and its scaling `stats`, not from description text. *(Boundary:
  effects that add damage through bespoke handlers rather than the engine's stat-bonus system —
  e.g. Boiling Blood's `extra_damage` — are intentionally not tagged, as there's no structured
  signal to read.)*
- **Build planner** — on the Equipment tab, *＋ Build* toggles an item into a sticky build bar.
  With a component inventory it allocates your components across the build respecting the game's
  **whole-component commitment** rule (a component is spent entirely on one recipe — extra
  essences wasted, never shared between items) and marks each item ✓ craftable / ✗ short with
  per-requirement detail, the components it consumes, and any leftover components. Hovering an
  item name shows its full stat card. Persists across reloads (localStorage).
- **Components & inventory** — all 83 component items (tiers 1–3 + rares) with their on-pickup /
  on-craft effects. *＋ Add to pool* collects components into a **"My components"** inventory
  (mental model: *"I have 2 Chaos Seeds and 1 Blood Basin"*), shown as editable chips with the
  derived essence pool. The Equipment tab's *Craftable only* toggle and build planner both read
  from this inventory. Persists across reloads.
- **Spells** — all 196 player spells with level, tags, stats, descriptions, and upgrades.
- **Monsters** — the full bestiary (351 monsters across base spawns, evolutions, and the rare
  rosters), all summonable minions, and the 13 Tavern **companions**, as cards with art,
  HP/shields/resists, movement, tags, depth, and every ability and passive. Filter by
  tag/element, type (monster / summonable / companion), and text.
- **Cross-reference links** — when a spell, item, or monster references another spell, item, or
  unit, the name is a link: clicking it switches to the right tab, scrolls the entry into view,
  and flashes it. References are found **programmatically** by static-analysing each class's
  source (AST) for identifiers that are known game classes — e.g. Dread Lash's `cast()` method
  contains `SealFate`, so it links to *Seal Fate*. This avoids the false positives of matching
  names in prose (the word "Death" in "Death Bounty" is never mistaken for the Death unit).
  Summoned-unit references additionally come from the structured summon data.
- **Buff glossary tooltips** — named status effects that have no card of their own (e.g. an
  Alchemist's *Brewed Concoctions*) are surfaced as hover-only tooltips showing the buff's
  description. Buff references are found by the same AST analysis (a card's code must actually
  reference the buff class), so no prose false positives; buff terms get a dashed underline to
  distinguish them from navigable links.
- **Summon stat sheets** — any spell, item, or component that summons a unit shows the
  unit(s) as chips; hovering one pops a floating stat sheet (HP, tags, resistances,
  movement, abilities with damage/range/cooldown, and passives) for every summonable unit.

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
(`E:\SteamLibrary\steamapps\common\Rift Wizard 3`, set at the top of `extract.py` /
`copy_icons.py`) and writes only into `site/`. Update that path if your install differs.

### Live vs beta versions

The site can serve both the **live** and **beta** Steam branches with a header version
selector. `gameinfo.py` reads the installed branch/build from Steam's app manifest and
`extract.py` tags each dataset. Since the build reads one install and Steam checks out one
branch at a time, build **each branch in its own pass**:

```sh
# on the default (live) branch installed in Steam:
.venv/Scripts/python.exe build.py        # -> site/data.json  + versions.json[live]
# switch Steam to the beta branch, let it update, then:
.venv/Scripts/python.exe build.py        # -> site/data.beta.json + versions.json[beta]
```

Commit `data.json`, `data.beta.json`, `versions.json`, and `ids.json`. Each pass upserts only
its own branch (order-independent), and stable ids are a single append-only namespace shared
across branches, so Guide links keep working in whichever version has that content. The reader
switches with the header dropdown; the choice rides in the URL as a human-readable `v=beta`
(live omits it). See **ARCHITECTURE.md §17**.

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

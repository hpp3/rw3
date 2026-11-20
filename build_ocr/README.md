# build_ocr: winning builds from Discord screenshots

Reads Rift Wizard 3 end-of-run screenshots (the Discord channel where players post final
builds) and turns them into structured builds: spells with their upgrades, ordered
equipment, realm, challenge, outcome and turn counts. It replaces July's `victory_ocr.py`
(Tesseract with pixel-border detection), which mislabelled every Tome, Tavern companion
and many upgrades. On images both versions accept, July's upgrade lists match only about a
quarter of the time.

## Pipeline

| step | script | what it does |
|---|---|---|
| 0 | `har_download.py` | Chrome HAR of the channel → full-size attachment images (signed URLs expire in about 12-24 h, so run it right after capturing) |
| 0b | `image_dedupe.py` | moves byte/pixel-identical repeats to `duplicates/` |
| 1 | `vocab.py` | `vocab.json` = compendium spells/upgrades/equipment (live + beta + names from older builds in `history.json`) + Tomes, Tavern companions and Archmage Trial names read from the game source |
| 2 | `ocr_stage.py` | RapidOCR (PP-OCRv4, GPU via DirectML) → one cached JSON of text boxes per image, keyed by content hash; about 1.3 s/image |
| 3 | `parse.py` | text-anchored layout ("Spells"/"Equipment" headers, "Learn a Spell"/"Craft Equipment" terminators, "Outcome"/"Turns taken" pane) → `results.jsonl`, `summary.json`, `unmatched.tsv`; groups images of the same run |
| 4 | `evaluate.py` | accuracy against hand-read gold files and agreement with July's results |

```bash
cd build_ocr
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe rapidocr_onnxruntime pillow numpy rapidfuzz
uv pip uninstall --python .venv/Scripts/python.exe onnxruntime
uv pip install --python .venv/Scripts/python.exe onnxruntime-directml
.venv/Scripts/python.exe -I vocab.py --data ../site/data.json --data ../site/data.beta.json --history ../site/history.json --game "E:/SteamLibrary/steamapps/common/Rift Wizard 3"
.venv/Scripts/python.exe -I ocr_stage.py D:/Downloads/rw3_images D:/Downloads/rw3_images_2026-11 --cache D:/Downloads/rw3_build_ocr/cache
.venv/Scripts/python.exe -I parse.py --cache D:/Downloads/rw3_build_ocr/cache --images D:/Downloads/rw3_images D:/Downloads/rw3_images_2026-11 --out D:/Downloads/rw3_build_ocr/out
.venv/Scripts/python.exe -I evaluate.py --results D:/Downloads/rw3_build_ocr/out/results.jsonl --gold D:/Downloads/rw3_build_ocr/gold --july D:/Downloads/rw3_ocr_results/results.jsonl --out D:/Downloads/rw3_build_ocr/out/accuracy.md
```

Images, OCR cache, gold files and results live outside the repo (in `D:/Downloads/...`).

**GPU caution:** DirectML shares the GPU with whatever else is running. On 2026-11-19 a driver
reset ("GPU device instance has been suspended") happened mid-run while games were open. Use
`--cpu --threads 6 --shard i/3` (three processes, below-normal priority, about 45 min for 2,000
images) when the machine is in use. Failed images are never cached, so re-running retries them.

## Accuracy (2026-11-19 run, 2,872 images)

- **Gold set:** 22 hand-read images, stratified toward hard cases (7302 px ultrawide, 4K, Retina, 40-upgrade Wild Magic sheets, a 46-item list, cropped and in-progress sheets, map views, a non-game image). Spells 128/128, upgrades 287/287, equipment 276/276. Kind, realm, challenge, outcome and both turn counts are all correct. The score is the same whether the images are OCR'd on the GPU or with `--cpu`.
- **Near-matches:** every accepted fuzzy match below 97 was reviewed by hand; all 24 are OCR typos of the right name (e.g. "Seif Healing" -> Self Healing). Look-alikes with a clean OCR read but no close match (e.g. "Artificer's Wheel") are kept as unknown items rather than snapped.
- **July comparison:** the usable/unusable split agrees on 566 of 569. The differences:
  - two realm-21 in-progress sheets that July rejected (it accepted 19 others like them);
  - one map-only image that July accepted.
  Where both accept an image, July's upgrade lists match on only 123 of 412. Spot checks show July errors: Tomes snapped to other items, and upgrades read as spells.
- **Result:** 1,907 usable images, 1,904 unique vanilla wins (409 July + 1,495 new). 14 are flagged, 9 incomplete, and 25 are assumed wins (in-progress realm-21 sheets). Excluded: 4 demo wins (realm 20, June), 6 mid-run level clears and 2 modded runs. There are 183 non-builds; a 16-image sample of them was all genuinely non-build. 587 victory map views carry spell names only, and 289 of them have no character sheet from the same run.

## Output (`results.jsonl`, one row per image)

The fields are a superset of July's, so `../build_analysis.py` can read them. Demo wins (`demo_final_realm`) are excluded from `usable`.

- `kind`:
  - `victory_sheet`: character sheet + Outcome: VICTORY.
  - `in_progress_sheet`: character sheet, run not finished.
  - `defeat_sheet`
  - `victory_map` / `in_progress_map` / `defeat_map`: map view; spell names from the left panel only.
  - `level_clear_sheet` / `level_clear_map`: "Outcome: VICTORY" for a mid-run realm. The right pane summarises the level just finished, so only the final realm is a run win: 21, or 20 for demo-era posts before 2026-07-01, which get `demo_final_realm: true`.
  - `non_build`
- `modded`: signs of a modded run. Roguelite marks its rare variants with a leading `*`, and items that exist in neither the game nor the vocabulary come from other mods (e.g. Artificer's Wheel). These runs are not `usable`.
- `status`: `usable` for a final-realm victory sheet, or for an in-progress sheet on realm 21+ (`assumed_victory: true`, the same rule July used).
- `spells`: `[{name, upgrades, confidence, unknown_upgrades?}]` in sheet order. `unknown_upgrades` holds legible indented lines that match no known upgrade, which are usually names from June builds.
- `equipment`: `[{name, known, confidence}]` in order, repeats kept.
- `realm`, `challenge` (a trial name, `weekly_N`, `Mutated Run`, or raw text), `challenge_raw`, `outcome`, `turns_taken {local, global}`, `current_turn` (left panel), `spell_casts`.
- `warnings` include `upgrade_without_indent`, `spell_with_indent`, `foreign_upgrade`, `low_confidence_*`, `unmatched_*`, `row_gap_*` (a possibly missed line), `no_*_terminator` (a possibly cropped column) and `realm_conflict`.
- `lines`: every raw OCR line with its best spell/upgrade/equipment match and score, so nothing is snapped silently.
- `incomplete`: a column is cropped (no "Learn a Spell"/"Craft Equipment" line) or has a gap. Spells cut off the bottom are filled in from the left-panel list with `from_left_panel: true`, and their upgrades are unknown.
- `quality`: `clean` or `flagged`. `flagged` means a warning other than an old upgrade name, a split merged line, or a renamed spell inferred from its upgrades.
- `builds.jsonl`: one row per unique usable run, which is the file to analyse.
- `run_group` / `duplicate_of`: images of the same run. These are char sheet + finish map pairs posted together, or reposts. They are identified by the same global turn count plus Spell Casts, or by the same build and global turns; pairs posted within 3 s are matched by spells. Count unique runs with `status == usable and not duplicate_of`.

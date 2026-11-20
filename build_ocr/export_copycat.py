"""Export winning builds for the Copycat mod (mods/Copycat/builds.json).

    python -I export_copycat.py --builds OUT/builds.jsonl --site ../site --out <game>/mods/Copycat/builds.json [--challenge Improviser]

Each build keeps only what the winner chose themselves: the spells they learned and the
equipment they crafted. Dropped: upgrades (never shown), non-craftable gear (tomes, Tavern
companions, vault items) and forbidden spells, which come from crafting their book (the book
stays in the equipment list). Builds where a spell had 3+ upgrades are marked, with whether
the Codex of Chaotic Evolution (which grants extra upgrades) is among the crafted items.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

CODEX = "Codex of Chaotic Evolution"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", type=Path, required=True)
    ap.add_argument("--site", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--challenge", default="Improviser")
    ap.add_argument("--image-dir", action="append", default=[], help="folder(s) holding the screenshots")
    args = ap.parse_args()
    data = json.loads((args.site / "data.json").read_text(encoding="utf-8"))
    forbidden = {s["name"] for s in data["spells"] if s.get("granted_by") or s.get("forbidden")}
    craftable = {e["name"] for e in data["equipment"]}
    out = []
    for line in args.builds.read_text(encoding="utf-8").splitlines():
        b = json.loads(line)
        if (b.get("challenge") or "") != args.challenge or b.get("incomplete"):
            continue
        spells = [s["name"] for s in b["spells"] if not s.get("unknown") and s["name"] not in forbidden]
        items = [e["name"] for e in b["equipment"] if e["known"] and e["name"] in craftable]
        pushed = [s["name"] for s in b["spells"] if len(s["upgrades"]) >= 3]
        if not spells and not items:
            continue
        out.append({
            "id": b["image"].split("_", 1)[0],
            "posted": dt.datetime.fromtimestamp(b["posted"] / 1000, dt.UTC).date().isoformat(),
            "posted_ms": b["posted"],  # Discord post time (UTC epoch ms, from the attachment id)
            "image": b["image"],       # the original screenshot, looked up in image_dirs
            "spells": spells,
            "equipment": items,
            "pushed": pushed,
            "codex": CODEX in items,
        })
    out.sort(key=lambda r: r["id"])
    payload = {"challenge": args.challenge, "source": "Discord #final-builds screenshots, OCR'd by build_ocr",
               "generated": dt.date.today().isoformat(),
               "image_dirs": [str(d) for d in args.image_dir],  # where the mod finds the screenshots
               "builds": out}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} builds ({sum(1 for r in out if not r['pushed'])} with no spell past 2 upgrades) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

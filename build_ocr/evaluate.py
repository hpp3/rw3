"""Stage 3: measure parser accuracy.

    python -I evaluate.py --results OUT/results.jsonl --gold GOLD_DIR [--july D:/Downloads/rw3_ocr_results/results.jsonl] --out OUT/accuracy.md

Gold: hand-read JSON files (one per image) -> field-level precision/recall.
July: the July Codex/Tesseract results -> agreement on status (July's usable/unusable split was
corrected by hand) and on build contents where both call an image usable. Disagreements are
listed so they can be settled by looking at the image; July is a comparison, not the truth.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from rapidfuzz import fuzz


def canon(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def prf(pred: Counter, gold: Counter) -> tuple[int, int, int]:
    tp = sum((pred & gold).values())
    return tp, sum(pred.values()), sum(gold.values())


def fmt(tp, np_, ng):
    p = tp / np_ if np_ else 1.0
    r = tp / ng if ng else 1.0
    return f"precision {p:.1%} ({tp}/{np_}), recall {r:.1%} ({tp}/{ng})"


def eval_gold(results: dict, gold_dir: Path) -> list[str]:
    out = ["## Gold set (hand-read images)", ""]
    totals = {k: [0, 0, 0] for k in ("spells", "upgrades", "equipment")}
    field_ok = Counter()
    field_n = Counter()
    exact = 0
    nbuild = 0
    rows = []
    for gf in sorted(gold_dir.glob("*.json")):
        g = json.loads(gf.read_text(encoding="utf-8"))
        r = results.get(g["image"])
        if r is None:
            rows.append(f"| {g['image']} | not in results | | |")
            continue
        notes = []
        for f, gv, rv in (("kind", g["kind"], r["kind"]), ("realm", g.get("realm"), r.get("realm")),
                          ("outcome", g.get("outcome"), r.get("outcome")),
                          ("challenge", canon(g.get("challenge")), canon(r.get("challenge"))),
                          ("turns_local", g.get("turns_local"), (r.get("turns_taken") or {}).get("local")),
                          ("turns_global", g.get("turns_global"), (r.get("turns_taken") or {}).get("global"))):
            if f != "kind" and not g["kind"].endswith("sheet") and not g["kind"].endswith("map"):
                continue
            field_n[f] += 1
            if gv == rv or (f == "challenge" and gv and rv and fuzz.ratio(gv, rv) >= 90):
                field_ok[f] += 1
            else:
                notes.append(f"{f}: gold={gv!r} got={rv!r}")
        if g["kind"].endswith("_sheet") and r["kind"].endswith("_sheet"):
            nbuild += 1
            gs = Counter(canon(s["name"]) for s in g["spells"])
            rs = Counter(canon(s["name"]) for s in r.get("spells") or [])
            gu = Counter((canon(s["name"]), canon(u)) for s in g["spells"] for u in s.get("upgrades") or [] if u != "?")
            ru = Counter((canon(s["name"]), canon(u)) for s in r.get("spells") or [] for u in s.get("upgrades") or [])
            ge = Counter(canon(e) for e in g.get("equipment") or [] if e != "?")
            re_ = Counter(canon(e["name"]) for e in r.get("equipment") or [])
            for key, pc, gc in (("spells", rs, gs), ("upgrades", ru, gu), ("equipment", re_, ge)):
                tp, np_, ng = prf(pc, gc)
                for i, v in enumerate((tp, np_, ng)):
                    totals[key][i] += v
                if pc != gc:
                    miss = list((gc - pc).elements())
                    extra = list((pc - gc).elements())
                    notes.append(f"{key}: missed {miss} extra {extra}")
            if gs == rs and gu == ru and ge == re_:
                exact += 1
        rows.append(f"| {g['image']} | {g['kind']} | {r['kind']} | {'; '.join(notes) or 'all correct'} |")
    out.append(f"Character sheets compared: {nbuild}; builds read exactly right (every spell, upgrade, item): {exact}")
    out.append("")
    for key, (tp, np_, ng) in totals.items():
        out.append(f"- {key}: {fmt(tp, np_, ng)}")
    for f in ("kind", "realm", "outcome", "challenge", "turns_local", "turns_global"):
        if field_n[f]:
            out.append(f"- {f}: {field_ok[f]}/{field_n[f]} correct")
    out += ["", "| image | gold kind | parsed kind | differences |", "|---|---|---|---|"] + rows + [""]
    return out


def eval_july(results: dict, july_path: Path) -> list[str]:
    july = {}
    for line in july_path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        july[r["image"]] = r
    out = ["## Comparison with the July (Codex/Tesseract) results", ""]
    m = Counter()
    flips = {"july_usable_now_not": [], "july_unusable_now_usable": []}
    for name, j in july.items():
        r = results.get(name)
        if r is None:
            m["missing"] += 1
            continue
        m[(j["status"], r["status"])] += 1
        if j["status"] == "usable" and r["status"] != "usable":
            flips["july_usable_now_not"].append(f"{name} -> {r['kind']} ({r.get('reason')})")
        if j["status"] != "usable" and r["status"] == "usable":
            flips["july_unusable_now_usable"].append(f"{name} -> {r['kind']}")
    out.append("Status agreement (July status -> new status):")
    for k, v in sorted(m.items(), key=lambda kv: str(kv[0])):
        out.append(f"- {k}: {v}")
    for k, v in flips.items():
        out.append(f"\n{k} ({len(v)}):")
        out += [f"- {x}" for x in v[:60]]
    # content agreement where both usable
    agree = Counter()
    diffs = []
    for name, j in july.items():
        r = results.get(name)
        if not r or j["status"] != "usable" or r["status"] != "usable":
            continue
        js = {canon(s["name"]) for s in j["spells"]}
        rs = {canon(s["name"]) for s in r.get("spells") or []}
        ju = {(canon(s["name"]), canon(u)) for s in j["spells"] for u in s["upgrades"]}
        ru = {(canon(s["name"]), canon(u)) for s in r.get("spells") or [] for u in s.get("upgrades") or []}
        je = Counter(canon(e["name"]) for e in j["equipment"])
        re_ = Counter(canon(e["name"]) for e in r.get("equipment") or [])
        agree["both_usable"] += 1
        agree["spells_same"] += js == rs
        agree["upgrades_same"] += ju == ru
        agree["equipment_same"] += je == re_
        agree["all_same"] += js == rs and ju == ru and je == re_
        if not (js == rs and ju == ru and je == re_):
            diffs.append((name, sorted(js ^ rs), sorted(ju ^ ru), sorted((je - re_).elements()), sorted((re_ - je).elements())))
    out += ["", f"Where both call the image usable ({agree['both_usable']}): spells identical {agree['spells_same']}, "
            f"upgrades identical {agree['upgrades_same']}, equipment identical {agree['equipment_same']}, everything identical {agree['all_same']}", ""]
    out.append("Content disagreements (spell symmetric diff | upgrade symmetric diff | equipment only in July | only in new):")
    for d in diffs[:80]:
        out.append(f"- {d[0]}: {d[1]} | {d[2]} | {d[3]} | {d[4]}")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--gold", type=Path)
    ap.add_argument("--july", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    results = {}
    for line in args.results.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        results[r["image"]] = r
    report = ["# Build OCR accuracy", ""]
    if args.gold:
        report += eval_gold(results, args.gold)
    if args.july:
        report += eval_july(results, args.july)
    args.out.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

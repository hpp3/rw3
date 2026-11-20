"""Dedupe a new image batch against older batches.

Usage: python -I dedupe.py NEW_DIR OLD_DIR [OLD_DIR ...] [--cache FILE] [--apply] [--review N]

Exact duplicates (same bytes, or same decoded pixels) are moved to NEW_DIR/duplicates/
with --apply; anything matching an old file loses, and inside the new batch the earliest
attachment ID wins. Near-duplicates (same picture re-encoded / resized / slightly cropped)
are only reported, with side-by-side sheets for the closest N pairs, never moved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

EXTS = {".webp", ".png", ".jpg", ".jpeg"}
SKIP_DIRS = {"duplicates", "dedupe_review", "har_preview"}
THUMB = (96, 54)


def sort_key(p: Path):
    head = p.name.split("_", 1)[0]
    return (int(head) if head.isdigit() else 0, p.name)


def images_in(root: Path) -> list[Path]:
    out = [p for p in root.rglob("*") if p.suffix.lower() in EXTS and p.is_file()
           and not (SKIP_DIRS & set(p.relative_to(root).parts[:-1]))]
    return sorted(out, key=sort_key)


def describe(path_str: str) -> dict:
    path = Path(path_str)
    data = path.read_bytes()
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    gray = rgb.convert("L")
    g = np.asarray(gray.resize((17, 16), Image.BILINEAR), dtype=np.int16)
    return {
        "path": path_str,
        "size": rgb.size,
        "sha": hashlib.sha256(data).hexdigest(),
        "pix": hashlib.sha256(rgb.tobytes() + repr(rgb.size).encode()).hexdigest(),
        "dhash": np.packbits((g[:, 1:] > g[:, :-1]).flatten()).view(np.uint64),
        "thumb": np.asarray(gray.resize(THUMB, Image.BILINEAR), dtype=np.uint8),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("new", type=Path)
    ap.add_argument("old", type=Path, nargs="+")
    ap.add_argument("--cache", type=Path, default=Path("dedupe_cache.pkl"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--review", type=int, default=40, help="side-by-side sheets for the N closest near-duplicate pairs")
    ap.add_argument("--mad", type=float, default=6.0, help="max mean abs grey difference (0-255) on a 96x54 thumbnail to call a near-duplicate")
    args = ap.parse_args()

    cache: dict[str, dict] = pickle.loads(args.cache.read_bytes()) if args.cache.exists() else {}
    old_paths = [p for d in args.old for p in images_in(d)]
    new_paths = images_in(args.new)
    todo = [str(p) for p in old_paths + new_paths if str(p) not in cache]
    print(f"old files: {len(old_paths)}  new files: {len(new_paths)}  to hash: {len(todo)}", flush=True)
    with ProcessPoolExecutor(max_workers=12) as pool:
        for i, d in enumerate(pool.map(describe, todo, chunksize=8), 1):
            cache[d["path"]] = d
            if i % 500 == 0:
                print(f"  hashed {i}/{len(todo)}", flush=True)
    args.cache.write_bytes(pickle.dumps(cache))
    old = [cache[str(p)] for p in old_paths]
    new = [cache[str(p)] for p in new_paths]

    widths = Counter(d["size"][0] for d in new)
    print("new widths (top):", widths.most_common(6), " narrower than 700px:", sum(1 for d in new if d["size"][0] < 700), flush=True)

    # exact duplicates
    seen: dict[str, str] = {}
    for d in old:
        seen.setdefault(d["sha"], d["path"]); seen.setdefault(d["pix"], d["path"])
    exact, keep = [], []
    for d in new:
        hit = seen.get(d["sha"]) or seen.get(d["pix"])
        if hit:
            exact.append({"duplicate": d["path"], "of": hit, "kind": "bytes" if d["sha"] in seen else "pixels",
                          "of_batch": "new" if hit.startswith(str(args.new)) else "old"})
        else:
            keep.append(d)
            seen.setdefault(d["sha"], d["path"]); seen.setdefault(d["pix"], d["path"])
    print(f"exact duplicates: {len(exact)}  (of an old image: {sum(e['of_batch'] == 'old' for e in exact)}, within new batch: {sum(e['of_batch'] == 'new' for e in exact)})", flush=True)

    # near duplicates: compare thumbnails (aspect-normalised) of each kept new image vs old + earlier kept
    pool = old + keep
    T = np.stack([d["thumb"].astype(np.float32).ravel() for d in pool])
    aspect = np.array([d["size"][0] / d["size"][1] for d in pool])
    n_old = len(old)
    near = []
    dist_hist = Counter()
    for i in range(n_old, len(pool)):
        mad = np.abs(T[:i] - T[i]).mean(axis=1)
        ok = np.abs(aspect[:i] - aspect[i]) < 0.05
        j = int(np.argmin(np.where(ok, mad, 1e9))) if i else -1
        if j >= 0 and ok[j]:
            dist_hist[min(int(mad[j]), 30)] += 1
            if mad[j] <= args.mad:
                near.append({"new": pool[i]["path"], "match": pool[j]["path"], "mad": round(float(mad[j]), 2),
                             "match_batch": "old" if j < n_old else "new", "sizes": [pool[i]["size"], pool[j]["size"]]})
    near.sort(key=lambda r: r["mad"])
    print("nearest-neighbour MAD histogram (bucket: count):", dict(sorted(dist_hist.items())), flush=True)
    print(f"near-duplicate candidates (MAD <= {args.mad}): {len(near)}  (vs old: {sum(r['match_batch'] == 'old' for r in near)})", flush=True)
    for r in near[:60]:
        print(f"  mad={r['mad']:5.2f}  {Path(r['new']).name}  ~  [{r['match_batch']}] {Path(r['match']).name}", flush=True)

    review = args.new / "dedupe_review"
    if near and args.review:
        review.mkdir(exist_ok=True)
        for k, r in enumerate(near[:args.review]):
            a, b = Image.open(r["new"]).convert("RGB"), Image.open(r["match"]).convert("RGB")
            h = 540
            a = a.resize((max(1, a.width * h // a.height), h)); b = b.resize((max(1, b.width * h // b.height), h))
            sheet = Image.new("RGB", (a.width + b.width + 10, h), "white")
            sheet.paste(a, (0, 0)); sheet.paste(b, (a.width + 10, 0))
            sheet.save(review / f"{k:03d}_mad{r['mad']}_{Path(r['new']).stem[:40]}.jpg", quality=80)

    report = {"old_files": len(old), "new_files": len(new), "exact_duplicates": exact, "near_candidates": near, "applied": args.apply}
    (args.new / "dedupe_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.apply and exact:
        dup_dir = args.new / "duplicates"
        dup_dir.mkdir(exist_ok=True)
        for e in exact:
            shutil.move(e["duplicate"], dup_dir / Path(e["duplicate"]).name)
        print(f"moved {len(exact)} exact duplicates to {dup_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

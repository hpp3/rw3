"""Stage 1: run RapidOCR over screenshots and cache the raw text boxes.

    python -I ocr_stage.py IMAGE_DIR [IMAGE_DIR ...] --cache CACHE_DIR [--limit N] [--force]

One JSON file per image content (sha256 prefix), so parser changes never need a re-OCR and
renamed/moved images reuse their cache. Boxes are stored in original image pixels.
Uses DirectML (GPU) when onnxruntime-directml is installed; falls back to CPU otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

EXTS = {".webp", ".png", ".jpg", ".jpeg", ".bmp", ".gif"}
SKIP_DIRS = {"duplicates", "dedupe_review", "har_preview"}
TARGET_MIN_HEIGHT = 1080   # upscale smaller screenshots so the game font is ~20px tall
SMALL_TEXT_PX = 17          # second pass at 2x when the median line box is shorter than this
MAX_PIXELS = 40_000_000


def iter_images(dirs: list[Path]) -> list[Path]:
    out = []
    for root in dirs:
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() in EXTS and p.is_file() and not (SKIP_DIRS & set(p.relative_to(root).parts[:-1])):
                out.append(p)
    return out


USE_GPU = True
CPU_THREADS = -1


def make_engine():
    from rapidocr_onnxruntime import RapidOCR
    import onnxruntime
    gpu = USE_GPU and "DmlExecutionProvider" in onnxruntime.get_available_providers()
    kw = dict(use_cls=False, text_score=0.3, max_side_len=10000, min_height=30)
    if gpu:
        kw.update(det_use_dml=True, rec_use_dml=True)
    else:
        kw.update(det_use_dml=False, rec_use_dml=False, intra_op_num_threads=CPU_THREADS)
    return RapidOCR(**kw), gpu


def lower_priority() -> None:
    """Below-normal CPU priority so games and the desktop stay responsive (Windows only)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:  # noqa: BLE001
        pass


def run(engine, img: Image.Image, scale: float) -> list[dict]:
    if scale != 1.0:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    arr = np.asarray(img)[:, :, ::-1]  # RapidOCR expects BGR arrays
    res, _ = engine(arr, use_cls=False, text_score=0.3, box_thresh=0.45, unclip_ratio=1.6)
    boxes = []
    for quad, text, conf in res or []:
        xs = [pt[0] for pt in quad]
        ys = [pt[1] for pt in quad]
        boxes.append({
            "box": [round(min(xs) / scale, 1), round(min(ys) / scale, 1), round(max(xs) / scale, 1), round(max(ys) / scale, 1)],
            "text": text,
            "score": round(float(conf), 3),
        })
    return boxes


def ocr_image(engine, path: Path) -> dict:
    with Image.open(path) as im:
        img = im.convert("RGB")
    w, h = img.size
    scale = 1.0
    if h < TARGET_MIN_HEIGHT:
        scale = min(TARGET_MIN_HEIGHT / h, 3.0)
    passes = [scale]
    boxes = run(engine, img, scale)
    heights = [(b["box"][3] - b["box"][1]) * scale for b in boxes]
    med = statistics.median(heights) if heights else 0
    if boxes and med < SMALL_TEXT_PX and (w * h * (scale * 2) ** 2) <= MAX_PIXELS:
        scale2 = scale * 2
        boxes2 = run(engine, img, scale2)
        passes.append(scale2)
        if len(boxes2) >= len(boxes) * 0.8:
            boxes = boxes2
    return {"size": [w, h], "passes": passes, "median_box_h": round(med / scale, 1) if med else 0, "boxes": boxes}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", type=Path, nargs="+")
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", help="only these file names")
    ap.add_argument("--cpu", action="store_true", help="don't use the GPU (safer while games are running: a DirectML job can trigger a driver reset)")
    ap.add_argument("--threads", type=int, default=-1, help="CPU threads per process with --cpu")
    ap.add_argument("--shard", default="0/1", help="i/n: process every n-th image starting at i (run n processes in parallel)")
    args = ap.parse_args()

    global USE_GPU, CPU_THREADS
    USE_GPU, CPU_THREADS = not args.cpu, args.threads
    lower_priority()
    args.cache.mkdir(parents=True, exist_ok=True)
    paths = iter_images(args.dirs)
    shard_i, shard_n = (int(x) for x in args.shard.split("/"))
    paths = paths[shard_i::shard_n]
    if args.only:
        wanted = set(args.only)
        paths = [p for p in paths if p.name in wanted]
    if args.limit:
        paths = paths[: args.limit]
    engine, gpu = make_engine()
    print(f"{len(paths)} images, GPU={gpu}", flush=True)
    t0 = time.time()
    done = 0
    failures_in_a_row = 0
    for i, path in enumerate(paths, 1):
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        out = args.cache / f"{sha[:20]}.json"
        if out.exists() and not args.force:
            if '"error"' not in out.read_text(encoding="utf-8")[:200]:
                continue  # cached; earlier error records are retried
        rec = None
        for attempt in range(2):
            try:
                rec = ocr_image(engine, path)
                failures_in_a_row = 0
                break
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                # a GPU driver reset ("device instance has been suspended") poisons the DirectML
                # session: rebuild the engine once, and never cache the failure
                print(f"  OCR failed on {path.name} (attempt {attempt + 1}): {msg.splitlines()[-1][:160]}", flush=True)
                engine, gpu = make_engine()
        if rec is None:
            failures_in_a_row += 1
            if failures_in_a_row >= 5:
                print("5 images in a row failed even after rebuilding the engine; stopping", flush=True)
                return 1
            continue
        rec.update({"image": path.name, "sha256": sha})
        out.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        done += 1
        if done % 100 == 0:
            rate = (time.time() - t0) / done
            print(f"  {i}/{len(paths)} ocr'd {done} ({rate:.2f}s/img)", flush=True)
    print(f"done: {done} new OCR results in {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

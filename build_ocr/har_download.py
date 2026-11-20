"""Download full-size Discord attachment images harvested from a Chrome HAR.

Usage: python -I har_download.py HAR OUT_DIR --channel ID [--skip-manifest OLD_MANIFEST ...] [--workers N]

- keeps only media.discordapp.net/attachments/<channel>/ image requests (no avatars/emoji)
- strips width/height to get the full-size rendition (same as the July run)
- skips attachment IDs already listed in any --skip-manifest
- writes <id>_<stem>.webp, download_manifest.json, full_size_urls.txt
- if a full-size fetch fails, saves the HAR's embedded (resized) body to har_preview/
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def full_size(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("width", "height")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, safe=""), ""))


def file_name(att_id: str, path: str) -> str:
    stem = Path(path.rsplit("/", 1)[-1]).stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)[:80] or "image"
    return f"{att_id}_{stem}.webp"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("har", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--channel", required=True)
    ap.add_argument("--skip-manifest", type=Path, action="append", default=[])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    skip: set[str] = set()
    for m in args.skip_manifest:
        for row in json.loads(m.read_text(encoding="utf-8-sig")):
            skip.add(row["FileName"].split("_", 1)[0])

    har = json.loads(args.har.read_text(encoding="utf-8"))
    prefix = f"https://media.discordapp.net/attachments/{args.channel}/"
    by_id: dict[str, dict] = {}
    for e in har["log"]["entries"]:
        url = e["request"]["url"]
        if not url.startswith(prefix) or not e["response"]["content"].get("mimeType", "").startswith("image/"):
            continue
        att_id = urlsplit(url).path.strip("/").split("/")[2]
        content = e["response"]["content"]
        prev = by_id.get(att_id)
        # keep the largest embedded preview as the fallback body
        if prev is None or content.get("size", 0) > prev["preview_size"]:
            by_id[att_id] = {
                "id": att_id,
                "url": full_size(url),
                "name": file_name(att_id, urlsplit(url).path),
                "preview": content.get("text"),
                "preview_encoding": content.get("encoding"),
                "preview_size": content.get("size", 0),
            }
    todo = [v for k, v in sorted(by_id.items(), key=lambda kv: int(kv[0])) if k not in skip]
    print(f"{len(by_id)} attachment images in HAR, {len(by_id) - len(todo)} skipped (already downloaded), {len(todo)} to fetch", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "full_size_urls.txt").write_text("\n".join(t["url"] for t in todo) + "\n", encoding="utf-8")
    preview_dir = args.out / "har_preview"
    lock = threading.Lock()
    done = [0]

    def fetch(t: dict) -> dict:
        dest = args.out / t["name"]
        row = {"Id": t["id"], "Url": t["url"], "FileName": t["name"], "Path": str(dest), "Status": "", "Bytes": 0, "Sha256": "", "Error": ""}
        if dest.exists() and dest.stat().st_size > 0:
            data = dest.read_bytes()
            row.update(Status="already_present", Bytes=len(data), Sha256=hashlib.sha256(data).hexdigest())
            return row
        last = ""
        for attempt in range(4):
            try:
                req = urllib.request.Request(t["url"], headers={"User-Agent": UA, "Accept": "image/webp,image/*,*/*"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    data = resp.read()
                if not ctype.startswith("image/") or not data:
                    raise ValueError(f"unexpected content-type {ctype!r} ({len(data)} bytes)")
                part = dest.with_suffix(".part")
                part.write_bytes(data)
                part.replace(dest)
                row.update(Status="downloaded", Bytes=len(data), Sha256=hashlib.sha256(data).hexdigest())
                return row
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code in (403, 404):
                    break
                time.sleep(2 * (attempt + 1) + (5 if exc.code == 429 else 0))
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(2 * (attempt + 1))
        row["Error"] = last
        if t["preview"]:
            preview_dir.mkdir(exist_ok=True)
            body = base64.b64decode(t["preview"]) if t["preview_encoding"] == "base64" else t["preview"].encode("latin-1")
            (preview_dir / t["name"]).write_bytes(body)
            row["Status"] = "failed_preview_saved"
        else:
            row["Status"] = "failed"
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed([pool.submit(fetch, t) for t in todo]):
            row = fut.result()
            with lock:
                rows.append(row)
                done[0] += 1
                if done[0] % 100 == 0 or row["Status"].startswith("failed"):
                    print(f"{done[0]}/{len(todo)} {row['Status']} {row['FileName']} {row['Error']}", flush=True)
    rows.sort(key=lambda r: int(r["Id"]))
    (args.out / "download_manifest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["Status"]] = counts.get(r["Status"], 0) + 1
    total = sum(r["Bytes"] for r in rows)
    print(f"done: {counts}, {total / 2**20:.1f} MiB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

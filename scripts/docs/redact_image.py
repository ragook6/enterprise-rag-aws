#!/usr/bin/env python3
"""
Irreversible screenshot redaction: raw captures (git-ignored) -> sanitized PNGs for the public repo.

    .venv/bin/python scripts/docs/redact_image.py --spec screenshots-raw/redactions.json

Spec (lives next to the raw files, git-ignored):
    {"03-s3-documents-bucket.png": {"crop": [0, 90, 1920, 1080],      # optional, applied first
                                    "boxes": [[40, 210, 620, 240]],   # filled solid, after crop
                                    "reviewed_by": "", "notes": ""},
     "04-detail.png": {"source": "full.png", "crop": [...]}}           # optional "source" raw file
How it is irreversible:
  1. crop removes pixels entirely (prefer cropping out the console header / account menu);
  2. boxes overwrite pixel values with a solid color (no overlay, no layers, no transparency);
  3. the image is rebuilt from raw RGB bytes and re-encoded as a NEW PNG with no metadata
     (EXIF/XMP/text chunks/ICC dropped), so nothing from the original file container survives.
The raw file is never modified. Output: docs/images/aws/<name>.png + docs/images/aws/MANIFEST.json.
Manual review of every output image is still required (no OCR is installed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
FILL = (31, 31, 31)


def redact(src: Path, dst: Path, crop=None, boxes=(), max_width: int | None = 1600) -> dict:
    raw_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    with Image.open(src) as im:
        rgb = im.convert("RGB")                       # drops alpha/palette; flatten
    if crop:
        rgb = rgb.crop(tuple(crop))
    draw = ImageDraw.Draw(rgb)
    for b in boxes:
        draw.rectangle(tuple(b), fill=FILL)           # overwrite pixels
    for b in boxes:                                    # verify the fill at full resolution, before any resize
        x0, y0, x1, y1 = b
        if len(set(rgb.crop((x0, y0, x1 + 1, y1 + 1)).get_flattened_data())) != 1:
            raise RuntimeError(f"{src.name}: box {b} is not a uniform fill")
    if max_width and rgb.width > max_width:
        rgb = rgb.resize((max_width, round(rgb.height * max_width / rgb.width)), Image.LANCZOS)
    clean = Image.frombytes("RGB", rgb.size, rgb.tobytes())   # fresh image: no info/exif/icc carried over
    dst.parent.mkdir(parents=True, exist_ok=True)
    clean.save(dst, format="PNG", optimize=True)
    if hashlib.sha256(src.read_bytes()).hexdigest() != raw_hash:
        raise RuntimeError(f"raw file changed: {src}")
    verify(dst)
    return {"output": str(dst.relative_to(ROOT)) if dst.is_relative_to(ROOT) else str(dst),
            "output_sha256": hashlib.sha256(dst.read_bytes()).hexdigest(), "size": list(clean.size),
            "boxes": len(boxes), "cropped": bool(crop)}


def verify(path: Path) -> None:
    """The published file must carry no metadata and be plain RGB."""
    with Image.open(path) as im:
        meta = {k: v for k, v in im.info.items() if k not in ("dpi",)}
        if meta or im.getexif():
            raise RuntimeError(f"{path}: metadata present: {list(meta)}")
        if im.mode != "RGB":
            raise RuntimeError(f"{path}: unexpected mode {im.mode}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--raw-dir", default=str(ROOT / "screenshots-raw"))
    ap.add_argument("--out-dir", default=str(ROOT / "docs" / "images" / "aws"))
    args = ap.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text())
    manifest = {}
    for name, s in sorted(spec.items()):
        src = Path(args.raw_dir) / s.get("source", name)   # optional: several outputs cut from one raw capture
        if not src.is_file():
            print(f"skip {name}: raw file not found")
            continue
        info = redact(src, Path(args.out_dir) / name, s.get("crop"), s.get("boxes", []))
        info["manual_review"] = (f"reviewed by: {s['reviewed_by']}" if s.get("reviewed_by")
                                 else "PENDING - review the output image before publishing")
        manifest[name] = info
        print(f"redacted {name}: {info['boxes']} box(es), cropped={info['cropped']}, review={info['manual_review']}")
    (Path(args.out_dir) / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

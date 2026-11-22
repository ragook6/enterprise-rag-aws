"""Irreversible screenshot redaction (scripts/docs/redact_image.py). Synthetic images only; no AWS."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "docs"))
import redact_image as ri  # noqa: E402

SECRET = (255, 0, 128)   # distinctive color standing in for sensitive text


def make_raw(path: Path):
    im = Image.new("RGBA", (800, 400), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 800, 50), fill=(35, 47, 62, 255))            # "console header" with account menu
    d.rectangle((650, 10, 790, 40), fill=SECRET + (255,))            # account menu
    d.rectangle((100, 200, 400, 230), fill=SECRET + (255,))          # bucket name in the body
    d.text((110, 205), "111122223333", fill=(0, 0, 0, 255))
    meta = PngInfo(); meta.add_text("Comment", "account 111122223333 user someone")
    im.save(path, pnginfo=meta)


class RedactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.raw = self.tmp / "raw" / "03-test.png"; self.raw.parent.mkdir()
        make_raw(self.raw)
        self.raw_hash = hashlib.sha256(self.raw.read_bytes()).hexdigest()

    def test_crop_fill_strip_metadata(self):
        out = self.tmp / "out" / "03-test.png"
        info = ri.redact(self.raw, out, crop=[0, 50, 800, 400], boxes=[[100, 150, 400, 180]], max_width=None)
        with Image.open(out) as im:
            self.assertEqual(im.size, (800, 350))                        # header removed by crop
            self.assertEqual(im.mode, "RGB")
            self.assertNotIn("Comment", im.info)                         # text chunk gone
            self.assertEqual(dict(im.getexif()), {})
            self.assertNotIn(SECRET, set(im.getdata()))                  # no secret pixels anywhere
            self.assertEqual(set(im.crop((100, 150, 401, 181)).getdata()), {ri.FILL})
        self.assertNotIn(b"111122223333", out.read_bytes())               # not even in the file bytes
        self.assertEqual(hashlib.sha256(self.raw.read_bytes()).hexdigest(), self.raw_hash)  # raw untouched
        self.assertEqual(info["boxes"], 1); self.assertTrue(info["cropped"])

    def test_resize_keeps_redaction(self):
        out = self.tmp / "out" / "small.png"
        ri.redact(self.raw, out, crop=[0, 50, 800, 400], boxes=[[90, 140, 410, 190]], max_width=400)
        with Image.open(out) as im:
            self.assertEqual(im.width, 400)
            self.assertNotIn(SECRET, set(im.getdata()))

    def test_cli_manifest_marks_unreviewed_images_pending(self):
        spec = self.tmp / "raw" / "redactions.json"
        spec.write_text(json.dumps({"03-test.png": {"crop": [0, 50, 800, 400], "boxes": [[100, 150, 400, 180]]},
                                    "99-missing.png": {}}))
        out_dir = self.tmp / "public"
        ri.main(["--spec", str(spec), "--raw-dir", str(self.raw.parent), "--out-dir", str(out_dir)])
        manifest = json.loads((out_dir / "MANIFEST.json").read_text())
        self.assertEqual(list(manifest), ["03-test.png"])
        self.assertTrue(manifest["03-test.png"]["manual_review"].startswith("PENDING"))

    def test_verify_rejects_metadata(self):
        bad = self.tmp / "bad.png"
        meta = PngInfo(); meta.add_text("Author", "x")
        Image.new("RGB", (10, 10)).save(bad, pnginfo=meta)
        with self.assertRaises(RuntimeError):
            ri.verify(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)

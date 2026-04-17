"""Generate the multi-platform app icons from frontend/public/logo512.png.

Run once (locally or in CI) to regenerate:

    python assets/icons/_generate_icons.py

Produces:
    assets/icons/cursor-view.png   (512x512, Linux)
    assets/icons/cursor-view.ico   (multi-size, Windows)
    assets/icons/cursor-view.icns  (multi-size, macOS)
"""

from __future__ import annotations

import pathlib

from PIL import Image

try:
    import icnsutil
except ImportError:
    icnsutil = None

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "frontend" / "public" / "logo512.png"
OUT_DIR = REPO_ROOT / "assets" / "icons"

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

ICNS_KEYS: list[tuple[str, int]] = [
    ("icp4", 16),
    ("icp5", 32),
    ("icp6", 64),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),
]


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Source image not found: {SOURCE}")

    img = Image.open(SOURCE).convert("RGBA")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    png_path = OUT_DIR / "cursor-view.png"
    img.resize((512, 512), Image.LANCZOS).save(png_path, format="PNG")
    print(f"wrote {png_path}")

    ico_path = OUT_DIR / "cursor-view.ico"
    img.save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )
    print(f"wrote {ico_path}")

    icns_path = OUT_DIR / "cursor-view.icns"
    if icnsutil is None:
        print(f"skipping {icns_path}: install icnsutil to generate .icns")
        return

    icns = icnsutil.IcnsFile()
    for key, size in ICNS_KEYS:
        resized = img.resize((size, size), Image.LANCZOS)
        tmp = OUT_DIR / f"_tmp_{key}.png"
        resized.save(tmp, format="PNG")
        try:
            icns.add_media(key, file=str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
    icns.write(str(icns_path))
    print(f"wrote {icns_path}")


if __name__ == "__main__":
    main()

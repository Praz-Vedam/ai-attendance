#!/usr/bin/env python3
"""Create a placeholder JPEG for upload load tests.

For mark-attendance verification tests, replace fixtures/sample.jpg with a real
face photo that matches a registered student embedding.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
OUTPUT = FIXTURES_DIR / "sample.jpg"


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    # Small RGB image — exercises multipart upload; ML may return "no face detected".
    image = Image.new("RGB", (320, 240), color=(180, 160, 140))
    image.save(OUTPUT, format="JPEG", quality=85)
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

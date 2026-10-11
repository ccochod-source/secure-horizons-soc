#!/usr/bin/env python3
"""Exporte le modèle procédural en GLB via la page /castle (GLTFExporter dans le navigateur).

Usage : python3 scripts/castle/export_glb.py [--url http://127.0.0.1:3100/castle] [--out public/castle/castle.glb]
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:3100/castle?src=procedural")
    ap.add_argument("--out", default=str(ROOT / "public" / "castle" / "castle.glb"))
    args = ap.parse_args()
    out = Path(args.out)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        page.goto(args.url, wait_until="networkidle", timeout=120_000)
        page.wait_for_function('typeof window.__castleExport === "function"', timeout=60_000)
        page.wait_for_timeout(2000)
        with page.expect_download(timeout=120_000) as dl:
            page.evaluate("window.__castleExport()")
        dl.value.save_as(str(out))
        browser.close()
    print(f"{out} : {out.stat().st_size / 1e6:.2f} Mo")


if __name__ == "__main__":
    main()

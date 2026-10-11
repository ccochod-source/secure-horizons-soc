#!/usr/bin/env python3
"""Capture la page /castle/model-check (Playwright) et compare chaque rendu à son image de référence.

Usage :
  python3 scripts/castle/capture.py [--url URL] [--query "elev=7&fov=13"] [--out DIR]

Produit, dans DIR (défaut .runtime/castle-check) : render_<vue>.png, compare_<vue>.png
(référence | rendu | fusion 50 % | masque : blanc = commun, rouge = référence seule, bleu = rendu seul)
et compare_all.png. Affiche l'IoU des silhouettes (objet vs fond) par vue.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
VIEWS = ["top", "front", "back", "left", "right"]


def silhouette(img: Image.Image, tol: int = 28) -> np.ndarray:
    """Masque des pixels qui diffèrent de la couleur de fond (médiane des bords)."""
    a = np.asarray(img.convert("RGB")).astype(int)
    edges = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    bg = np.median(edges, axis=0)
    return np.abs(a - bg).max(axis=2) > tol


def bbox(m: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(m)
    return (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())) if len(xs) else (0, 0, 0, 0)


def bbox_stats(m_ref: np.ndarray, m_r: np.ndarray) -> dict[str, float]:
    """Écarts de boîte englobante rendu/référence : rapport de largeur/hauteur et décalage du centre (fraction de l'image)."""
    (x0, x1, y0, y1), (u0, u1, v0, v1) = bbox(m_ref), bbox(m_r)
    h, w = m_ref.shape
    return {
        "width_ratio": round((u1 - u0) / max(1, x1 - x0), 3),
        "height_ratio": round((v1 - v0) / max(1, y1 - y0), 3),
        "dx": round(((u0 + u1) - (x0 + x1)) / 2 / w, 3),
        "dy": round(((v0 + v1) - (y0 + y1)) / 2 / h, 3),
    }


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 0.0


def labelled(img: Image.Image, text: str) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, 7 * len(text) + 10, 16], fill=(20, 20, 20))
    d.text((5, 2), text, fill=(255, 255, 255))
    return out


def mask_image(m_ref: np.ndarray, m_r: np.ndarray) -> Image.Image:
    h, w = m_ref.shape
    rgb = np.full((h, w, 3), 214, dtype=np.uint8)
    rgb[m_ref & m_r] = (255, 255, 255)
    rgb[m_ref & ~m_r] = (220, 60, 50)
    rgb[~m_ref & m_r] = (50, 90, 220)
    return Image.fromarray(rgb)


def capture(url: str, out: Path, timeout: int) -> dict[str, Image.Image]:
    renders: dict[str, Image.Image] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=1)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url, wait_until="networkidle", timeout=timeout)
        try:
            page.wait_for_selector('main[data-ready-count="5"]', timeout=timeout)
        except Exception:
            page.screenshot(path=str(out / "page_timeout.png"), full_page=True)
            print("Rendus non prêts. Erreurs page :", errors, file=sys.stderr)
            raise
        page.wait_for_timeout(1500)
        for v in VIEWS:
            path = out / f"render_{v}.png"
            page.locator(f'[data-view="{v}"] canvas').screenshot(path=str(path))
            img = Image.open(path).convert("RGB")
            # la capture d'élément peut inclure 1 px de page sur un bord : on rogne 2 px partout
            img = img.crop((2, 2, img.width - 2, img.height - 2))
            img.save(path)
            renders[v] = img
        if errors:
            print("Erreurs JS :", errors, file=sys.stderr)
        browser.close()
    return renders


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:3100/castle/model-check")
    ap.add_argument("--query", default="")
    ap.add_argument("--out", default=str(ROOT / ".runtime" / "castle-check"))
    ap.add_argument("--timeout", type=int, default=120_000)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    url = args.url + (("?" + args.query) if args.query else "")
    renders = capture(url, out, args.timeout)

    rows: list[Image.Image] = []
    scores: dict[str, float] = {}
    stats: dict[str, dict[str, float]] = {}
    for v in VIEWS:
        r = renders[v]
        ref = Image.open(ROOT / "public" / "castle" / f"{v}.jpg").convert("RGB").resize(r.size, Image.LANCZOS)
        m_ref, m_r = silhouette(ref), silhouette(r)
        scores[v] = round(iou(m_ref, m_r), 3)
        stats[v] = bbox_stats(m_ref, m_r)
        cells = [labelled(ref, f"{v} reference"), labelled(r, f"{v} rendu"), labelled(Image.blend(ref, r, 0.5), "fusion"), labelled(mask_image(m_ref, m_r), f"IoU {scores[v]:.3f}")]
        row = Image.new("RGB", (sum(c.width for c in cells) + 6 * (len(cells) - 1), r.height), (244, 243, 239))
        x = 0
        for c in cells:
            row.paste(c, (x, 0))
            x += c.width + 6
        row.save(out / f"compare_{v}.png")
        rows.append(row)
    width = max(r.width for r in rows)
    sheet = Image.new("RGB", (width, sum(r.height for r in rows) + 8 * (len(rows) - 1)), (244, 243, 239))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 8
    sheet.save(out / "compare_all.png")
    print(json.dumps({"iou": scores, "bbox": stats, "out": str(out)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

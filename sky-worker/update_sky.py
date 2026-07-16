#!/usr/bin/env python3
"""Fetch the newest qualified ESO ALPACA frame and publish an atomic WebP pair."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from astropy.io import fits
from PIL import Image

TAP_URL = "https://archive.eso.org/tap_obs/sync"
OUTPUT_DIR = Path(os.environ.get("SKY_OUTPUT_DIR", "/data/sky"))
INTERVAL_SECONDS = max(900, int(os.environ.get("SKY_UPDATE_SECONDS", "3600")))
MIN_SQM_ZEN = float(os.environ.get("SKY_MIN_SQM_ZEN", "21.8"))
DISPLAY_SIZE = min(4096, max(1920, int(os.environ.get("SKY_DISPLAY_SIZE", "3840"))))
WEBP_QUALITY = min(95, max(72, int(os.environ.get("SKY_WEBP_QUALITY", "88"))))


def query_latest() -> dict[str, str]:
    query = (
        "SELECT TOP 1 dp_id,exp_start,date_end,naxis1,naxis2,sqm_zen,"
        "access_estsize,access_url FROM ist.alpaca "
        f"WHERE sqm_zen >= {MIN_SQM_ZEN:.2f} ORDER BY exp_start DESC"
    )
    params = urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query})
    request = Request(f"{TAP_URL}?{params}", headers={"User-Agent": "global-rag-sky-worker/1.0"})
    with urlopen(request, timeout=45) as response:
        rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8"))))
    if not rows:
        raise RuntimeError("ESO ALPACA did not return a qualified frame")
    return rows[0]


def current_dp_id() -> str | None:
    try:
        return json.loads((OUTPUT_DIR / "current.json").read_text("utf-8")).get("dpId")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def download(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": "global-rag-sky-worker/1.0"})
    with urlopen(request, timeout=180) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def decompress_z(source: Path, target: Path) -> None:
    with target.open("wb") as output:
        subprocess.run(["uncompress", "-c", str(source)], stdout=output, check=True)


def render_webp(source: Path, target: Path) -> None:
    with fits.open(source, memmap=True) as document:
        raw = document[0].data
        if raw is None or raw.ndim != 2:
            raise RuntimeError("ALPACA FITS frame is not a two-dimensional image")

        sample = np.asarray(raw[::12, ::12], dtype=np.float32)
        finite = sample[np.isfinite(sample)]
        if finite.size == 0:
            raise RuntimeError("ALPACA FITS frame contains no finite pixels")
        low, high = np.percentile(finite, (0.2, 99.98))
        if high <= low:
            raise RuntimeError("ALPACA FITS frame has an invalid intensity range")

        image_data = np.asarray(raw, dtype=np.float32)
        image_data = np.clip((image_data - low) / (high - low), 0.0, 1.0)
        image_data = np.power(image_data, 1.0 / 2.1)
        image_data = np.asarray(image_data * 255.0, dtype=np.uint8)

    image = Image.fromarray(image_data, mode="L")
    image.thumbnail((DISPLAY_SIZE, DISPLAY_SIZE), Image.Resampling.LANCZOS)
    image.save(target, "WEBP", quality=WEBP_QUALITY, method=5)


def publish(row: dict[str, str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="alpaca-") as temp_dir:
        temp = Path(temp_dir)
        compressed = temp / "frame.fits.Z"
        expanded = temp / "frame.fits"
        rendered = temp / "current.webp"

        download(row["access_url"], compressed)
        decompress_z(compressed, expanded)
        render_webp(expanded, rendered)

        metadata = {
            "provider": "ESO",
            "instrument": "ALPACA",
            "site": "Paranal Observatory, Chile",
            "dpId": row["dp_id"],
            "capturedAt": row["exp_start"],
            "exposureEnd": row["date_end"] + ("Z" if not row["date_end"].endswith("Z") else ""),
            "exposureSeconds": 120,
            "sqmZen": float(row["sqm_zen"]),
            "sourceWidth": int(row["naxis1"]),
            "sourceHeight": int(row["naxis2"]),
            "displayWidth": DISPLAY_SIZE,
            "displayHeight": DISPLAY_SIZE,
            "status": "latest-qualified",
            "isFallback": False,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sourcePage": "https://archive.eso.org/cms/eso-archive-news/alpaca-all-sky-images-from-paranal-available-in-the-archive.html",
            "archiveRecord": f"https://archive.eso.org/datalink/links?ID=ivo://eso.org/ID?{row['dp_id']}",
            "credit": "ESO / ALPACA",
        }
        metadata_temp = temp / "current.json"
        metadata_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", "utf-8")

        os.chmod(rendered, 0o644)
        os.chmod(metadata_temp, 0o644)
        os.replace(rendered, OUTPUT_DIR / "current.webp")
        os.replace(metadata_temp, OUTPUT_DIR / "current.json")


def update_once() -> None:
    row = query_latest()
    if row["dp_id"] == current_dp_id():
        print(f"[sky] unchanged: {row['dp_id']}", flush=True)
        return
    publish(row)
    print(f"[sky] published: {row['dp_id']} / SQM {row['sqm_zen']}", flush=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        started = time.monotonic()
        try:
            update_once()
        except Exception as error:
            print(f"[sky] update failed; keeping previous frame: {error}", flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(30, INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main()

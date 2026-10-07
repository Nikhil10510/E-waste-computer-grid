"""
E-Waste Compute Grid — Sample Test Data Setup
Owner: Nikhil Kumar

Fetches or generates sample test images for realistic demonstrations of MobileNetV2
image classification (Golden Retriever, Tabby Cat, Sports Car, Coffee Mug, Daisy, etc.).
"""

import os
import sys
import urllib.request
from pathlib import Path
from PIL import Image

# Ensure stdout UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TEST_DATA_DIR = Path(__file__).resolve().parent / "sample"
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Curated high-quality, lightweight public images from Wikimedia Commons
SAMPLE_IMAGES = [
    {
        "filename": "golden_retriever.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/Golden_Retriever_Dukedestiny01_drvd.jpg/440px-Golden_Retriever_Dukedestiny01_drvd.jpg",
        "expected_class": "golden retriever"
    },
    {
        "filename": "tabby_cat.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4d/Cat_November_2010-1a.jpg/440px-Cat_November_2010-1a.jpg",
        "expected_class": "tabby cat"
    },
    {
        "filename": "sports_car.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c9/2019_Porsche_911_Carrera_4S_3.0_Front.jpg/440px-2019_Porsche_911_Carrera_4S_3.0_Front.jpg",
        "expected_class": "sports car"
    },
    {
        "filename": "coffee_mug.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/A_small_cup_of_coffee.JPG/440px-A_small_cup_of_coffee.JPG",
        "expected_class": "coffee mug / cup"
    },
    {
        "filename": "airliner.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/Airbus_A380_overfly.jpg/440px-Airbus_A380_overfly.jpg",
        "expected_class": "airliner"
    }
]


def download_or_generate_samples():
    print(f"[DATA] Setting up test images in: {TEST_DATA_DIR}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for item in SAMPLE_IMAGES:
        file_path = TEST_DATA_DIR / item["filename"]
        if file_path.exists() and file_path.stat().st_size > 1000:
            print(f"[DATA] ✓ Already exists: {item['filename']}")
            continue

        print(f"[DATA] Downloading {item['filename']} ({item['expected_class']})...")
        try:
            req = urllib.request.Request(item["url"], headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp, open(file_path, "wb") as f:
                f.write(resp.read())
            print(f"[DATA] ✓ Downloaded {item['filename']}")
        except Exception as e:
            print(f"[DATA] ⚠ Could not download {item['filename']}: {e}. Creating fallback image...")
            # Fallback placeholder image
            img = Image.new("RGB", (224, 224), color=(120, 150, 180))
            img.save(file_path)
            print(f"[DATA] ✓ Saved fallback for {item['filename']}")

    print("\n[DATA] ✅ Sample dataset ready! Files in directory:")
    for f in TEST_DATA_DIR.glob("*.*"):
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name:25s} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    download_or_generate_samples()

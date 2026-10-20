"""DroneDrill AI - Vendor Script Downloader.

Downloads Chart.js into client/vendor/chart.min.js once for offline local usage.
No CDN links are used at runtime.
"""

from pathlib import Path
import urllib.request

VENDOR_DIR = Path(__file__).resolve().parent.parent / "client" / "vendor"
VENDOR_DIR.mkdir(parents=True, exist_ok=True)

CHARTJS_TARGET = VENDOR_DIR / "chart.min.js"
CHARTJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"

if not CHARTJS_TARGET.exists() or CHARTJS_TARGET.stat().st_size < 1000:
    print(f"Downloading Chart.js to {CHARTJS_TARGET}...")
    req = urllib.request.Request(
        CHARTJS_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req) as resp, open(CHARTJS_TARGET, "wb") as f:
        f.write(resp.read())
    print(f"Chart.js vendored successfully ({CHARTJS_TARGET.stat().st_size} bytes).")
else:
    print(f"Chart.js already vendored at {CHARTJS_TARGET}.")

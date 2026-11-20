#!/usr/bin/env python3
"""Phase 1 probe: post caption lines to a live Zoom meeting via the third-party caption API.

Usage (in a meeting you host, with Closed captions enabled):
  1. Captions -> "Use a third-party CC service" -> "Copy the API token" (it is a URL).
  2. Run:  uv run python scripts/zoom_probe.py            (paste the URL when asked; input is hidden)
     or    ZOOM_CC_URL='https://wmcc.zoom.us/closedcaption?...' uv run python scripts/zoom_probe.py
  3. In Zoom, turn on captions (Show captions) and watch the lines arrive.

What it checks: Thai renders, how `seq` must start/increment, how long a line can be, and what happens
after the token is re-copied. The token is never printed or saved.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TESTS = [
    "Hello from the caption probe. (English)",
    "สวัสดีครับ ทดสอบคำบรรยายภาษาไทย",
    "พื้นฐาน PCBA และมาตรฐาน IPC-A-610 สำหรับนิสิตวิศวกรรม",
    "ประโยคยาวเพื่อทดสอบความยาวสูงสุดของคำบรรยาย: อุตสาหกรรมอิเล็กทรอนิกส์และเซมิคอนดักเตอร์"
    "เป็นอุตสาหกรรมเป้าหมายของประเทศไทย และมีฐานการผลิตสำคัญอยู่ในพื้นที่ระเบียงเศรษฐกิจพิเศษภาคตะวันออก",
]


def mask(url: str) -> str:
    return re.sub(r"(token|id|key|signature)=[^&]+", r"\1=****", url, flags=re.I)


def post(base: str, text: str, seq: int, lang: str) -> tuple[int, str]:
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}seq={seq}&lang={urllib.parse.quote(lang)}"
    req = urllib.request.Request(
        url, data=text.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except urllib.error.URLError as e:
        return 0, str(e.reason)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="th-TH")
    ap.add_argument("--seq", type=int, default=1, help="first sequence number (default 1)")
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between posts")
    ap.add_argument("--text", action="append", help="custom line(s) instead of the built-in tests")
    ap.add_argument("--interactive", action="store_true", help="type lines yourself; empty line quits")
    a = ap.parse_args()

    base = os.environ.get("ZOOM_CC_URL") or getpass.getpass("Paste the Zoom caption API URL (hidden): ")
    base = base.strip()
    if not base.startswith("https://"):
        print("That does not look like the caption URL (expected https://...).", file=sys.stderr)
        return 2
    print(f"Target: {mask(base)}  lang={a.lang}")

    seq = a.seq
    lines = a.text or TESTS
    if a.interactive:
        lines = iter(lambda: input("caption> "), "")
    for line in lines:
        status, body = post(base, line, seq, a.lang)
        print(f"seq={seq:<4} len={len(line):<4} -> {status} {body.strip()}")
        seq += 1
        if not a.interactive:
            time.sleep(a.gap)
    print("Done. Note in Zoom: did Thai render? which lines were cut? any delay?")
    return 0


if __name__ == "__main__":
    sys.exit(main())

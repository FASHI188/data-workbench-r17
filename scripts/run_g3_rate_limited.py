#!/usr/bin/env python3
"""Rate-limited production launcher for build_g3_ohlcv.py.

This changes transport pacing only. Parsing, lifecycle, schema, hash and OHLCV evidence
rules remain those of build_g3_ohlcv.py. A failed source still fails the build.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

MODULE = Path(__file__).with_name("build_g3_ohlcv.py")
spec = importlib.util.spec_from_file_location("build_g3_ohlcv", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

_original = m.request_bytes
_last_by_host: dict[str, float] = {}


def paced_request(url: str, referer: str, attempts: int = 6, timeout: int = 90) -> bytes:
    host = "SSE" if "sse.com.cn" in url else "SZSE"
    minimum = 0.55 if host == "SSE" else 0.25
    last = _last_by_host.get(host, 0.0)
    delay = minimum - (time.monotonic() - last)
    if delay > 0:
        time.sleep(delay)
    try:
        return _original(url, referer, attempts=4, timeout=35)
    finally:
        _last_by_host[host] = time.monotonic()


m.request_bytes = paced_request
raise SystemExit(m.main())

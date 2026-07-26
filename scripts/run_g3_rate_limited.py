#!/usr/bin/env python3
"""Session-reusing, rate-limited production launcher for build_g3_ohlcv.py.

Only transport behavior is changed. Parsing, lifecycle, schema, hash and OHLCV evidence
rules remain those of build_g3_ohlcv.py. Invalid or missing evidence still fails closed.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import requests

MODULE = Path(__file__).with_name("build_g3_ohlcv.py")
spec = importlib.util.spec_from_file_location("build_g3_ohlcv", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

_sessions: dict[str, requests.Session] = {}
_last_by_host: dict[str, float] = {}


def session_for(host: str, referer: str) -> requests.Session:
    if host in _sessions:
        return _sessions[host]
    s = requests.Session()
    s.headers.update({
        "User-Agent": m.UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": referer,
        "Connection": "keep-alive",
    })
    try:
        s.get(referer, timeout=15)
    except requests.RequestException:
        pass
    _sessions[host] = s
    return s


def paced_request(url: str, referer: str, attempts: int = 6, timeout: int = 90) -> bytes:
    host = "SSE" if "sse.com.cn" in url else "SZSE"
    minimum = 0.55 if host == "SSE" else 0.25
    last_error: Exception | None = None
    s = session_for(host, referer)
    for attempt in range(1, 5):
        last = _last_by_host.get(host, 0.0)
        delay = minimum - (time.monotonic() - last)
        if delay > 0:
            time.sleep(delay)
        try:
            r = s.get(url, timeout=35)
            r.raise_for_status()
            if not r.content:
                raise RuntimeError(f"empty response: {url}")
            return r.content
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 4.0))
        finally:
            _last_by_host[host] = time.monotonic()
    assert last_error is not None
    raise last_error


m.request_bytes = paced_request
raise SystemExit(m.main())

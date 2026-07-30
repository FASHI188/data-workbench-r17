#!/usr/bin/env python3
from __future__ import annotations

# Shared clean-integration writer used only for deterministic Stage3 refreezes.
import gzip
import io
from pathlib import Path
from typing import Any

_ORIGINAL_GZIP_OPEN = gzip.open


class _DeterministicTextGzipWriter:
    def __init__(
        self,
        filename: str | bytes | Path,
        *,
        compresslevel: int = 9,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        self._raw = open(filename, "wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=self._raw,
            compresslevel=compresslevel,
            mtime=0,
        )
        self._text = io.TextIOWrapper(
            self._gzip,
            encoding=encoding or "utf-8",
            errors=errors,
            newline=newline,
        )
        self._closed = False

    def __enter__(self):
        return self._text

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._text, name)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._text.close()
        finally:
            self._raw.close()
            self._closed = True


def deterministic_gzip_open(
    filename,
    mode: str = "rb",
    compresslevel: int = 9,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
):
    """Drop gzip filename/mtime only for text writes; delegate all reads unchanged."""
    if "w" in mode and "t" in mode:
        return _DeterministicTextGzipWriter(
            filename,
            compresslevel=compresslevel,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )
    return _ORIGINAL_GZIP_OPEN(
        filename,
        mode,
        compresslevel=compresslevel,
        encoding=encoding,
        errors=errors,
        newline=newline,
    )

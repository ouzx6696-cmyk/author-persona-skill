# -*- coding: utf-8 -*-
"""File reading and robust encoding detection without external dependencies."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple


CANDIDATE_ENCODINGS = ["utf-8", "gb18030", "gbk", "big5"]
_BOMS = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


def _validate_decoded_text(text: str, encoding: str) -> None:
    """Reject byte-decoding results that are clearly not text input."""
    if "\ufffd" in text:
        raise UnicodeError(f"replacement character detected after {encoding} decoding")
    if "\x00" in text and not encoding.startswith(("utf-16", "utf-32")):
        raise UnicodeError(f"NUL characters detected after {encoding} decoding")
    control_count = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t\f")
    if control_count > max(2, len(text) // 1000):
        raise UnicodeError(f"too many control characters after {encoding} decoding")


def read_text_file(file_path: Path | str) -> Tuple[str, str]:
    """Read a text corpus with strict BOM-aware encoding detection.

    Lossy latin-1 decoding is intentionally not used as a fallback: accepting
    arbitrary bytes would turn corrupted input into a plausible but false
    analysis report.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    raw_bytes = path.read_bytes()
    for bom, enc in _BOMS:
        if raw_bytes.startswith(bom):
            text = raw_bytes.decode(enc)
            _validate_decoded_text(text, enc)
            return text, ("utf-8-sig" if enc == "utf-8-sig" else enc)

    errors = []
    for enc in CANDIDATE_ENCODINGS:
        try:
            text = raw_bytes.decode(enc)
            _validate_decoded_text(text, enc)
            return text, enc
        except UnicodeError as exc:
            errors.append(f"{enc}: {exc}")

    raise UnicodeError(
        f"Unable to decode text file safely: {path}. Tried {', '.join(CANDIDATE_ENCODINGS)}; "
        + "; ".join(errors[:3])
    )

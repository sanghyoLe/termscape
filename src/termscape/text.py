"""Display-width and mirroring helpers for ASCII/Unicode art."""

import unicodedata

# Characters swapped when art is flipped horizontally (e.g. a fish swimming left).
_MIRROR = str.maketrans("()<>[]{}/\\", ")(><][}{\\/")


def char_width(ch: str) -> int:
    """Terminal cells a character occupies: 0 for combining marks, 2 for wide CJK/emoji, else 1."""
    if ch.isascii():
        return 1
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_width(s: str) -> int:
    return sum(char_width(c) for c in s)


def pad(s: str, width: int) -> str:
    return s + " " * (width - text_width(s))


def mirror_char(ch: str) -> str:
    return ch.translate(_MIRROR)


def mirror_row(row: str) -> str:
    """Flip an already-padded row horizontally."""
    return row[::-1].translate(_MIRROR)

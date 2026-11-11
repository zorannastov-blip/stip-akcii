from __future__ import annotations

from pathlib import Path

PRIMEROCI = Path(__file__).parent / "primeroci"


def tekst(ime: str) -> str:
    return (PRIMEROCI / ime).read_text(encoding="utf-8")


def bajti(ime: str) -> bytes:
    return (PRIMEROCI / ime).read_bytes()

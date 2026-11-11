"""Логирање: една линија по настан, на стандарден излез."""

from __future__ import annotations

import logging
import sys

_POSTAVENO = False


def postavi(nivo: str = "INFO") -> None:
    global _POSTAVENO
    if _POSTAVENO:
        return
    rakuvac = logging.StreamHandler(sys.stdout)
    rakuvac.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    )
    koren = logging.getLogger()
    koren.handlers.clear()
    koren.addHandler(rakuvac)
    koren.setLevel(nivo.upper())
    for bucen in ("httpx", "httpcore", "pdfminer", "asyncio"):
        logging.getLogger(bucen).setLevel(logging.WARNING)
    _POSTAVENO = True


def get_logger(ime: str) -> logging.Logger:
    return logging.getLogger(ime)

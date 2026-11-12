"""Поставки: се читаат од postavki.toml, со разумни стандардни вредности."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STANDARDEN_AGENT = "stip-akcii/0.1 (licno dnevno citanje na javni cenovnici)"


@dataclass(frozen=True)
class Settings:
    """Она што го бара учтивиот HTTP клиент (citaci/http.py)."""

    scraper_user_agent: str = STANDARDEN_AGENT
    scraper_delay_seconds: float = 1.5
    scraper_max_retries: int = 3
    scraper_timeout_seconds: float = 90.0


@dataclass(frozen=True)
class Postavki:
    grad: str = "Штип"
    sinjiri: tuple[str, ...] = ("kam", "ramstore", "stokomak", "zito", "kipper")
    # Зборови што се следат: секој запис е еден или повеќе збора што СИТЕ
    # мора да ги има називот („кафе нескафе").
    sledi: tuple[str, ...] = ()
    # Основни производи за кои се бара најевтиниот маркет: записите
    # [[kosnicka]] како што се напишани; ги чита и проверува kosnicka.py.
    kosnicka: tuple[dict[str, Any], ...] = ()
    # Најмногу минути за една продавница, за читањето да не виси.
    minuti_po_prodavnica: int = 25
    mreza: Settings = field(default_factory=Settings)


_TEKOVNI = Settings()


def get_settings() -> Settings:
    return _TEKOVNI


def vcitaj(pateka: Path | None) -> Postavki:
    """Ги чита поставките; датотека што ја нема значи стандардни вредности."""
    global _TEKOVNI
    if pateka is None or not pateka.exists():
        return Postavki()

    with pateka.open("rb") as f:
        surovo = tomllib.load(f)

    mreza_s = surovo.get("mreza", {})
    agent = str(mreza_s.get("agent", STANDARDEN_AGENT))
    if not agent.isascii():
        raise ValueError("mreza.agent смее да има само ASCII знаци (HTTP заглавие)")
    mreza = Settings(
        scraper_user_agent=agent,
        scraper_delay_seconds=float(mreza_s.get("pauza_sekundi", 1.5)),
        scraper_max_retries=int(mreza_s.get("obidi", 3)),
        scraper_timeout_seconds=float(mreza_s.get("istek_sekundi", 90.0)),
    )
    _TEKOVNI = mreza

    osnovno = Postavki()
    return Postavki(
        grad=str(surovo.get("grad", osnovno.grad)),
        sinjiri=tuple(surovo.get("sinjiri", osnovno.sinjiri)),
        sledi=tuple(str(z) for z in surovo.get("sledi", ())),
        kosnicka=tuple(dict(z) for z in surovo.get("kosnicka", ())),
        minuti_po_prodavnica=int(
            surovo.get("minuti_po_prodavnica", osnovno.minuti_po_prodavnica)
        ),
        mreza=mreza,
    )

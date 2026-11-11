"""Дневното читање: `python -m stipakcii`.

    python -m stipakcii                    прочитај сè, запиши, изгради извештај
    python -m stipakcii --samo kam,zito    само наведените синџири
    python -m stipakcii --samo-izvestaj    без мрежа: извештај од она што е запишано
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stipakcii import dnevnik, izvestaj, skladiste
from stipakcii.citanje import OK, procitaj_se
from stipakcii.postavki import vcitaj

log = dnevnik.get_logger("stipakcii")
ZONA = ZoneInfo("Europe/Skopje")


def _argumenti(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="stipakcii", description=__doc__.splitlines()[0])
    p.add_argument("--koren", type=Path, default=Path.cwd(), help="папката на проектот")
    p.add_argument("--postavki", type=Path, default=None, help="стандардно: <koren>/postavki.toml")
    p.add_argument("--samo", default="", help="кодови на синџири, одделени со запирка")
    p.add_argument("--samo-izvestaj", action="store_true", help="не читај, само изгради извештај")
    p.add_argument("--datum", default="", help="ГГГГ-ММ-ДД наместо денес (за проба)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arg = _argumenti(argv)
    dnevnik.postavi()
    koren: Path = arg.koren
    postavki = vcitaj(arg.postavki or koren / "postavki.toml")
    denes = date.fromisoformat(arg.datum) if arg.datum else datetime.now(ZONA).date()
    podatoci = koren / "podatoci"

    kod = 0
    if not arg.samo_izvestaj:
        samo = tuple(k.strip() for k in arg.samo.split(",") if k.strip())
        ishodi = asyncio.run(procitaj_se(postavki, samo))
        uspesni = sum(p.status == OK for s in ishodi for p in s.prodavnici)
        if uspesni == 0:
            # Ништо не се прочитало: вчерашните податоци остануваат недопрени,
            # а излезот со грешка го прави читањето црвено во GitHub Actions.
            for s in ishodi:
                log.error("%s: %s", s.sinjir_ime, s.poraka or "ниедна продавница не се прочита")
            log.error("Ниту еден ценовник не се прочита. Податоците не се менуваат.")
            return 1

        zbir = skladiste.zapisi_den(podatoci, ishodi, denes)
        log.info(
            "Запишано: %d од %d продавници, %d реда, %d акции (%d нови, %d завршени), "
            "%d променети редовни цени",
            zbir.prodavnici_ok,
            zbir.prodavnici_vkupno,
            zbir.redovi,
            zbir.akcii,
            zbir.novi_akcii,
            zbir.zavrseni_akcii,
            zbir.promeni_na_ceni,
        )
        for s in ishodi:
            if s.status != OK:
                # Синтакса што GitHub Actions ја прикажува како предупредување.
                print(f"::warning title={s.sinjir_ime}::{s.poraka}")
            for p in s.prodavnici:
                if p.status != OK:
                    print(f"::warning title={p.sinjir_ime} {p.prodavnica}::{p.poraka}")

    izvestaj.zapisi(koren, izvestaj.soberi(podatoci, postavki, denes))
    log.info("Извештајот е во docs/index.html и IZVESTAJ.md")
    return kod


if __name__ == "__main__":
    sys.exit(main())

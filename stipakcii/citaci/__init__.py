"""Читачи на ценовници, по еден модул на синџир (од Marketchecker)."""

from __future__ import annotations

from stipakcii.citaci.base import PricelistReader
from stipakcii.citaci.kam import KamReader
from stipakcii.citaci.kipper import KipperReader
from stipakcii.citaci.proverkanaceni import StokomakReader, ZitoReader
from stipakcii.citaci.ramstore import RamstoreReader

# код на синџир -> класа на читач. Нов синџир: еден модул и еден ред тука.
CITACI: dict[str, type[PricelistReader]] = {
    KamReader.chain_code: KamReader,
    RamstoreReader.chain_code: RamstoreReader,
    StokomakReader.chain_code: StokomakReader,
    ZitoReader.chain_code: ZitoReader,
    KipperReader.chain_code: KipperReader,
}

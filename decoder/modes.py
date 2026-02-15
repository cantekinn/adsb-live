"""
Mode-S mesaj alan ayiklama.

14-byte (112-bit) uzun mesaj formati:
    bit  0..4   DF  - Downlink Format (5 bit)
    bit  5..7   CA  - Capability (3 bit)
    bit  8..31  AA  - ICAO 24-bit adres
    bit 32..87  ME  - Message Extended (56 bit, ADS-B payload)
    bit 88..111 PI  - Parity/CRC (24 bit)
"""

from dataclasses import dataclass


@dataclass
class ModeSFrame:
    df: int
    ca: int
    icao: str       # 6 hex
    me: bytes       # 7 byte (56 bit)
    raw: bytes      # tum 14 byte


def parse(msg: bytes) -> ModeSFrame | None:
    """14 byte mesaji ModeSFrame'e parse eder. DF 17/18 disindaysa None."""
    if len(msg) != 14:
        return None

    df = (msg[0] >> 3) & 0x1F
    if df not in (17, 18):
        return None

    ca = msg[0] & 0x07
    icao = msg[1:4].hex().upper()
    me = msg[4:11]
    return ModeSFrame(df=df, ca=ca, icao=icao, me=me, raw=msg)


def get_tc(me: bytes) -> int:
    """ADS-B Type Code: ME alaninin ilk 5 biti."""
    return (me[0] >> 3) & 0x1F

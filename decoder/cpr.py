"""
Compact Position Reporting (CPR) cozumu.

ADS-B airborne pozisyonu 17 bit lat + 17 bit lon olarak kodlanir,
ama mutlak degil - "even" (F=0) ve "odd" (F=1) iki farkli enlem
zone yapisi ile sikistirilmistir.

Global cozum: 10 saniye icinde ayni ICAO'dan bir even + bir odd frame.
Local cozum:  bilinen referans (~100 NM) ile tek frame.

Referans: Junzi Sun, "1090 MHz Riddle", bolum 5.
"""

import math
from dataclasses import dataclass

NZ = 15  # latitude zone sayisi (kuzey yarim kurede)


@dataclass
class CprFrame:
    icao: str
    f: int          # 0=even, 1=odd
    lat_cpr: int    # 17-bit ham deger
    lon_cpr: int
    t: float        # zaman damgasi (s)


def _mod(a: float, b: float) -> float:
    """Pozitif modulo (Python % zaten ayni davranir, sadelik icin sarmal)."""
    return a - b * math.floor(a / b)


def _nl(lat: float) -> int:
    """
    Verilen enlem icin longitude zone sayisi (NL).
    ICAO Annex 10 Vol IV Tablo C-1; analitik formul:
    """
    if lat == 0:
        return 59
    if abs(lat) >= 87:
        return 1
    if abs(lat) == 87:
        return 2
    return int(math.floor(
        (2 * math.pi) /
        math.acos(1 - (1 - math.cos(math.pi / (2 * NZ))) /
                       math.cos(math.radians(abs(lat))) ** 2)
    ))


def decode_global(even: CprFrame, odd: CprFrame) -> tuple[float, float] | None:
    """
    Global CPR. Iki frame'i yas sirasina gore alip son frame'in pozisyonunu verir.
    None donmesi -> NL tutarsizligi (cozulemez, baska pair beklemek lazim).
    """
    # ham CPR -> normalize
    lat_e = even.lat_cpr / 2**17
    lat_o = odd.lat_cpr / 2**17
    lon_e = even.lon_cpr / 2**17
    lon_o = odd.lon_cpr / 2**17

    # latitude index j
    j = math.floor(59 * lat_e - 60 * lat_o + 0.5)

    d_lat_e = 360.0 / (4 * NZ)        # 6 derece
    d_lat_o = 360.0 / (4 * NZ - 1)    # ~6.10169

    lat_even = d_lat_e * (_mod(j, 60) + lat_e)
    lat_odd = d_lat_o * (_mod(j, 59) + lat_o)

    # guney yarimkure duzeltmesi
    if lat_even >= 270:
        lat_even -= 360
    if lat_odd >= 270:
        lat_odd -= 360

    # son frame hangisiyse onun enlemini kullan
    if odd.t >= even.t:
        lat = lat_odd
        f = 1
    else:
        lat = lat_even
        f = 0

    # NL tutarliligi kontrol
    if _nl(lat_even) != _nl(lat_odd):
        return None

    nl = _nl(lat)
    ni = max(nl - f, 1)

    m = math.floor(lon_e * (nl - 1) - lon_o * nl + 0.5)

    if f == 0:
        lon = (360.0 / ni) * (_mod(m, ni) + lon_e)
    else:
        lon = (360.0 / ni) * (_mod(m, ni) + lon_o)

    if lon >= 180:
        lon -= 360

    return lat, lon


def decode_local(frame: CprFrame, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """Tek frame + referans. Referans 180 NM (~333 km) icinde olmali."""
    f = frame.f
    lat_cpr = frame.lat_cpr / 2**17
    lon_cpr = frame.lon_cpr / 2**17

    d_lat = 360.0 / (4 * NZ - f)
    j = math.floor(ref_lat / d_lat) + math.floor(
        _mod(ref_lat, d_lat) / d_lat - lat_cpr + 0.5
    )
    lat = d_lat * (j + lat_cpr)

    nl = _nl(lat)
    ni = max(nl - f, 1)
    d_lon = 360.0 / ni

    m = math.floor(ref_lon / d_lon) + math.floor(
        _mod(ref_lon, d_lon) / d_lon - lon_cpr + 0.5
    )
    lon = d_lon * (m + lon_cpr)

    return lat, lon

"""
Mode-S DF17 ADS-B mesaj encoder.

decoder/* tarafindaki cozucu fonksiyonlarin tersi:
  - identification (TC 1-4)
  - airborne position (TC 9-18, baro alt)
  - velocity (TC 19, GS subtype 1)

CPR encoding icin Junzi Sun "1090 MHz Riddle" Bolum 5 formullerinin tersi.

CRC: decoder.crc.compute kullanip son 3 byte'a yazariz.
"""

import math
from dataclasses import dataclass
from decoder.crc import compute as crc_compute

NZ = 15
_ICAO_CHARS = '#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######'
_CHAR_TO_CODE = {c: i for i, c in enumerate(_ICAO_CHARS) if c != '#'}


def _nl(lat: float) -> int:
    if lat == 0: return 59
    if abs(lat) >= 87: return 1
    return int(math.floor(
        (2 * math.pi) /
        math.acos(1 - (1 - math.cos(math.pi / (2 * NZ))) /
                       math.cos(math.radians(abs(lat))) ** 2)
    ))


def _pack_bits(bits: list[int]) -> bytes:
    """[1,0,1,1,...] -> bytes. Uzunluk 8'in kati olmali."""
    assert len(bits) % 8 == 0
    out = bytearray(len(bits) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (7 - (i % 8))
    return bytes(out)


def _int_to_bits(val: int, n: int) -> list[int]:
    return [(val >> (n - 1 - i)) & 1 for i in range(n)]


def encode_callsign(callsign: str) -> bytes:
    """8-karakter callsign -> 6-byte ME alt-payload (TC 1-4 i\u00e7in)."""
    cs = (callsign.upper() + '________')[:8]
    bits = []
    for c in cs:
        code = _CHAR_TO_CODE.get(c, 32)  # bilinmeyen -> space
        bits.extend(_int_to_bits(code, 6))
    return _pack_bits(bits)


def encode_altitude_q1(alt_ft: int) -> int:
    """25-ft cozunurluklu Q=1 altitude 12-bit kodu doner."""
    n = (alt_ft + 1000) // 25
    if n < 0: n = 0
    if n > 2047: n = 2047
    # 11 bit n, ortasinda Q-bit (=1)
    upper7 = (n >> 4) & 0x7F   # ust 7 bit
    lower4 = n & 0x0F          # alt 4 bit
    return (upper7 << 5) | (1 << 4) | lower4


def cpr_encode(lat: float, lon: float, f: int) -> tuple[int, int]:
    """Lat/Lon -> 17-bit even/odd CPR çiftleri."""
    d_lat = 360.0 / (4 * NZ - f)
    yz = math.floor(2**17 * ((lat % d_lat) / d_lat) + 0.5)
    rlat = d_lat * (yz / 2**17 + math.floor(lat / d_lat))
    nl = _nl(rlat)
    ni = max(nl - f, 1)
    d_lon = 360.0 / ni
    xz = math.floor(2**17 * ((lon % d_lon) / d_lon) + 0.5)
    return int(yz) & 0x1FFFF, int(xz) & 0x1FFFF


def encode_position(lat: float, lon: float, alt_ft: int, f: int,
                    tc: int = 11) -> bytes:
    """DF17 ME alani (7 byte) - airborne position (baro)."""
    yz, xz = cpr_encode(lat, lon, f)
    alt12 = encode_altitude_q1(alt_ft)
    # ME yapisi:
    #   bit 0..4   TC (5)
    #   bit 5..6   SS  (surveillance status, 0)
    #   bit 7      NIC supp (0)
    #   bit 8..19  ALT (12)
    #   bit 20     T  (time, 0)
    #   bit 21     F  (CPR format)
    #   bit 22..38 lat-cpr (17)
    #   bit 39..55 lon-cpr (17)
    bits = []
    bits.extend(_int_to_bits(tc, 5))   # TC
    bits.extend([0, 0])                # SS
    bits.append(0)                     # NIC supp
    bits.extend(_int_to_bits(alt12, 12))
    bits.append(0)                     # T
    bits.append(f & 1)                 # F
    bits.extend(_int_to_bits(yz, 17))
    bits.extend(_int_to_bits(xz, 17))
    assert len(bits) == 56
    return _pack_bits(bits)


def encode_velocity(speed_kt: float, heading_deg: float,
                    vert_rate_fpm: int) -> bytes:
    """TC 19 subtype 1 (ground speed) velocity ME alani."""
    rad = math.radians(heading_deg)
    vx = speed_kt * math.sin(rad)
    vy = speed_kt * math.cos(rad)
    s_ew = 1 if vx < 0 else 0
    s_ns = 1 if vy < 0 else 0
    v_ew = int(round(abs(vx))) + 1
    v_ns = int(round(abs(vy))) + 1
    v_ew = max(1, min(1023, v_ew))
    v_ns = max(1, min(1023, v_ns))

    vr_sign = 1 if vert_rate_fpm < 0 else 0
    vr_val = int(round(abs(vert_rate_fpm) / 64.0)) + 1
    vr_val = max(1, min(511, vr_val))

    bits = []
    bits.extend(_int_to_bits(19, 5))   # TC
    bits.extend(_int_to_bits(1, 3))    # Subtype = 1 (GS)
    bits.append(0)                     # IC
    bits.append(0)                     # IFR cap
    bits.extend(_int_to_bits(0, 3))    # NUC vel
    bits.append(s_ew)
    bits.extend(_int_to_bits(v_ew, 10))
    bits.append(s_ns)
    bits.extend(_int_to_bits(v_ns, 10))
    bits.append(0)                     # vrate source (baro=0)
    bits.append(vr_sign)
    bits.extend(_int_to_bits(vr_val, 9))
    bits.extend(_int_to_bits(0, 2))    # reserved
    bits.append(0)                     # diff alt sign
    bits.extend(_int_to_bits(0, 7))    # diff alt
    assert len(bits) == 56
    return _pack_bits(bits)


def encode_identification(callsign: str, category: int = 5) -> bytes:
    """TC 4 (heavy=A4) identification ME alani."""
    # TC 4 = heavy aircraft (Category A4)
    bits = []
    bits.extend(_int_to_bits(4, 5))                  # TC = 4
    bits.extend(_int_to_bits(category & 7, 3))       # Category subtype
    cs_bytes = encode_callsign(callsign)
    # cs_bytes 6 byte = 48 bit
    for byte in cs_bytes:
        bits.extend(_int_to_bits(byte, 8))
    assert len(bits) == 56
    return _pack_bits(bits)


def build_df17(icao: str, me: bytes) -> bytes:
    """DF17 mesaji + CRC kapatma. icao=6 hex string."""
    df_ca = (17 << 3) | 5   # DF=17, CA=5
    icao_bytes = bytes.fromhex(icao)
    pre = bytes([df_ca]) + icao_bytes + me   # 11 byte
    full = pre + b'\x00\x00\x00'             # CRC yeri
    crc = crc_compute(full)
    return pre + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])

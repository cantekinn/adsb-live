"""
ADS-B (DF17) ME alani decode.

Type Code (TC) ME ilk 5 biti:
    1-4    Aircraft Identification (callsign)
    5-8    Surface Position (v1'de yok)
    9-18   Airborne Position (baro altitude)
    19     Velocity
    20-22  Airborne Position (GNSS altitude)
"""

from dataclasses import dataclass

# ICAO 6-bit karakter setine bakim - 64 karakter
# A-Z = 1-26, 0-9 = 48-57, ' ' = 32, '_' / kalan -> '#'
_ICAO_CHARS = '#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######'


@dataclass
class Identification:
    callsign: str
    category: int  # uçak kategorisi (TC 1-4)


@dataclass
class AirbornePosition:
    f: int          # 0=even, 1=odd
    lat_cpr: int    # 17-bit
    lon_cpr: int
    altitude: int | None    # ft, baro


@dataclass
class Velocity:
    speed: float | None      # knots, ground speed
    heading: float | None    # deg, true track
    vertical_rate: int | None  # ft/min, +up
    speed_type: str          # "GS" veya "TAS"/"IAS"


# ------------------------------------------------------------
# yardimci - ME byte'larindan bit dilim cikar (MSB-first)
# ------------------------------------------------------------
def _bits(me: bytes, start: int, length: int) -> int:
    """ME (56 bit) icinden start. bitten itibaren length bit ciplak int."""
    val = int.from_bytes(me, 'big')   # 56-bit
    shift = 56 - start - length
    return (val >> shift) & ((1 << length) - 1)


# ------------------------------------------------------------
# TC 1-4: Identification (callsign)
# ------------------------------------------------------------
def decode_identification(me: bytes) -> Identification:
    category = _bits(me, 5, 3)
    chars = []
    for i in range(8):
        c = _bits(me, 8 + i * 6, 6)
        chars.append(_ICAO_CHARS[c])
    callsign = ''.join(chars).rstrip('#').rstrip()
    return Identification(callsign=callsign, category=category)


# ------------------------------------------------------------
# TC 9-18: Airborne Position (baro)
# ------------------------------------------------------------
def _decode_altitude_baro(alt_bits: int) -> int | None:
    """
    12-bit altitude alani. Q-bit (bit 4) = 1 -> 25 ft cozunurluk.
    """
    if alt_bits == 0:
        return None
    q = (alt_bits >> 4) & 1
    if q == 1:
        # Q=1: 11 bit -> N, alt = N*25 - 1000 ft
        n = ((alt_bits >> 5) << 4) | (alt_bits & 0x0F)
        return n * 25 - 1000
    # Q=0: 100 ft cozunurluk, Gillham kodlu - nadiren karsilasilir, atla
    return None


def decode_airborne_position(me: bytes) -> AirbornePosition:
    altitude = _decode_altitude_baro(_bits(me, 8, 12))
    f = _bits(me, 21, 1)
    lat_cpr = _bits(me, 22, 17)
    lon_cpr = _bits(me, 39, 17)
    return AirbornePosition(f=f, lat_cpr=lat_cpr, lon_cpr=lon_cpr,
                             altitude=altitude)


# ------------------------------------------------------------
# TC 5-8: Surface Position (yer trafigi)
# ------------------------------------------------------------
@dataclass
class SurfacePosition:
    f: int
    lat_cpr: int
    lon_cpr: int
    speed: float | None     # knots (0.125 cozunurluk dusuk, 1 yuksek)
    heading: float | None   # deg


def decode_surface_position(me: bytes) -> SurfacePosition:
    """Yer trafigi - hiz + heading + CPR."""
    mov = _bits(me, 5, 7)   # movement
    spd = None
    if mov == 0:
        spd = None
    elif mov == 1:
        spd = 0.0
    elif mov <= 8:
        spd = (mov - 1) * 0.125
    elif mov <= 12:
        spd = 1.0 + (mov - 9) * 0.25
    elif mov <= 38:
        spd = 2.0 + (mov - 13) * 0.5
    elif mov <= 93:
        spd = 15.0 + (mov - 39) * 1.0
    elif mov <= 108:
        spd = 70.0 + (mov - 94) * 2.0
    elif mov <= 123:
        spd = 100.0 + (mov - 109) * 5.0
    else:
        spd = 175.0  # >= 175 kt

    hdg_status = _bits(me, 12, 1)
    hdg_val = _bits(me, 13, 7)
    hdg = hdg_val * 360.0 / 128.0 if hdg_status else None

    f = _bits(me, 21, 1)
    lat_cpr = _bits(me, 22, 17)
    lon_cpr = _bits(me, 39, 17)
    return SurfacePosition(f=f, lat_cpr=lat_cpr, lon_cpr=lon_cpr,
                           speed=spd, heading=hdg)


# ------------------------------------------------------------
# TC 19: Velocity
# ------------------------------------------------------------
def decode_velocity(me: bytes) -> Velocity | None:
    subtype = _bits(me, 5, 3)
    if subtype in (1, 2):
        # Ground speed
        s_ew = _bits(me, 13, 1)
        v_ew = _bits(me, 14, 10) - 1
        s_ns = _bits(me, 24, 1)
        v_ns = _bits(me, 25, 10) - 1
        if v_ew < 0 or v_ns < 0:
            return None
        vx = -v_ew if s_ew else v_ew
        vy = -v_ns if s_ns else v_ns
        import math as _m
        speed = _m.sqrt(vx * vx + vy * vy)
        heading = _m.degrees(_m.atan2(vx, vy))
        if heading < 0:
            heading += 360
        vr = _vertical_rate(me)
        return Velocity(speed=speed, heading=heading, vertical_rate=vr,
                        speed_type='GS')
    if subtype in (3, 4):
        # Airspeed
        hdg_status = _bits(me, 13, 1)
        hdg_val = _bits(me, 14, 10)
        airspeed = _bits(me, 25, 10) - 1
        if airspeed < 0:
            return None
        heading = hdg_val * 360.0 / 1024.0 if hdg_status else None
        vr = _vertical_rate(me)
        as_type = 'TAS' if _bits(me, 24, 1) else 'IAS'
        return Velocity(speed=airspeed, heading=heading, vertical_rate=vr,
                        speed_type=as_type)
    return None


# ------------------------------------------------------------
# TC 31: Operational Status (NIC, NACp, GVA, SDA)
# ------------------------------------------------------------
@dataclass
class OperationalStatus:
    subtype: int           # 0=airborne, 1=surface
    nic: int | None        # Navigation Integrity Category
    nacp: int | None       # Navigation Accuracy Category (position)
    gva: int | None        # Geometric Vertical Accuracy
    sda: int | None        # System Design Assurance
    version: int           # ADS-B version


def decode_operational_status(me: bytes) -> OperationalStatus:
    """TC 31 Operational Status. Versiyon 1/2'ye gore alanlar farkli."""
    subtype = _bits(me, 5, 3)
    version = _bits(me, 40, 3)
    nacp = _bits(me, 48, 4) if subtype == 0 else _bits(me, 48, 4)
    gva = _bits(me, 52, 2) if subtype == 0 else None
    sda = _bits(me, 54, 2)
    nic = _bits(me, 55, 1) | (_bits(me, 36, 1) << 1)   # NIC supp-A + NICbaro
    return OperationalStatus(subtype=subtype, nic=nic, nacp=nacp,
                             gva=gva, sda=sda, version=version)


def _vertical_rate(me: bytes) -> int | None:
    sign = _bits(me, 36, 1)
    val = _bits(me, 37, 9) - 1
    if val < 0:
        return None
    rate = val * 64
    return -rate if sign else rate

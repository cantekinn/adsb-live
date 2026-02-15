"""
Mode-S Comm-B (DF20/DF21) MB alani decode.

DF20 = Comm-B Altitude Reply, DF21 = Comm-B Identity Reply.
Her ikisi de 112 bit, son 56 biti MB (Comm-B veri alani).

MB ilk 8 biti = BDS register tanimlayicisi.
Bizim icin onemli olan:
  BDS 2,0 = Aircraft Identification (callsign, 6-bit ICAO chars)

CRC formulu Comm-B'de: alinan CRC = ICAO XOR computed_CRC(msg).
Bu yuzden ICAO bilinmiyorsa dogrulanamiyor. DF17'den tanidigimiz
ICAO'larin whitelist'i ile dogruluyoruz (cross-validation).
"""

from dataclasses import dataclass

from . import crc as crc_mod

_ICAO_CHARS = '#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######'


@dataclass
class CommBIdent:
    callsign: str


def extract_icao_from_pi(msg: bytes) -> str:
    """
    Comm-B/DF11 mesajindan ICAO adresini cikar.
    CRC = top24(computed_CRC(msg)) XOR last24(msg) = ICAO
    """
    pi = int.from_bytes(msg[-3:], 'big')
    computed = crc_mod.compute(msg[:-3] + b'\x00\x00\x00')
    icao_int = pi ^ computed
    return f'{icao_int:06X}'


@dataclass
class SelectedVertical:
    """BDS 4,0 - Kokpit secili dikey hedef."""
    mcp_alt: int | None     # ft, MCP selected altitude
    fms_alt: int | None     # ft, FMS selected
    baro_set: float | None  # mb, pressure setting


@dataclass
class TrackAndTurn:
    """BDS 5,0 - Tur/heading raporlari."""
    roll: float | None       # deg
    track: float | None      # deg
    ground_speed: float | None  # kt
    track_rate: float | None    # deg/s
    tas: float | None        # kt


@dataclass
class HeadingSpeed:
    """BDS 6,0 - Heading + speed (kokpit IAS, Mach)."""
    mag_heading: float | None  # deg
    ias: int | None            # kt
    mach: float | None
    baro_rate: int | None      # ft/min
    inertial_rate: int | None  # ft/min


def _is_valid_bds40(mb: bytes) -> bool:
    """BDS 4,0 sanity check - status bitleri tutarli mi."""
    # Bit 1, 14, 27 status, sonraki alanlari "active" yapar
    s1 = (mb[0] >> 7) & 1
    if s1 == 0 and int.from_bytes(mb[:2], 'big') & 0x7FE0 != 0:
        return False
    return True


def decode_bds40(msg: bytes) -> SelectedVertical | None:
    """DF20/21 MB alaninda BDS 4,0 cozumu."""
    if len(msg) != 14:
        return None
    mb = msg[4:11]
    val = int.from_bytes(mb, 'big')   # 56 bit

    # bit 1 status, bit 2-13 MCP alt (12 bit, 16-ft cozunurluk)
    s_mcp = (val >> 55) & 1
    mcp = (val >> 43) & 0xFFF
    mcp_ft = mcp * 16 if s_mcp else None

    s_fms = (val >> 42) & 1
    fms = (val >> 30) & 0xFFF
    fms_ft = fms * 16 if s_fms else None

    s_baro = (val >> 29) & 1
    baro = (val >> 17) & 0xFFF
    baro_mb = 800 + baro * 0.1 if s_baro else None

    # En az bir alan valid degilse kabul etme
    if mcp_ft is None and fms_ft is None and baro_mb is None:
        return None
    # Sanity: yukseklikler 60000 ft alti olmali
    if mcp_ft and (mcp_ft > 60000 or mcp_ft < 0):
        return None
    if fms_ft and (fms_ft > 60000 or fms_ft < 0):
        return None
    return SelectedVertical(mcp_alt=mcp_ft, fms_alt=fms_ft, baro_set=baro_mb)


def decode_bds50(msg: bytes) -> TrackAndTurn | None:
    """DF20/21 MB alaninda BDS 5,0 cozumu."""
    if len(msg) != 14:
        return None
    mb = msg[4:11]
    val = int.from_bytes(mb, 'big')

    s_roll = (val >> 55) & 1
    roll_raw = (val >> 45) & 0x1FF
    if s_roll:
        roll = roll_raw * 45.0 / 256.0
        # bit 11 sign
        if (val >> 54) & 1: roll = -roll
    else: roll = None

    s_trk = (val >> 44) & 1
    trk_raw = (val >> 33) & 0x3FF
    if s_trk:
        trk = trk_raw * 90.0 / 512.0
        if (val >> 43) & 1: trk = (trk + 360) % 360
        if trk < 0 or trk > 360: trk = None
    else: trk = None

    s_gs = (val >> 32) & 1
    gs_raw = (val >> 22) & 0x3FF
    gs = gs_raw * 2 if s_gs and gs_raw > 0 else None
    if gs and (gs > 700 or gs < 0): gs = None

    s_trate = (val >> 21) & 1
    trate_raw = (val >> 12) & 0x1FF
    if s_trate:
        trate = trate_raw * 8.0 / 256.0
        if (val >> 20) & 1: trate = -trate
    else: trate = None

    s_tas = (val >> 11) & 1
    tas_raw = (val >> 1) & 0x3FF
    tas = tas_raw * 2 if s_tas and tas_raw > 0 else None
    if tas and (tas > 700 or tas < 0): tas = None

    # En az 2 alan valid olmali
    valid = sum(v is not None for v in (roll, trk, gs, trate, tas))
    if valid < 2:
        return None
    return TrackAndTurn(roll=roll, track=trk, ground_speed=gs,
                        track_rate=trate, tas=tas)


def decode_bds60(msg: bytes) -> HeadingSpeed | None:
    """DF20/21 MB alaninda BDS 6,0 cozumu."""
    if len(msg) != 14:
        return None
    mb = msg[4:11]
    val = int.from_bytes(mb, 'big')

    s_hdg = (val >> 55) & 1
    hdg_raw = (val >> 44) & 0x7FF
    if s_hdg:
        hdg = hdg_raw * 90.0 / 512.0
        if (val >> 54) & 1: hdg = (hdg + 360) % 360
        if hdg < 0 or hdg > 360: hdg = None
    else: hdg = None

    s_ias = (val >> 43) & 1
    ias_raw = (val >> 33) & 0x3FF
    ias = int(ias_raw) if s_ias and ias_raw > 0 else None
    if ias and (ias > 500 or ias < 0): ias = None

    s_mach = (val >> 32) & 1
    mach_raw = (val >> 22) & 0x3FF
    mach = mach_raw * 0.004 if s_mach and mach_raw > 0 else None
    if mach and (mach > 1 or mach < 0): mach = None

    s_baro = (val >> 21) & 1
    baro_raw = (val >> 12) & 0x1FF
    if s_baro:
        baro_rate = baro_raw * 32
        if (val >> 20) & 1: baro_rate = -baro_rate
        if abs(baro_rate) > 8000: baro_rate = None
    else: baro_rate = None

    s_inert = (val >> 11) & 1
    inert_raw = (val >> 1) & 0x1FF
    if s_inert:
        inert_rate = inert_raw * 32
        if (val >> 10) & 1: inert_rate = -inert_rate
        if abs(inert_rate) > 8000: inert_rate = None
    else: inert_rate = None

    valid = sum(v is not None for v in (hdg, ias, mach, baro_rate, inert_rate))
    if valid < 2:
        return None
    return HeadingSpeed(mag_heading=hdg, ias=ias, mach=mach,
                        baro_rate=baro_rate, inertial_rate=inert_rate)


def decode_bds20_callsign(msg: bytes) -> str | None:
    """
    DF20/21 mesajinin MB alaninda BDS 2,0 varsa callsign'i cozer.
    msg: 14 byte (112 bit) tam Mode-S mesaji.
    MB = byte index 4..10 (7 byte, 56 bit), ilk byte BDS kodu.
    """
    if len(msg) != 14:
        return None
    mb = msg[4:11]
    if mb[0] != 0x20:
        return None
    # 8 karakter x 6 bit = 48 bit (mb[1..6])
    bits = int.from_bytes(mb[1:7], 'big')  # 48 bit
    chars = []
    for i in range(8):
        c = (bits >> (42 - 6 * i)) & 0x3F
        chars.append(_ICAO_CHARS[c])
    cs = ''.join(chars).rstrip('#').rstrip()
    # Bos veya cok kisa ise sahte
    if len(cs) < 2:
        return None
    return cs

"""
Decoder birim testleri.

Bilinen iyi Mode-S/ADS-B mesajlari uzerinden CRC, parse ve decode dogrula.
Referans vektorler: Junzi Sun "1090 MHz Riddle" ve pyModeS dokumantasyonu.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decoder import crc, modes, adsb
from decoder.cpr import CprFrame, decode_global


# --------------------------------------------------------------
def test_crc_valid_df17():
    # KLM1023 callsign mesaji - bilinen iyi
    msg = bytes.fromhex('8D4840D6202CC371C32CE0576098')
    assert crc.compute(msg) == 0


def test_crc_invalid_when_corrupted():
    msg = bytearray(bytes.fromhex('8D4840D6202CC371C32CE0576098'))
    msg[5] ^= 0x01  # bit cevir
    assert crc.compute(bytes(msg)) != 0


# --------------------------------------------------------------
def test_parse_df17():
    msg = bytes.fromhex('8D4840D6202CC371C32CE0576098')
    f = modes.parse(msg)
    assert f is not None
    assert f.df == 17
    assert f.icao == '4840D6'
    assert modes.get_tc(f.me) == 4    # identification


def test_callsign_decode():
    msg = bytes.fromhex('8D4840D6202CC371C32CE0576098')
    f = modes.parse(msg)
    ident = adsb.decode_identification(f.me)
    assert ident.callsign.strip() == 'KLM1023'


# --------------------------------------------------------------
def test_airborne_position():
    # Bilinen even+odd cifti, ICAO 40621D, lat~52.2572, lon~3.9192
    even = bytes.fromhex('8D40621D58C382D690C8AC2863A7')
    odd = bytes.fromhex('8D40621D58C386435CC412692AD6')
    fe = modes.parse(even)
    fo = modes.parse(odd)
    pe = adsb.decode_airborne_position(fe.me)
    po = adsb.decode_airborne_position(fo.me)
    assert pe.f == 0
    assert po.f == 1

    # Even daha guncel -> lat_even kullanilir, klasik "1090 Riddle" referansi
    cf_e = CprFrame(icao='40621D', f=0, lat_cpr=pe.lat_cpr,
                    lon_cpr=pe.lon_cpr, t=2.0)
    cf_o = CprFrame(icao='40621D', f=1, lat_cpr=po.lat_cpr,
                    lon_cpr=po.lon_cpr, t=1.0)
    lat, lon = decode_global(cf_e, cf_o)
    assert abs(lat - 52.2572) < 0.001, f'lat={lat}'
    assert abs(lon - 3.9194) < 0.001, f'lon={lon}'


# --------------------------------------------------------------
def test_velocity():
    # bilinen velocity mesaji - GS subtype 1
    msg = bytes.fromhex('8D485020994409940838175B284F')
    f = modes.parse(msg)
    assert modes.get_tc(f.me) == 19
    v = adsb.decode_velocity(f.me)
    assert v is not None
    assert v.speed_type == 'GS'
    assert 150 < v.speed < 200

"""
End-to-end pipeline testi: sentetik IQ -> preamble -> PPM -> CRC -> decode.

SDR olmadan tum sayisal isaret isleme zincirini dogrular.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from decoder import preamble, ppm, crc, modes, adsb


def _make_iq(msg_hex: str, lead: int = 50, trail: int = 50) -> np.ndarray:
    """Bilinen DF17 mesajini ideal preamble + PPM ile sentezle."""
    msg = bytes.fromhex(msg_hex)
    bits = []
    for b in msg:
        for i in range(8):
            bits.append((b >> (7 - i)) & 1)
    pre = np.zeros(16, dtype=np.float32)
    for i in (0, 2, 7, 9):
        pre[i] = 1.0
    body = np.zeros(112 * 2, dtype=np.float32)
    for i, b in enumerate(bits):
        body[i * 2 + (0 if b else 1)] = 1.0
    sig = np.concatenate([np.zeros(lead, dtype=np.float32), pre, body,
                          np.zeros(trail, dtype=np.float32)])
    return sig.astype(np.complex64)


def test_end_to_end_callsign():
    msg_hex = '8D4840D6202CC371C32CE0576098'
    iq = _make_iq(msg_hex, lead=50)
    mag = preamble.magnitude(iq)
    hits = preamble.find_preambles(mag)
    assert hits == [50]

    decoded = ppm.demod(mag[hits[0] + 16: hits[0] + 16 + 224])
    assert decoded.hex().upper() == msg_hex
    assert crc.compute(decoded) == 0
    f = modes.parse(decoded)
    assert f.icao == '4840D6'
    ident = adsb.decode_identification(f.me)
    assert ident.callsign == 'KLM1023'


def test_pipeline_via_decoder_class():
    """Decoder sinifi tum aciklik."""
    from decoder.pipeline import Decoder
    from aircraft.tracker import AircraftTracker

    tracker = AircraftTracker()
    dec = Decoder(tracker)

    msg_hex = '8D4840D6202CC371C32CE0576098'
    iq = _make_iq(msg_hex, lead=100)
    dec.process(iq)

    assert dec.stats['preamble_hits'] >= 1
    assert dec.stats['crc_ok'] == 1
    assert dec.stats['df17_decoded'] == 1
    assert tracker.count() == 1
    snap = tracker.snapshot()
    assert snap[0]['icao'] == '4840D6'
    assert snap[0]['callsign'] == 'KLM1023'

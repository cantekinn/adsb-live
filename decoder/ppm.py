"""
Mode-S Pulse Position Modulation (PPM) demod.

Her 1 us'lik bit penceresi iki yarim'a bolunur (her biri 0.5 us).
- Ilk yarim yuksek > ikinci yarim -> bit = 1
- Ikinci yarim yuksek > ilk yarim -> bit = 0

2 MS/s ornekleme -> her bit 2 ornek (ornek0=ilk yarim, ornek1=ikinci yarim).
"""

import numpy as np
from config import LONG_MSG_BITS

SHORT_MSG_BITS = 56


def _demod_bits(samples: np.ndarray, n_bits: int) -> bytes | None:
    if len(samples) < n_bits * 2:
        return None
    s = samples[: n_bits * 2]
    pairs = s.reshape(n_bits, 2)
    if pairs.max() < 1e-3:
        return None
    bits = pairs[:, 0] > pairs[:, 1]
    nbytes = (n_bits + 7) // 8
    out = bytearray(nbytes)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (7 - (i % 8))
    return bytes(out)


def demod(samples_after_preamble: np.ndarray) -> bytes | None:
    """112-bit (uzun) Mode-S mesaj decode, 14 byte doner."""
    return _demod_bits(samples_after_preamble, LONG_MSG_BITS)


def demod_short(samples_after_preamble: np.ndarray) -> bytes | None:
    """56-bit (kisa) Mode-S mesaj decode, 7 byte doner."""
    return _demod_bits(samples_after_preamble, SHORT_MSG_BITS)

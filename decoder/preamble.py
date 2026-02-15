"""
Mode-S preamble dedektoru.

Preamble (8 us): 1 us'lik dort darbe, 0.5 us darbe genisligi.
Darbeler 0.0, 1.0, 3.5, 4.5 us'de.
2 MS/s ornekleme ile (0.5 us = 1 ornek), preamble = 16 ornek.

Beklenen yuksek ornekler:  0, 2, 7, 9
Beklenen dusuk ornekler:   1, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 15
"""

import numpy as np
from config import (
    PREAMBLE_LEN, PREAMBLE_HIGH_IDX, PREAMBLE_LOW_IDX,
    PREAMBLE_THRESHOLD, LONG_MSG_SAMPLES,
)


def magnitude(iq: np.ndarray) -> np.ndarray:
    """complex IQ -> magnitude (float32)."""
    # np.abs hizli; alternatif: i*i + q*q
    return np.abs(iq).astype(np.float32)


def find_preambles(mag: np.ndarray) -> list[int]:
    """
    Magnitude akimi uzerinde threshold-based preamble dedektoru + matched filter
    quality skoru.

    Aday tespiti: min(highs) > THR * max(lows) ile hizli filtre.
    Sonra skor: corr(slice, ideal_preamble) - kotu skorlu adaylari elenir.
    """
    n = len(mag)
    needed = PREAMBLE_LEN + LONG_MSG_SAMPLES
    if n < needed:
        return []

    high_arr = np.stack([mag[i: n - needed + i + 1] for i in PREAMBLE_HIGH_IDX])
    low_arr = np.stack([mag[i: n - needed + i + 1] for i in PREAMBLE_LOW_IDX])

    high_min = high_arr.min(axis=0)
    low_max = low_arr.max(axis=0)

    candidates = np.where(
        (high_min > PREAMBLE_THRESHOLD * low_max) & (high_min > 0)
    )[0]

    # Matched filter ideal preamble (16 ornek): high at 0,2,7,9; rest low
    ideal = np.zeros(PREAMBLE_LEN, dtype=np.float32)
    for i in PREAMBLE_HIGH_IDX:
        ideal[i] = 1.0
    # Negatif weight for lows (boylece tum slice ortalamasinin ezilmesi engellenir)
    for i in PREAMBLE_LOW_IDX:
        ideal[i] = -0.3
    # Normalize
    ideal = ideal / np.linalg.norm(ideal)

    # Ardisik elimine
    hits: list[int] = []
    last = -PREAMBLE_LEN
    for idx in candidates.tolist():
        if idx - last < PREAMBLE_LEN:
            continue
        # Matched filter quality
        slice_ = mag[idx:idx + PREAMBLE_LEN]
        norm = np.linalg.norm(slice_) + 1e-9
        score = float(np.dot(slice_, ideal) / norm)
        # 0.5 esigi ile kalitesiz tepe noktalarini at (genelde gurultu)
        if score < 0.45:
            continue
        hits.append(idx)
        last = idx
    return hits

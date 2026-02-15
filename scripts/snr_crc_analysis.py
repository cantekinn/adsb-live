"""
SNR vs CRC pass rate analizi.

Bir IQ kaydini al, sinyal seviyesini farkli SNR'lere indirip
decoder'in basari oranini olc. LNA katkisini analiz etmek icin:
  - Olculen mevcut SNR (kullanici LNA varken)
  - Hesapsal: LNA olmasaydi SNR ne olurdu (~-15 dB cikis kaybi)

Cikis: SNR (dB) vs CRC pass rate egrisi, PNG + CSV.
"""

import argparse
import sys
import os
import time
import math
import numpy as np
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decoder.pipeline import Decoder
from aircraft.tracker import AircraftTracker


def load_iq(path: str) -> np.ndarray:
    """Load IQ from .wav or .bin/.iq, normalize."""
    lower = path.lower()
    if lower.endswith('.wav'):
        from scipy.signal import resample_poly
        w = wave.open(path, 'rb')
        fs = w.getframerate()
        raw = w.readframes(w.getnframes())
        w.close()
        d = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        iq = (d[0::2] + 1j * d[1::2]).astype(np.complex64)
        if fs != 2_000_000:
            from math import gcd
            g = gcd(fs, 2_000_000)
            iq = resample_poly(iq, 2_000_000 // g, fs // g).astype(np.complex64)
        return iq
    raw = np.fromfile(path, dtype=np.uint8)
    iq = (raw.astype(np.float32) - 127.5) / 127.5
    return (iq[0::2] + 1j * iq[1::2]).astype(np.complex64)


def measure_snr(iq: np.ndarray) -> float:
    """Sinyal/gurultu oranini magnitude histogram'dan tahmin et (dB)."""
    mag = np.abs(iq)
    noise_floor = np.percentile(mag, 50)    # medyan
    signal_peak = np.percentile(mag, 99.5)  # peak
    return 20 * np.log10((signal_peak + 1e-9) / (noise_floor + 1e-9))


def add_noise(iq: np.ndarray, target_snr_db: float) -> np.ndarray:
    """Mevcut sinyale ek AWGN ekleyerek hedef SNR'a indir.

    Mevcut SNR'i tahmin et, hedeften yuksekse fark kadar gurultu ekle.
    """
    current = measure_snr(iq)
    if target_snr_db >= current:
        return iq
    # Eklemeli gurultu varyansi: hedef SNR'a inecek sekilde
    mag = np.abs(iq)
    sig_pow = np.percentile(mag, 99.5) ** 2
    target_noise_pow = sig_pow / (10 ** (target_snr_db / 10))
    current_noise_pow = np.percentile(mag, 50) ** 2
    extra_pow = max(0, target_noise_pow - current_noise_pow)
    sigma = math.sqrt(extra_pow / 2)
    noise = (np.random.normal(0, sigma, len(iq))
             + 1j * np.random.normal(0, sigma, len(iq))).astype(np.complex64)
    return iq + noise


def decode_run(iq: np.ndarray) -> dict:
    t = AircraftTracker()
    dec = Decoder(t)
    for s in range(0, len(iq), 256 * 1024):
        dec.process(iq[s:s + 256 * 1024])
    return {
        'preamble': dec.stats['preamble_hits'],
        'crc_ok': dec.stats['crc_ok'],
        'df17': dec.stats['df17_decoded'],
        'fix1': dec.stats['fixed_1bit'],
        'fix2': dec.stats['fixed_2bit'],
        'aircraft': t.count(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iq_file')
    ap.add_argument('--snr-range', default='-10:30:2',
                    help='SNR taramasi: start:stop:step (dB)')
    ap.add_argument('--out-csv', default='snr_crc.csv')
    ap.add_argument('--out-png', default='snr_crc.png')
    args = ap.parse_args()

    print(f'Yukleme: {args.iq_file}')
    iq = load_iq(args.iq_file)
    base_snr = measure_snr(iq)
    print(f'Ham SNR: {base_snr:.1f} dB')
    print(f'Sample: {len(iq):,} ({len(iq)/2e6:.1f} sn)')

    start, stop, step = map(float, args.snr_range.split(':'))
    snr_list = np.arange(start, stop + step / 2, step)

    results = []
    for target_snr in snr_list:
        if target_snr > base_snr:
            continue  # Sinyali yukseltemiyoruz
        np.random.seed(42)
        iq_noisy = add_noise(iq.copy(), target_snr)
        actual = measure_snr(iq_noisy)
        t0 = time.time()
        r = decode_run(iq_noisy)
        dt = time.time() - t0
        rate = r['crc_ok'] / max(1, r['preamble'])
        print(f'SNR target={target_snr:5.1f} actual={actual:5.1f}  '
              f'preamble={r["preamble"]:>5}  CRC={r["crc_ok"]:>5} '
              f'({rate*100:4.1f}%)  ucak={r["aircraft"]:>3}  ({dt:.1f}s)')
        results.append({'snr_target': target_snr, 'snr_actual': actual, **r,
                        'pass_rate': rate})

    # CSV
    with open(args.out_csv, 'w') as f:
        f.write('snr_target,snr_actual,preamble,crc_ok,df17,fix1,fix2,aircraft,pass_rate\n')
        for r in results:
            f.write(f"{r['snr_target']:.2f},{r['snr_actual']:.2f},"
                    f"{r['preamble']},{r['crc_ok']},{r['df17']},"
                    f"{r['fix1']},{r['fix2']},{r['aircraft']},{r['pass_rate']:.4f}\n")
    print(f'CSV: {args.out_csv}')

    # PNG (varsa matplotlib)
    try:
        import matplotlib.pyplot as plt
        snrs = [r['snr_actual'] for r in results]
        rates = [r['pass_rate'] * 100 for r in results]
        n_acs = [r['aircraft'] for r in results]

        fig, ax1 = plt.subplots(figsize=(9, 5))
        ax1.plot(snrs, rates, 'o-', color='#4cc9f0', label='CRC pass rate')
        ax1.set_xlabel('SNR (dB)')
        ax1.set_ylabel('CRC pass rate (%)', color='#4cc9f0')
        ax1.tick_params(axis='y', labelcolor='#4cc9f0')
        ax1.set_ylim(0, 105)
        ax1.grid(True, alpha=0.3)

        ax2 = ax1.twinx()
        ax2.plot(snrs, n_acs, 's--', color='#f59e0b', label='Unique aircraft', alpha=0.7)
        ax2.set_ylabel('Unique aircraft', color='#f59e0b')
        ax2.tick_params(axis='y', labelcolor='#f59e0b')

        ax1.set_title(f'ADS-B Decoder: SNR vs Performance ({os.path.basename(args.iq_file)})')
        plt.tight_layout()
        plt.savefig(args.out_png, dpi=120)
        print(f'PNG: {args.out_png}')
    except ImportError:
        print('matplotlib kurulu degil, PNG yok (pip install matplotlib)')


if __name__ == '__main__':
    main()

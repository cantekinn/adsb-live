"""
LNA katkisi analiz scripti.

Bir IQ kaydini kullanarak hesaplar:
  1. Mevcut SNR (LNA varken)
  2. LNA'siz tahmini SNR: SNR_no_LNA = SNR_LNA - (G_LNA - NF_total_diff)
     Friis: NF_total = NF_LNA + (NF_2 - 1) / G_LNA
            G_LNA = 14 dB, NF_LNA = 0.75 dB (BFP740 typical)
            NF_RX (RTL2832U) = 7 dB
            Bizim 3-katli LNA + RX bandinda
  3. Her iki SNR'da decoder pass rate ve gorulebilen ucak sayisi
  4. Sonuc raporu: dB cinsinden iyilesme + uçak sayisi artisi

BTU EEM bitirme tezi BFP740FESD 3-katli 2.4 GHz LNA icin uyarlanmis
(1090 MHz ADS-B icin parametreler farkli ama metodoloji ayni).
"""

import argparse
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.snr_crc_analysis import load_iq, measure_snr, add_noise, decode_run


def friis_total_nf_db(nf_stages: list, gains_db: list) -> float:
    """Friis kaskat gurultu rakami hesabi. dB cinsinden."""
    nf_lin = [10**(nf/10) for nf in nf_stages]
    g_lin = [10**(g/10) for g in gains_db]
    total = nf_lin[0]
    cumg = 1.0
    for i in range(1, len(nf_lin)):
        cumg *= g_lin[i - 1]
        total += (nf_lin[i] - 1) / cumg
    return 10 * np.log10(total)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('iq_file')
    ap.add_argument('--lna-gain', type=float, default=30.0,
                    help='3-katli LNA toplam kazanc (dB), default 30')
    ap.add_argument('--lna-nf', type=float, default=0.85,
                    help='LNA cumulative NF (dB), default 0.85')
    ap.add_argument('--rx-nf', type=float, default=7.0,
                    help='RTL2832U NF (dB), default 7')
    args = ap.parse_args()

    print('LNA Katkisi Analizi')
    print('=' * 60)

    # Sistem NF hesabi
    nf_with = friis_total_nf_db([args.lna_nf, args.rx_nf], [args.lna_gain])
    nf_without = args.rx_nf
    snr_improvement = nf_without - nf_with
    print(f'LNA var:  NF = {nf_with:.2f} dB')
    print(f'LNA yok:  NF = {nf_without:.2f} dB')
    print(f'\u0394SNR  : {snr_improvement:+.2f} dB  (LNA katkisi)')
    print()

    iq = load_iq(args.iq_file)
    measured_snr = measure_snr(iq)
    print(f'Olculen SNR (LNA var): {measured_snr:.1f} dB')
    print()

    # Decode iki senaryoda
    print(f'A. Mevcut SNR ({measured_snr:.1f} dB - LNA var):')
    r_with = decode_run(iq)
    print(f'   Preamble={r_with["preamble"]}, CRC ok={r_with["crc_ok"]}, '
          f'pass rate={r_with["crc_ok"]/max(1,r_with["preamble"])*100:.1f}%, '
          f'ucak={r_with["aircraft"]}')

    target_snr_no_lna = measured_snr - snr_improvement
    print()
    print(f'B. Hesapsal SNR ({target_snr_no_lna:.1f} dB - LNA yok):')
    np.random.seed(42)
    iq_no_lna = add_noise(iq.copy(), target_snr_no_lna)
    r_without = decode_run(iq_no_lna)
    print(f'   Preamble={r_without["preamble"]}, CRC ok={r_without["crc_ok"]}, '
          f'pass rate={r_without["crc_ok"]/max(1,r_without["preamble"])*100:.1f}%, '
          f'ucak={r_without["aircraft"]}')

    print()
    print('=' * 60)
    print('SONUC:')
    if r_without["preamble"] > 0:
        pass_rate_gain = (r_with["crc_ok"]/max(1,r_with["preamble"])
                         - r_without["crc_ok"]/max(1,r_without["preamble"])) * 100
    else:
        pass_rate_gain = float('inf')
    ac_gain = r_with["aircraft"] - r_without["aircraft"]
    print(f'  CRC pass rate iyilesmesi: +{pass_rate_gain:.1f} percentage point')
    print(f'  Gorulen ucak sayisi    : +{ac_gain} ucak ({r_without["aircraft"]} -> {r_with["aircraft"]})')
    print(f'  Mesaj basari sayisi    : {r_with["crc_ok"]} vs {r_without["crc_ok"]} '
          f'({r_with["crc_ok"]/max(1,r_without["crc_ok"]):.1f}x daha fazla)')


if __name__ == '__main__':
    main()

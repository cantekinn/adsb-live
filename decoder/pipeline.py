"""
Decoder pipeline - SDR'den gelen IQ chunklarini alip uçak guncellemelerine cevirir.

IQ -> magnitude -> preamble hits -> PPM demod -> CRC -> Mode-S parse -> ADS-B decode
"""

import logging
import numpy as np

from . import preamble as pre
from . import ppm
from . import crc as crc_mod
from . import modes
from . import adsb
from . import commb

from aircraft.tracker import AircraftTracker

log = logging.getLogger(__name__)


class Decoder:
    """Stateless icin ozlu - sadece tracker referansi tutar."""

    def __init__(self, tracker: AircraftTracker):
        self.tracker = tracker
        self.stats = {
            'samples_processed': 0,
            'preamble_hits': 0,
            'crc_ok': 0,
            'df17_decoded': 0,
            'df11_confirmed': 0,
            'fixed_1bit': 0,
            'fixed_2bit': 0,
            'commb_callsign': 0,
        }
        # DF11 dogrulamasi icin: DF17 ile CRC pass eden ICAO'larin set'i
        self._known_icaos: set[str] = set()

    @staticmethod
    def _flip_bit_correct(msg: bytes) -> bytes | None:
        """1-bit hata duzeltme: her biti tek tek flip et, CRC sifir mi bak."""
        ba = bytearray(msg)
        n_bits = len(ba) * 8
        for i in range(n_bits):
            ba[i // 8] ^= 1 << (7 - (i % 8))
            if crc_mod.compute(bytes(ba)) == 0:
                return bytes(ba)
            ba[i // 8] ^= 1 << (7 - (i % 8))
        return None

    @staticmethod
    def _flip_2bit_correct(msg: bytes) -> bytes | None:
        """2-bit hata duzeltme: ME bolgesinde (bit 32..87) ciftli flip dene.

        Buyuk: 112*111/2 = 6216 dene. Sadece ME alanini hedefliyoruz
        cunku CRC alani 24 bit, ic icine girince yanlis pozitifi artar.
        Sadece kuyrukta kalanlar icin (1-bit basarisiz olunca) fallback.
        """
        ba = bytearray(msg)
        # ME bolgesi: bit 32..87 (56 bit). DF/CA/ICAO + CRC korunsun.
        candidates = list(range(32, 88))
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                bi, bj = candidates[i], candidates[j]
                ba[bi // 8] ^= 1 << (7 - (bi % 8))
                ba[bj // 8] ^= 1 << (7 - (bj % 8))
                if crc_mod.compute(bytes(ba)) == 0:
                    return bytes(ba)
                ba[bi // 8] ^= 1 << (7 - (bi % 8))
                ba[bj // 8] ^= 1 << (7 - (bj % 8))
        return None

    def process(self, iq: np.ndarray) -> None:
        """Bir IQ chunk."""
        self.stats['samples_processed'] += len(iq)
        mag = pre.magnitude(iq)
        hits = pre.find_preambles(mag)
        self.stats['preamble_hits'] += len(hits)

        from config import PREAMBLE_LEN, LONG_MSG_SAMPLES

        for h in hits:
            start = h + PREAMBLE_LEN
            # ±1 sample offset dene (timing jitter)
            decoded_long = None
            decoded_short = None
            for off in (0, -1, 1):
                s = start + off
                if s < 0 or s + LONG_MSG_SAMPLES > len(mag):
                    continue
                slice_long = mag[s : s + LONG_MSG_SAMPLES]

                # Uzun (112-bit) dene
                msg_long = ppm.demod(slice_long)
                if msg_long is not None and crc_mod.compute(msg_long) == 0:
                    decoded_long = msg_long
                    break

                # Kisa (56-bit) DF11 dene - sadece DF==11 ise
                msg_short = ppm.demod_short(slice_long[: 56 * 2])
                if msg_short is not None and decoded_short is None:
                    df = (msg_short[0] >> 3) & 0x1F
                    if df == 11:
                        decoded_short = msg_short

            # Uzun mesaj bulunamadi - 1-bit error correction dene
            if decoded_long is None:
                for off in (0, -1, 1):
                    s = start + off
                    if s < 0 or s + LONG_MSG_SAMPLES > len(mag):
                        continue
                    msg = ppm.demod(mag[s : s + LONG_MSG_SAMPLES])
                    if msg is None:
                        continue
                    # 1-bit fix sadece DF17 icin gerekli (CRC=0 dogrulamasi var)
                    df = (msg[0] >> 3) & 0x1F
                    if df != 17:
                        continue
                    fixed = self._flip_bit_correct(msg)
                    if fixed is not None:
                        decoded_long = fixed
                        self.stats['fixed_1bit'] += 1
                        break
                # 1-bit basarisiz, 2-bit dene (sadece DF17 icin, pahali)
                if decoded_long is None:
                    for off in (0, -1, 1):
                        s = start + off
                        if s < 0 or s + LONG_MSG_SAMPLES > len(mag):
                            continue
                        msg = ppm.demod(mag[s : s + LONG_MSG_SAMPLES])
                        if msg is None: continue
                        if ((msg[0] >> 3) & 0x1F) != 17: continue
                        fixed = self._flip_2bit_correct(msg)
                        if fixed is not None:
                            decoded_long = fixed
                            self.stats['fixed_2bit'] += 1
                            break

            if decoded_long is not None:
                self.stats['crc_ok'] += 1
                frame = modes.parse(decoded_long)
                if frame is None:
                    continue
                if frame.df == 17:
                    self.stats['df17_decoded'] += 1
                    self._known_icaos.add(frame.icao)
                    self.tracker.update(frame.icao)  # ICAO'yu ekle
                    self._dispatch_adsb(frame)
            elif decoded_short is not None:
                # DF11 - sadece DF17 ile dogrulanmis ICAO'lardan kabul et
                icao = decoded_short[1:4].hex().upper()
                if icao in self._known_icaos:
                    self.stats['df11_confirmed'] += 1
                    self.tracker.update(icao)
            else:
                # DF20/21 Comm-B - whitelist ICAO ile cross-validate
                for off in (0, -1, 1):
                    s = start + off
                    if s < 0 or s + LONG_MSG_SAMPLES > len(mag):
                        continue
                    msg = ppm.demod(mag[s : s + LONG_MSG_SAMPLES])
                    if msg is None:
                        continue
                    df = (msg[0] >> 3) & 0x1F
                    if df not in (20, 21):
                        continue
                    # CRC XOR PI -> ICAO candidate
                    icao_cand = commb.extract_icao_from_pi(msg)
                    if icao_cand not in self._known_icaos:
                        continue
                    # Comm-B icerik dogrulu kontrolleri (BDS 2,0 / 4,0 / 5,0 / 6,0)
                    self.tracker.update(icao_cand)  # heartbeat
                    cs = commb.decode_bds20_callsign(msg)
                    if cs:
                        self.stats['commb_callsign'] += 1
                        self.tracker.update(icao_cand, callsign=cs)
                    # BDS 4,0
                    sv = commb.decode_bds40(msg)
                    if sv is not None:
                        fields = {}
                        if sv.mcp_alt is not None: fields['mcp_alt'] = sv.mcp_alt
                        if sv.fms_alt is not None: fields['fms_alt'] = sv.fms_alt
                        if sv.baro_set is not None: fields['baro_set'] = sv.baro_set
                        if fields:
                            self.stats['commb_bds40'] = self.stats.get('commb_bds40', 0) + 1
                            self.tracker.update(icao_cand, **fields)
                    # BDS 5,0
                    tt = commb.decode_bds50(msg)
                    if tt is not None:
                        fields = {}
                        if tt.roll is not None: fields['roll'] = tt.roll
                        if tt.track_rate is not None: fields['track_rate'] = tt.track_rate
                        if tt.tas is not None: fields['tas'] = tt.tas
                        if fields:
                            self.stats['commb_bds50'] = self.stats.get('commb_bds50', 0) + 1
                            self.tracker.update(icao_cand, **fields)
                    # BDS 6,0
                    hs = commb.decode_bds60(msg)
                    if hs is not None:
                        fields = {}
                        if hs.mag_heading is not None: fields['mag_heading'] = hs.mag_heading
                        if hs.ias is not None: fields['ias'] = hs.ias
                        if hs.mach is not None: fields['mach'] = hs.mach
                        if hs.baro_rate is not None: fields['baro_rate'] = hs.baro_rate
                        if hs.inertial_rate is not None: fields['inertial_rate'] = hs.inertial_rate
                        if fields:
                            self.stats['commb_bds60'] = self.stats.get('commb_bds60', 0) + 1
                            self.tracker.update(icao_cand, **fields)
                    break

    # --------------------------------------------------------
    def _dispatch_adsb(self, f: modes.ModeSFrame) -> None:
        tc = modes.get_tc(f.me)
        if 1 <= tc <= 4:
            ident = adsb.decode_identification(f.me)
            # Pattern hafizasina ekle (gelecekte tamamlama icin)
            from aircraft import analytics
            analytics.remember_callsign(f.icao, ident.callsign)
            self.tracker.update(
                f.icao,
                callsign=ident.callsign,
                category=ident.category,
            )
        elif 5 <= tc <= 8:
            # Surface position - yer trafigi
            sp = adsb.decode_surface_position(f.me)
            self.tracker.update_position(
                f.icao,
                lat_cpr=sp.lat_cpr,
                lon_cpr=sp.lon_cpr,
                f=sp.f,
                altitude=None,  # surface, alt yok
            )
            fields = {'on_ground': True}
            if sp.speed is not None:
                fields['speed'] = sp.speed
            if sp.heading is not None:
                fields['heading'] = sp.heading
            self.tracker.update(f.icao, **fields)
        elif 9 <= tc <= 18 or 20 <= tc <= 22:
            pos = adsb.decode_airborne_position(f.me)
            self.tracker.update_position(
                f.icao,
                lat_cpr=pos.lat_cpr,
                lon_cpr=pos.lon_cpr,
                f=pos.f,
                altitude=pos.altitude,
            )
            self.tracker.update(f.icao, on_ground=False)
        elif tc == 19:
            v = adsb.decode_velocity(f.me)
            if v is not None:
                self.tracker.update(
                    f.icao,
                    speed=v.speed,
                    heading=v.heading,
                    vertical_rate=v.vertical_rate,
                    speed_type=v.speed_type,
                )
        elif tc == 31:
            ops = adsb.decode_operational_status(f.me)
            self.tracker.update(
                f.icao,
                adsb_version=ops.version,
                nic=ops.nic,
                nacp=ops.nacp,
            )

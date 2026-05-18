"""
Entry point.

Iki ana thread:
  - SDR capture     (RtlCapture)  -> IQ kuyrugu doldurur
  - Decoder         (DecoderThread) -> IQ -> Aircraft tracker

Ana thread Flask-SocketIO web sunucusunu calistirir.

Kullanim:
    python main.py                 # canli SDR
    python main.py --iq file.iq    # dosyadan IQ tukem (test)
"""

# eventlet monkey patch web app'ten ONCE
import eventlet
eventlet.monkey_patch()

import argparse
import logging
import queue
import sys
import threading
import os
import time

import numpy as np

from config import QUEUE_MAX, CAPTURE_CHUNK
from aircraft.tracker import AircraftTracker
from decoder.pipeline import Decoder

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s',
)
log = logging.getLogger('main')

# Feeder thread'i decoder.stats'a yazabilsin diye paylasilan referans
_shared_stats: dict | None = None


class DecoderThread(threading.Thread):
    daemon = True
    name = 'Decoder'

    def __init__(self, iq_q: queue.Queue, decoder: Decoder):
        super().__init__()
        self.q = iq_q
        self.dec = decoder
        self._stop = threading.Event()

    def run(self) -> None:
        log.info('Decoder thread baslatildi')
        while not self._stop.is_set():
            try:
                iq = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.dec.process(iq)
            except Exception:
                log.exception('decoder.process hatasi')

    def stop(self) -> None:
        self._stop.set()


class PrunerThread(threading.Thread):
    daemon = True
    name = 'Pruner'

    def __init__(self, tracker: AircraftTracker):
        super().__init__()
        self.tracker = tracker
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            time.sleep(5.0)
            n = self.tracker.prune()
            if n:
                log.info('%d uçak timeout ile silindi', n)

    def stop(self) -> None:
        self._stop.set()


def _read_wav_iq(path: str) -> tuple[np.ndarray, int]:
    """SDRangel-style 16-bit stereo (ch0=I, ch1=Q) WAV oku."""
    import wave
    with wave.open(path, 'rb') as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        fs = w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2 or nch != 2:
        raise ValueError(f'Beklenmedik WAV: {sw*8} bit, {nch} ch')
    d = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return (d[0::2] + 1j * d[1::2]).astype(np.complex64), fs


def feed_iq_file(path: str, iq_q: queue.Queue, speed: float = 0.0) -> None:
    """
    IQ dosyasini decoder kuyruguna besle.

    Desteklenen formatlar (uzantiya gore):
      .wav         - 16-bit signed stereo (SDRangel), oto 2 MS/s'ye resample
      .bin / .iq   - rtl_sdr raw uint8 interleaved IQ @ 2 MS/s

    speed:
      0   -> mumkun oldugunca hizli
      1.0 -> gercek zamanli (canli SDR'ymis gibi)
      2.0 -> 2x hizli vs.
    """
    log.info('IQ dosyasi okunuyor: %s', path)
    lower = path.lower()
    fs = 2_000_000
    if lower.endswith('.wav'):
        # WAV hala tum dosyayi okur (genelde <1 GB)
        iq_all, fs_in = _read_wav_iq(path)
        log.info('WAV: %d ornek @ %d Hz (%.1f s)',
                 len(iq_all), fs_in, len(iq_all) / fs_in)
        if fs_in != 2_000_000:
            from math import gcd
            from scipy.signal import resample_poly
            g = gcd(fs_in, 2_000_000)
            up, down = 2_000_000 // g, fs_in // g
            log.info('Resample %d -> 2 MS/s (up=%d, down=%d)',
                     fs_in, up, down)
            iq_all = resample_poly(iq_all, up, down).astype(np.complex64)
        total_samples = len(iq_all)
        iq_iter = lambda: (iq_all[i:i + CAPTURE_CHUNK]
                           for i in range(0, total_samples, CAPTURE_CHUNK))
    else:
        # BIN dosyasini streaming oku - GB'larca olabilir
        file_size = os.path.getsize(path)
        total_samples = file_size // 2  # uint8 IQ pair = 2 byte
        log.info('BIN: %d byte -> %d ornek (%.1f s)',
                 file_size, total_samples, total_samples / fs)

        def _bin_chunks():
            with open(path, 'rb') as fh:
                while True:
                    raw = fh.read(CAPTURE_CHUNK * 2)  # I+Q bytes
                    if not raw:
                        return
                    arr = np.frombuffer(raw, dtype=np.uint8)
                    iq_c = (arr[0::2].astype(np.float32) - 127.5) / 127.5
                    iq_c = iq_c + 1j * ((arr[1::2].astype(np.float32) - 127.5) / 127.5)
                    yield iq_c.astype(np.complex64)
        iq_iter = _bin_chunks

    log.info('IQ: %d ornek = %.1f s @ 2 MS/s',
             total_samples, total_samples / fs)

    # Progress bilgisini stats'a koy (Web UI gosterecek)
    global _shared_stats
    if _shared_stats is not None:
        _shared_stats['feed_total_seconds'] = total_samples / fs
        _shared_stats['feed_speed'] = speed if speed > 0 else 0
        _shared_stats['feed_mode'] = 'file'

    chunk_dt = CAPTURE_CHUNK / fs
    t_start = time.time()
    chunks_sent = 0
    for chunk in iq_iter():
        iq_q.put(chunk)
        chunks_sent += 1
        if speed > 0:
            target_wall = chunks_sent * chunk_dt / speed
            elapsed = time.time() - t_start
            slack = target_wall - elapsed
            if slack > 0:
                time.sleep(slack)
    log.info('IQ besleme bitti')


def main() -> int:
    ap = argparse.ArgumentParser(description='ADS-B Live Tracker')
    ap.add_argument('--iq', nargs='+',
                    help='Canli SDR yerine IQ dosyasi/dosyalari (.wav veya .bin). '
                         'Birden cok dosya verilirse sirayla beslenir.')
    ap.add_argument('--loop', action='store_true',
                    help='Dosyalari bitince bastan tekrar oynat (sonsuz)')
    ap.add_argument('--speed', type=float, default=0.0,
                    help='Dosya beslemeleri pacing (0=hizli, 1=realtime, 2=2x)')
    ap.add_argument('--ref-lat', type=float, default=None,
                    help='Referans enlem (local CPR icin)')
    ap.add_argument('--ref-lon', type=float, default=None,
                    help='Referans boylam')
    ap.add_argument('--no-web', action='store_true',
                    help='Web UI baslatma (sadece konsol log)')
    ap.add_argument('--opensky', action='store_true',
                    help='OpenSky Network live API feed (SDR/IQ gerek yok)')
    ap.add_argument('--opensky-bbox',
                    choices=['world', 'tr', 'tr-eu', 'uk'], default='tr-eu',
                    help='OpenSky cografi filtre')
    ap.add_argument('--opensky-user', default=None,
                    help='OpenSky basic auth kullanici adi (opsiyonel, rate up)')
    ap.add_argument('--opensky-pass', default=None,
                    help='OpenSky basic auth sifresi')
    ap.add_argument('--adsbfi', action='store_true',
                    help='adsb.fi / airplanes.live / adsb.lol public feed (auth gerekmez)')
    ap.add_argument('--adsbfi-source', default='airplaneslive',
                    choices=['adsbfi', 'airplaneslive', 'adsblol'],
                    help='Aggregator secimi (airplaneslive default, en stabil)')
    ap.add_argument('--adsbfi-radius', type=int, default=250,
                    help='Radius (NM, max 250)')
    ap.add_argument('--db', default=None,
                    help='SQLite persistence dosyasi (orn: data/adsb.db)')
    args = ap.parse_args()

    tracker = AircraftTracker(ref_lat=args.ref_lat, ref_lon=args.ref_lon)
    iq_q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
    decoder = Decoder(tracker)

    global _shared_stats
    _shared_stats = decoder.stats

    dec_thread = DecoderThread(iq_q, decoder)
    dec_thread.start()
    pruner = PrunerThread(tracker)
    pruner.start()

    # SQLite persistence (opsiyonel)
    persist = None
    if args.db:
        from storage.db import Persistence
        persist = Persistence(args.db, tracker, flush_interval=5.0)
        persist.start()

    if args.adsbfi:
        from opensky.adsbfi import AdsbFiFeed
        if args.ref_lat is None or args.ref_lon is None:
            log.error('adsb.fi icin --ref-lat ve --ref-lon zorunlu')
            return 1
        feed = AdsbFiFeed(tracker, lat=args.ref_lat, lon=args.ref_lon,
                          radius_nm=args.adsbfi_radius,
                          source=args.adsbfi_source,
                          stats=decoder.stats)
        if _shared_stats is not None:
            _shared_stats['feed_mode'] = f'adsbfi:{args.adsbfi_source}'
        feed.start()
        if args.no_web:
            try:
                while True:
                    time.sleep(5.0)
                    _print_summary(tracker, decoder)
            except KeyboardInterrupt:
                feed.stop()
                return 0
    elif args.opensky:
        from opensky.feed import OpenSkyFeed, BBOX_WORLD, BBOX_TR_EU, BBOX_TURKEY, BBOX_UK
        bbox_map = {'world': BBOX_WORLD, 'tr': BBOX_TURKEY,
                    'tr-eu': BBOX_TR_EU, 'uk': BBOX_UK}
        feed = OpenSkyFeed(tracker, bbox=bbox_map[args.opensky_bbox],
                           stats=decoder.stats,
                           username=args.opensky_user,
                           password=args.opensky_pass)
        if _shared_stats is not None:
            _shared_stats['feed_mode'] = 'opensky'
            _shared_stats['feed_bbox'] = args.opensky_bbox
        feed.start()
        if args.no_web:
            try:
                while True:
                    time.sleep(5.0)
                    _print_summary(tracker, decoder)
            except KeyboardInterrupt:
                feed.stop()
                return 0
    elif args.iq:
        # dosya beslemesi ayri thread'de (web UI ile paralel)
        def _feed_all():
            while True:
                for i, p in enumerate(args.iq):
                    log.info('[%d/%d] dosya: %s', i + 1, len(args.iq), p)
                    if _shared_stats is not None:
                        _shared_stats['feed_current_file'] = p
                        _shared_stats['feed_file_index'] = i + 1
                        _shared_stats['feed_file_total'] = len(args.iq)
                    feed_iq_file(p, iq_q, args.speed)
                if not args.loop:
                    break
                log.info('Loop: bastan basliyor')
                # Loop'ta toplam progress bozulmasin
                if _shared_stats is not None:
                    _shared_stats['samples_processed'] = 0
            log.info('Tum dosyalar bitti')

        feeder = threading.Thread(target=_feed_all, daemon=True, name='Feeder')
        feeder.start()
        if args.no_web:
            feeder.join()
            time.sleep(2.0)
            _print_summary(tracker, decoder)
            return 0
    elif not args.opensky and not args.adsbfi:
        from sdr.rtl_capture import RtlCapture
        capture = RtlCapture(iq_q)
        capture.start()

    if args.no_web:
        try:
            while True:
                time.sleep(5.0)
                _print_summary(tracker, decoder)
        except KeyboardInterrupt:
            return 0

    web_config = {
        'ref_lat': args.ref_lat,
        'ref_lon': args.ref_lon,
        'mode': 'opensky' if args.opensky else ('file' if args.iq else 'sdr'),
    }
    from web.app import run as run_web
    try:
        run_web(tracker, stats=decoder.stats, db_path=args.db,
                config=web_config)
    except KeyboardInterrupt:
        log.info('Cikis...')
    return 0


def _print_summary(tracker: AircraftTracker, decoder: Decoder) -> None:
    s = decoder.stats
    log.info('Stats: %d ornek, %d preamble, %d CRC ok, %d DF17, %d ucak',
             s['samples_processed'], s['preamble_hits'],
             s['crc_ok'], s['df17_decoded'], tracker.count())


if __name__ == '__main__':
    sys.exit(main())

"""
RTL-SDR asenkron IQ capture.

pyrtlsdr async API kullanir; her chunk yakalandiginda verilen callback'i cagirir.
Bu modul callback'te IQ array'ini queue'ya basar - decoder thread oradan tuketir.
"""

import logging
import queue
import threading

import numpy as np

try:
    from rtlsdr import RtlSdr
except ImportError:
    RtlSdr = None  # test ortaminda olabilir

from config import (
    SAMPLE_RATE, CENTER_FREQ, SDR_GAIN, SDR_PPM, CAPTURE_CHUNK,
)

log = logging.getLogger(__name__)


class RtlCapture(threading.Thread):
    """SDR'yi okuyup IQ chunklarini kuyruga basar."""

    daemon = True

    def __init__(self, iq_queue: queue.Queue):
        super().__init__(name='RtlCapture')
        self.q = iq_queue
        self._stop_flag = threading.Event()
        self._sdr: RtlSdr | None = None

    # --------------------------------------------------------
    def run(self) -> None:
        if RtlSdr is None:
            raise RuntimeError(
                'pyrtlsdr yuklu degil. `pip install pyrtlsdr` ve Zadig ile '
                'WinUSB suruculusunu kur.'
            )

        sdr = RtlSdr()
        self._sdr = sdr
        sdr.sample_rate = SAMPLE_RATE
        sdr.center_freq = CENTER_FREQ
        if isinstance(SDR_GAIN, str):
            sdr.gain = SDR_GAIN
        else:
            sdr.gain = float(SDR_GAIN)
        if SDR_PPM:
            sdr.freq_correction = int(SDR_PPM)

        log.info('SDR ayarli: fs=%d Hz fc=%d Hz gain=%s',
                 sdr.sample_rate, sdr.center_freq, sdr.gain)

        try:
            # blocking - callback'te _on_samples cagrilir
            sdr.read_samples_async(self._on_samples, CAPTURE_CHUNK)
        except Exception as exc:
            log.error('SDR async hata: %s', exc)
        finally:
            try:
                sdr.close()
            except Exception:
                pass
            log.info('SDR kapandi.')

    # --------------------------------------------------------
    def _on_samples(self, samples, ctx) -> None:
        if self._stop_flag.is_set():
            try:
                self._sdr.cancel_read_async()
            except Exception:
                pass
            return
        # pyrtlsdr complex128 dondurur - bellek icin complex64'e dusur
        arr = np.asarray(samples, dtype=np.complex64)
        try:
            self.q.put_nowait(arr)
        except queue.Full:
            # eski chunk'i at, bunu koy
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(arr)
            except queue.Full:
                pass  # gercekten kotu durum, atla

    # --------------------------------------------------------
    def stop(self) -> None:
        self._stop_flag.set()

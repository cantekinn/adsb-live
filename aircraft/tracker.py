"""
Uçak durum tablosu - ICAO -> Aircraft.

Decoder cagirir; web app okuyup snapshot alir.
Thread-safe (RLock).
"""

import threading
import time
import math
import logging

from .aircraft import Aircraft
from decoder.cpr import CprFrame, decode_global, decode_local
from config import AIRCRAFT_TIMEOUT_S, CPR_PAIR_TIMEOUT_S

log = logging.getLogger(__name__)

# Sanity check: makul olmayan zıplamaları reddet
MAX_GROUND_SPEED_KT = 1200.0   # commercial aircraft tavanı ~ 600 kt, marj
MAX_REF_RADIUS_NM = 300.0      # referansa max mesafe (RTL-SDR pratik menzili)
MIN_JUMP_NM = 50.0             # bu mesafe altinda her zaman kabul (false positive engelle)
EARTH_R_NM = 3440.065          # nautical miles


def _haversine_nm(lat1: float, lon1: float,
                  lat2: float, lon2: float) -> float:
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_NM * math.asin(math.sqrt(a))


class AircraftTracker:
    def __init__(self, ref_lat: float | None = None, ref_lon: float | None = None):
        self._aircraft: dict[str, Aircraft] = {}
        self._lock = threading.RLock()
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon

    # --------------------------------------------------------
    def _get_or_create(self, icao: str) -> Aircraft:
        ac = self._aircraft.get(icao)
        if ac is None:
            ac = Aircraft(icao=icao)
            self._aircraft[icao] = ac
        return ac

    # --------------------------------------------------------
    def update(self, icao: str, **fields) -> None:
        """Konum disindaki tum alanlar icin tek giris."""
        now = time.time()
        with self._lock:
            ac = self._get_or_create(icao)
            for k, v in fields.items():
                if v is not None:
                    setattr(ac, k, v)
            ac.last_seen = now
            ac.msg_count += 1

    # --------------------------------------------------------
    def update_position(self, icao: str, *, lat_cpr: int, lon_cpr: int,
                         f: int, altitude: int | None) -> None:
        """CPR frame al, mumkunse cozup lat/lon yaz."""
        now = time.time()
        with self._lock:
            ac = self._get_or_create(icao)
            if altitude is not None:
                ac.altitude = altitude
            ac.last_seen = now
            ac.msg_count += 1

            # CPR cache guncelle
            if f == 0:
                ac.even_lat_cpr = lat_cpr
                ac.even_lon_cpr = lon_cpr
                ac.even_t = now
            else:
                ac.odd_lat_cpr = lat_cpr
                ac.odd_lon_cpr = lon_cpr
                ac.odd_t = now

            # Global cozum dene
            new_lat = new_lon = None
            if (ac.even_t is not None and ac.odd_t is not None
                    and abs(ac.even_t - ac.odd_t) <= CPR_PAIR_TIMEOUT_S):
                even = CprFrame(icao=icao, f=0,
                                lat_cpr=ac.even_lat_cpr,
                                lon_cpr=ac.even_lon_cpr,
                                t=ac.even_t)
                odd = CprFrame(icao=icao, f=1,
                               lat_cpr=ac.odd_lat_cpr,
                               lon_cpr=ac.odd_lon_cpr,
                               t=ac.odd_t)
                res = decode_global(even, odd)
                if res is not None:
                    new_lat, new_lon = res

            # Global olmadiysa ve referans varsa local dene
            if new_lat is None and self.ref_lat is not None and self.ref_lon is not None:
                frame = CprFrame(icao=icao, f=f,
                                 lat_cpr=lat_cpr, lon_cpr=lon_cpr, t=now)
                # Lokali sadece zaten bir konumumuz yoksa ya da referansa yakinsa
                if ac.lat is None:
                    new_lat, new_lon = decode_local(
                        frame, self.ref_lat, self.ref_lon)

            if new_lat is None:
                return

            # Sanity check 1: referansa cok uzak mi (ilk konum icin)
            if (ac.lat is None and self.ref_lat is not None
                    and self.ref_lon is not None):
                d = _haversine_nm(self.ref_lat, self.ref_lon, new_lat, new_lon)
                if d > MAX_REF_RADIUS_NM:
                    log.warning('CPR reject %s: referansa %.0fnm uzak',
                                icao, d)
                    if f == 0:
                        ac.even_lat_cpr = ac.even_lon_cpr = ac.even_t = None
                    else:
                        ac.odd_lat_cpr = ac.odd_lon_cpr = ac.odd_t = None
                    return

            # Sanity check 2: onceki konumdan implicit hiz makul mu?
            # NOT: dosya speed>1 modunda wallclock dt suni kucuk olur, bu yuzden
            # kucuk mesafeleri (< MIN_JUMP_NM) her zaman gercek kabul ederiz.
            if ac.lat is not None and ac.lon is not None and ac.last_pos_t is not None:
                dt = now - ac.last_pos_t
                dist_nm = _haversine_nm(ac.lat, ac.lon, new_lat, new_lon)
                if dist_nm > MIN_JUMP_NM and dt > 0:
                    speed_kt = dist_nm / (dt / 3600.0)
                    if speed_kt > MAX_GROUND_SPEED_KT:
                        log.warning(
                            'CPR reject %s: %.0fnm in %.1fs (%.0fkt) %s -> %s',
                            icao, dist_nm, dt, speed_kt,
                            (round(ac.lat, 3), round(ac.lon, 3)),
                            (round(new_lat, 3), round(new_lon, 3)))
                        # Cache'i de gecersizle - bozuk frame'in iz birakmasin
                        if f == 0:
                            ac.even_lat_cpr = ac.even_lon_cpr = ac.even_t = None
                        else:
                            ac.odd_lat_cpr = ac.odd_lon_cpr = ac.odd_t = None
                        return

            ac.lat, ac.lon = new_lat, new_lon
            ac.last_pos_t = now
            ac.push_track(new_lat, new_lon)

    # --------------------------------------------------------
    def prune(self) -> int:
        """Eskileri temizle, atilan sayisini doner."""
        now = time.time()
        removed = 0
        with self._lock:
            stale = [icao for icao, ac in self._aircraft.items()
                     if now - ac.last_seen > AIRCRAFT_TIMEOUT_S]
            for icao in stale:
                del self._aircraft[icao]
                removed += 1
        return removed

    # --------------------------------------------------------
    def snapshot(self) -> list[dict]:
        """Web UI icin tum aktif uçaklarin dict listesi."""
        with self._lock:
            return [ac.to_dict() for ac in self._aircraft.values()]

    def count(self) -> int:
        with self._lock:
            return len(self._aircraft)

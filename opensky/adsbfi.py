"""
adsb.fi / airplanes.live / adsb.lol public aggregator feeder.

Hicbir auth gerekmez, sinirsiz. OpenSky'dan cok daha iyi.

API'lar:
  - adsb.fi:        https://api.adsb.fi/v2/lat/<lat>/lon/<lon>/dist/<nm>
  - airplanes.live: https://api.airplanes.live/v2/point/<lat>/<lon>/<nm>
  - adsb.lol:       https://api.adsb.lol/v2/point/<lat>/<lon>/<nm>

Hepsi ayni JSON formati (ADSBexchange v2 standardi).
"""

import logging
import threading
import time
import urllib.request
import urllib.error
import json

log = logging.getLogger(__name__)

SOURCES = {
    'adsbfi': lambda lat, lon, nm:
        f'https://api.adsb.fi/v2/lat/{lat}/lon/{lon}/dist/{nm}',
    'airplaneslive': lambda lat, lon, nm:
        f'https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}',
    'adsblol': lambda lat, lon, nm:
        f'https://api.adsb.lol/v2/point/{lat}/{lon}/{nm}',
}

DEFAULT_INTERVAL_S = 2.0


class AdsbFiFeed:
    """Public aggregator feeder.

    Tek bir noktayi referansla cevreyi sorgular. Max radius ~ 250 NM.
    Dunya capi icin: tekrarli sorgu birden cok point veya degisiklik.
    """

    def __init__(self, tracker, lat: float, lon: float, radius_nm: int = 250,
                 source: str = 'adsbfi', interval: float = DEFAULT_INTERVAL_S,
                 stats: dict | None = None):
        self.tracker = tracker
        self.lat = lat; self.lon = lon
        self.radius_nm = min(radius_nm, 250)  # API limiti
        self.source = source
        self.interval = interval
        self.stats = stats
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if source not in SOURCES:
            raise ValueError(f'Bilinmeyen source: {source}')

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f'AdsbFi-{self.source}')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _fetch(self) -> dict | None:
        url = SOURCES[self.source](self.lat, self.lon, self.radius_nm)
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'adsb-live/1.0 (educational, BTU EEM thesis)',
                'Accept': 'application/json',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            log.warning('%s HTTP %d', self.source, e.code)
            return None
        except Exception as e:
            log.warning('%s fetch hata: %s', self.source, e)
            return None

    def _ingest(self, data: dict) -> int:
        """ADSBexchange v2 format -> tracker.

        ac alanlari:
          hex, flight (callsign), r (registration), t (aircraft type),
          alt_baro (ft), alt_geom (ft), gs (kt), tas (kt), ias (kt),
          mach, track, true_heading, mag_heading,
          baro_rate (fpm), geom_rate (fpm),
          squawk, lat, lon, category, dbFlags
        """
        ac_list = data.get('ac') or data.get('aircraft') or []
        n = 0
        for ac in ac_list:
            try:
                icao = (ac.get('hex') or '').upper()
                if not icao or len(icao) != 6:
                    continue
                fields = {}
                cs = (ac.get('flight') or '').strip()
                if cs:
                    fields['callsign'] = cs
                # Alt: baro tercih
                alt = ac.get('alt_baro')
                if alt == 'ground':
                    fields['on_ground'] = True
                    alt = 0
                elif alt is None:
                    alt = ac.get('alt_geom')
                if isinstance(alt, (int, float)):
                    fields['altitude'] = int(alt)
                if ac.get('gs') is not None:
                    fields['speed'] = float(ac['gs'])
                hdg = ac.get('track') or ac.get('true_heading') or ac.get('mag_heading')
                if hdg is not None:
                    fields['heading'] = float(hdg)
                vr = ac.get('baro_rate') or ac.get('geom_rate')
                if vr is not None:
                    fields['vertical_rate'] = int(vr)
                if ac.get('squawk'):
                    fields['squawk'] = str(ac['squawk'])
                if ac.get('category'):
                    try:
                        # category 'A1', 'A5' formatinda - sadece 'A' kategorisi
                        cat = ac['category']
                        if cat.startswith('A') and len(cat) >= 2:
                            fields['category'] = int(cat[1])
                    except (ValueError, TypeError, AttributeError):
                        pass
                # Comm-B extras
                if ac.get('nav_altitude_mcp') is not None:
                    fields['mcp_alt'] = int(ac['nav_altitude_mcp'])
                if ac.get('nav_altitude_fms') is not None:
                    fields['fms_alt'] = int(ac['nav_altitude_fms'])
                if ac.get('nav_heading') is not None:
                    fields['mag_heading'] = float(ac['nav_heading'])
                if ac.get('mach') is not None:
                    fields['mach'] = float(ac['mach'])
                if ac.get('ias') is not None:
                    fields['ias'] = int(ac['ias'])
                if ac.get('tas') is not None:
                    fields['tas'] = float(ac['tas'])
                if ac.get('roll') is not None:
                    fields['roll'] = float(ac['roll'])

                self.tracker.update(icao, **fields)

                # Konum
                lat = ac.get('lat'); lon = ac.get('lon')
                if lat is not None and lon is not None:
                    with self.tracker._lock:
                        a = self.tracker._get_or_create(icao)
                        a.lat = lat; a.lon = lon
                        a.last_pos_t = time.time()
                        a.push_track(lat, lon)
                n += 1
            except Exception as e:
                log.debug('ac parse hata: %s', e)
        return n

    def _loop(self) -> None:
        log.info('AdsbFi feed (%s) basladi: lat=%.2f lon=%.2f r=%dNM interval=%.1fs',
                 self.source, self.lat, self.lon, self.radius_nm, self.interval)
        while not self._stop.is_set():
            t0 = time.time()
            data = self._fetch()
            if data:
                n = self._ingest(data)
                if self.stats is not None:
                    self.stats['feed_last_count'] = n
                    self.stats['feed_last_t'] = t0
                    self.stats['feed_total_polls'] = \
                        self.stats.get('feed_total_polls', 0) + 1
            self._stop.wait(self.interval)

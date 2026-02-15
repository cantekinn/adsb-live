"""
SQLite persistence.

Iki tablo:
  - aircraft: ICAO + son durum (UPSERT)
  - history:  her pozisyon mesaji icin yeni satir (zaman, lat, lon, alt, spd, hdg)

Background thread her N saniyede tracker snapshot'i alip flush eder.
Tablolari WAL modunda - okuma yazma cakismaz.
"""

import sqlite3
import threading
import time
import logging
import os

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS aircraft (
    icao TEXT PRIMARY KEY,
    first_seen REAL,
    last_seen REAL,
    callsign TEXT,
    country TEXT,
    country_code TEXT,
    operator TEXT,
    category INTEGER,
    msg_count INTEGER
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icao TEXT,
    t REAL,
    lat REAL,
    lon REAL,
    altitude INTEGER,
    speed REAL,
    heading REAL,
    vertical_rate INTEGER
);
CREATE INDEX IF NOT EXISTS idx_history_icao ON history(icao);
CREATE INDEX IF NOT EXISTS idx_history_t ON history(t);
CREATE INDEX IF NOT EXISTS idx_aircraft_last ON aircraft(last_seen);
"""


class Persistence:
    def __init__(self, path: str, tracker, flush_interval: float = 5.0):
        self.path = path
        self.tracker = tracker
        self.flush_interval = flush_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Yeni veritabani olusturma
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript('PRAGMA journal_mode=WAL;')
        conn.executescript(SCHEMA)
        conn.close()
        self._last_positions: dict[str, tuple] = {}  # ICAO -> (lat,lon) sok

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='Persistence')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        log.info('SQLite persistence: %s', self.path)
        while not self._stop.is_set():
            try:
                self._flush()
            except Exception as e:
                log.warning('SQLite flush hatasi: %s', e)
            self._stop.wait(self.flush_interval)

    def _flush(self) -> None:
        snap = self.tracker.snapshot()
        if not snap:
            return
        conn = sqlite3.connect(self.path, timeout=2.0)
        cur = conn.cursor()
        now = time.time()
        for ac in snap:
            # UPSERT aircraft
            cur.execute("""
                INSERT INTO aircraft (icao, first_seen, last_seen, callsign,
                    country, country_code, operator, category, msg_count)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(icao) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    callsign=COALESCE(excluded.callsign, aircraft.callsign),
                    country=COALESCE(excluded.country, aircraft.country),
                    country_code=COALESCE(excluded.country_code, aircraft.country_code),
                    operator=COALESCE(excluded.operator, aircraft.operator),
                    category=COALESCE(excluded.category, aircraft.category),
                    msg_count=excluded.msg_count
            """, (ac['icao'], ac.get('last_seen', now), ac.get('last_seen', now),
                  ac.get('callsign'), ac.get('country'), ac.get('country_code'),
                  ac.get('operator'), ac.get('category'), ac.get('msg_count', 0)))
            # History - yeni konum varsa insert (dedup)
            lat = ac.get('lat'); lon = ac.get('lon')
            if lat is not None and lon is not None:
                key = (round(lat, 4), round(lon, 4))
                if self._last_positions.get(ac['icao']) != key:
                    self._last_positions[ac['icao']] = key
                    cur.execute("""
                        INSERT INTO history (icao, t, lat, lon, altitude,
                            speed, heading, vertical_rate)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (ac['icao'], now, lat, lon,
                          ac.get('altitude'), ac.get('speed'),
                          ac.get('heading'), ac.get('vertical_rate')))
        conn.commit()
        conn.close()


# ----- query helpers (REST API icin) -----
def get_aircraft_history(path: str, icao: str, limit: int = 1000) -> list[dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT t, lat, lon, altitude, speed, heading
        FROM history WHERE icao=? ORDER BY t DESC LIMIT ?
    """, (icao.upper(), limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_total_stats(path: str) -> dict:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    n_aircraft = cur.execute('SELECT COUNT(*) FROM aircraft').fetchone()[0]
    n_history = cur.execute('SELECT COUNT(*) FROM history').fetchone()[0]
    countries = cur.execute("""
        SELECT country_code, COUNT(*) FROM aircraft
        WHERE country_code IS NOT NULL GROUP BY country_code
        ORDER BY 2 DESC LIMIT 10
    """).fetchall()
    operators = cur.execute("""
        SELECT operator, COUNT(*) FROM aircraft
        WHERE operator IS NOT NULL GROUP BY operator
        ORDER BY 2 DESC LIMIT 10
    """).fetchall()
    conn.close()
    return {
        'total_aircraft': n_aircraft,
        'total_positions': n_history,
        'top_countries': [{'cc': c, 'n': n} for c, n in countries],
        'top_operators': [{'op': o, 'n': n} for o, n in operators],
    }

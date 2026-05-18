"""
Flask + Socket.IO web UI + REST API.
"""

import logging
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

from config import EMIT_INTERVAL_S, WEB_HOST, WEB_PORT
from aircraft.tracker import AircraftTracker

log = logging.getLogger(__name__)


def create_app(tracker: AircraftTracker, stats: dict | None = None,
               db_path: str | None = None,
               config: dict | None = None
               ) -> tuple[Flask, SocketIO]:
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['SECRET_KEY'] = 'adsb-live'
    socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

    @app.route('/')
    def index():
        return render_template('index.html')

    # ===== REST API =====
    @app.route('/api/aircraft')
    def api_aircraft():
        return jsonify({'aircraft': tracker.snapshot(),
                        'count': tracker.count(),
                        'stats': stats or {},
                        'config': config or {}})

    @app.route('/api/aircraft/<icao>')
    def api_aircraft_one(icao):
        icao = icao.upper()
        snap = tracker.snapshot()
        for a in snap:
            if a['icao'] == icao:
                return jsonify(a)
        return jsonify({'error': 'not found'}), 404

    @app.route('/api/history/<icao>')
    def api_history(icao):
        if not db_path:
            return jsonify({'error': 'persistence not enabled'}), 503
        from storage.db import get_aircraft_history
        limit = int(request.args.get('limit', 1000))
        return jsonify({'icao': icao.upper(),
                        'history': get_aircraft_history(db_path, icao, limit)})

    @app.route('/api/stats')
    def api_stats():
        result = {'live': stats or {}, 'count': tracker.count()}
        if db_path:
            from storage.db import get_total_stats
            try:
                result['db'] = get_total_stats(db_path)
            except Exception as e:
                result['db_error'] = str(e)
        return jsonify(result)

    @app.route('/api/airports')
    def api_airports():
        with open(app.static_folder + '/airports.json', 'r') as f:
            return app.response_class(f.read(), mimetype='application/json')

    @app.route('/api/metar/<icao>')
    def api_metar(icao):
        from web.metar import get_metar, get_taf
        return jsonify({
            'icao': icao.upper(),
            'metar': get_metar(icao),
            'taf': get_taf(icao),
        })

    @app.route('/api/photo/<icao>')
    def api_photo(icao):
        from web.photo import get_photo
        photo = get_photo(icao)
        return jsonify(photo or {})

    @app.route('/api/heatmap')
    def api_heatmap():
        """SQLite'tan son N dakikalik tum pozisyon noktalari."""
        if not db_path:
            return jsonify({'error': 'persistence required'}), 503
        import sqlite3, time
        minutes = int(request.args.get('minutes', 60))
        since = time.time() - minutes * 60
        conn = sqlite3.connect(db_path)
        rows = conn.execute("""
            SELECT lat, lon, altitude, t FROM history
            WHERE t > ? AND lat IS NOT NULL
        """, (since,)).fetchall()
        conn.close()
        return jsonify({'points': rows, 'minutes': minutes, 'count': len(rows)})

    @app.route('/api/decode/<hex_msg>')
    def api_decode(hex_msg):
        """Bir hex mesaji adim adim decode et (egitim icin)."""
        from decoder import crc as crc_mod
        from decoder import modes
        from decoder import adsb as adsb_mod
        try:
            msg = bytes.fromhex(hex_msg)
        except ValueError:
            return jsonify({'error': 'invalid hex'}), 400
        if len(msg) not in (7, 14):
            return jsonify({'error': f'7 veya 14 byte bekleniyor, {len(msg)} alindi'}), 400
        # Bit liste
        bits = ''.join(f'{b:08b}' for b in msg)
        result = {'hex': hex_msg.upper(), 'bytes': len(msg), 'bits': bits}
        df = (msg[0] >> 3) & 0x1F
        result['df'] = df
        result['df_name'] = {
            0: 'Short Air-Air', 4: 'Surveillance Alt', 5: 'Surveillance ID',
            11: 'All-Call Reply', 16: 'Long Air-Air',
            17: 'ADS-B Extended Squitter', 18: 'TIS-B', 19: 'Military',
            20: 'Comm-B Alt', 21: 'Comm-B ID', 24: 'Comm-D',
        }.get(df, '?')
        if len(msg) == 14:
            ca = msg[0] & 0x07
            icao = msg[1:4].hex().upper()
            me = msg[4:11]
            pi = msg[11:14].hex().upper()
            result.update({'ca': ca, 'icao': icao,
                           'me_hex': me.hex().upper(), 'pi': pi})
            crc_val = crc_mod.compute(msg)
            result['crc'] = f'{crc_val:06X}'
            result['crc_ok'] = (crc_val == 0)
            if df == 17:
                tc = modes.get_tc(me)
                result['tc'] = tc
                if 1 <= tc <= 4:
                    ident = adsb_mod.decode_identification(me)
                    result['ident'] = {'callsign': ident.callsign,
                                       'category': ident.category}
                elif 9 <= tc <= 18 or 20 <= tc <= 22:
                    pos = adsb_mod.decode_airborne_position(me)
                    result['airborne_pos'] = {
                        'f': pos.f, 'lat_cpr': pos.lat_cpr,
                        'lon_cpr': pos.lon_cpr, 'altitude': pos.altitude}
                elif tc == 19:
                    v = adsb_mod.decode_velocity(me)
                    if v:
                        result['velocity'] = {
                            'speed': v.speed, 'heading': v.heading,
                            'vertical_rate': v.vertical_rate,
                            'type': v.speed_type}
        return jsonify(result)

    def _emit_loop():
        while True:
            socketio.emit('aircraft_update', {
                'aircraft': tracker.snapshot(),
                'count': tracker.count(),
                'stats': stats or {},
                'config': config or {},
            })
            socketio.sleep(EMIT_INTERVAL_S)

    @socketio.on('connect')
    def _on_connect():
        log.info('Client baglandi')

    socketio.start_background_task(_emit_loop)
    return app, socketio


def run(tracker: AircraftTracker, stats: dict | None = None,
        db_path: str | None = None, config: dict | None = None) -> None:
    app, sio = create_app(tracker, stats=stats, db_path=db_path, config=config)
    log.info('Web UI: http://%s:%d', WEB_HOST, WEB_PORT)
    sio.run(app, host=WEB_HOST, port=WEB_PORT, use_reloader=False)

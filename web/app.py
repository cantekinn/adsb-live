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

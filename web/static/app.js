// ADS-B Live - frontend (v3)

// ---------- harita ----------
const TILES = {
  dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png'
};
const map = L.map('map', { zoomControl: true, attributionControl: false })
  .setView([41.0, 29.0], 6);  // Turkiye genel
let tileLayer = L.tileLayer(TILES.dark, { maxZoom: 18 }).addTo(map);

// ---------- state ----------
const markers = {};
const trails = {};
const kalman = {};
const predictionLines = {};
const alertedICAOs = new Set();  // bir kez uyarilanlar
let selected = null;
let allAircraft = [];
let lastStats = {};
let heatLayer = null;
let heatMode = false;

const filters = {
  altMin: 0, altMax: 45000, spdMin: 0,
  countries: '', op: '',
  hideNoPos: false, hideNoCS: false,
  showTrails: true, showAirports: true,
};

// ---------- COLOR (altitude) ----------
// Tipler: 0=ground, 0-10k=mor, 10-20=mavi-yesil, 20-30=yesil-sari,
//         30-40=sari-turuncu, 40+=kirmizi
function altColor(alt) {
  if (alt == null) return '#888';
  if (alt < 1000) return '#6b21a8';
  if (alt < 5000) return '#7c3aed';
  if (alt < 10000) return '#2563eb';
  if (alt < 15000) return '#0891b2';
  if (alt < 20000) return '#06b6d4';
  if (alt < 25000) return '#10b981';
  if (alt < 30000) return '#84cc16';
  if (alt < 35000) return '#eab308';
  if (alt < 40000) return '#ea580c';
  return '#ef4444';
}

// ---------- AIRCRAFT TYPE -> SVG ----------
// category: 1=Light, 2=Small, 3=Large, 4=High-Vortex, 5=Heavy,
//           6=High-Performance, 7=Rotorcraft
const SVG_PLANE_NARROW = `<svg viewBox="-12 -12 24 24" xmlns="http://www.w3.org/2000/svg">
  <path class="body" d="M0,-11 L1.2,-3 L11,-1 L11,1 L1.2,3 L1,8 L4,9.5 L4,11
                         L0,10 L-4,11 L-4,9.5 L-1,8 L-1.2,3 L-11,1 L-11,-1
                         L-1.2,-3 Z"/>
</svg>`;
const SVG_PLANE_HEAVY = `<svg viewBox="-12 -12 24 24" xmlns="http://www.w3.org/2000/svg">
  <path class="body" d="M0,-11.5 L1.6,-2 L11.5,-0.5 L11.5,2 L1.6,3.5 L1.2,8.5 L5,10.5 L5,11.5
                         L0,10.5 L-5,11.5 L-5,10.5 L-1.2,8.5 L-1.6,3.5 L-11.5,2 L-11.5,-0.5
                         L-1.6,-2 Z"/>
</svg>`;
const SVG_HELI = `<svg viewBox="-12 -12 24 24" xmlns="http://www.w3.org/2000/svg">
  <path class="body" d="M-1,-3 L1,-3 L2,4 L1.5,8 L-1.5,8 L-2,4 Z M-10,-1 L10,-1 L10,1 L-10,1 Z
                         M-1,7 L1,7 L1,11 L-1,11 Z"/>
</svg>`;
const SVG_PROP = `<svg viewBox="-12 -12 24 24" xmlns="http://www.w3.org/2000/svg">
  <path class="body" d="M0,-9 L1,-3 L9,-0.5 L9,0.5 L1,3 L0.8,7 L3,8 L3,9
                         L0,8.5 L-3,9 L-3,8 L-0.8,7 L-1,3 L-9,0.5 L-9,-0.5
                         L-1,-3 Z"/>
</svg>`;

function planeSvg(category) {
  if (category === 7) return SVG_HELI;
  if (category === 1 || category === 2) return SVG_PROP;
  if (category === 5) return SVG_PLANE_HEAVY;
  return SVG_PLANE_NARROW;
}

function planeIcon(ac, sel) {
  const h = ac.heading || 0;
  let cls = 'plane-marker' + (sel ? ' selected' : '')
    + (ac.on_ground ? ' surface' : '');
  if (ac.emergency) cls += ' emergency';
  else if (ac.notable && ac.notable.category === 'vip') cls += ' vip';
  const color = altColor(ac.altitude);
  const svg = planeSvg(ac.category);
  // Inline color by replacing class style
  return L.divIcon({
    className: '',
    html: `<div class="${cls}" style="transform: rotate(${h}deg); --c: ${color}">
             ${svg.replace('class="body"', `class="body" fill="${color}"`)}
           </div>`,
    iconSize: [30, 30], iconAnchor: [15, 15]
  });
}

// ---------- COUNTRY FLAG EMOJI ----------
function flagEmoji(cc) {
  if (!cc || cc.length !== 2) return '';
  const A = 0x1F1E6, base = 'A'.charCodeAt(0);
  return String.fromCodePoint(A + cc.charCodeAt(0) - base,
                              A + cc.charCodeAt(1) - base);
}

// ---------- AIRPORTS ----------
const airportLayer = L.layerGroup().addTo(map);
let airportData = [];

function airportIcon(ap) {
  const isLarge = ap.type === 'l';
  const size = isLarge ? 12 : 8;
  const color = isLarge ? '#f5b342' : '#a78bfa';
  return L.divIcon({ className: '',
    html: `<div class="airport-marker" style="width:${size}px;height:${size}px">
             <div class="dot" style="width:${size-3}px;height:${size-3}px;background:${color}"></div>
             ${isLarge && ap.iata ? `<div class="iata" style="color:${color}">${ap.iata}</div>` : ''}
           </div>`,
    iconSize: [size, size], iconAnchor: [size/2, size/2] });
}

function renderAirports() {
  airportLayer.clearLayers();
  const z = map.getZoom();
  for (const ap of airportData) {
    // Zoom-bazli gizleme
    if (ap.type === 'l' && z < 4) continue;        // buyukler z>=4
    if (ap.type === 'm' && z < 7) continue;        // ortalar z>=7
    const m = L.marker([ap.lat, ap.lon], { icon: airportIcon(ap) }).addTo(airportLayer);
    m.bindTooltip(`<b>${ap.iata || ap.icao}</b><br>${ap.name}<br>${ap.country}`,
      { direction: 'top', offset: [0, -8] });
    m.on('click', () => showMetar(ap));
  }
}

fetch('/static/airports.json').then(r => r.json()).then(list => {
  airportData = list;
  renderAirports();
});

map.on('zoomend', renderAirports);

// ---------- FILTRELEME ----------
function passFilter(ac) {
  const alt = ac.altitude || 0;
  if (filters.hideNoPos && (ac.lat == null || ac.lon == null)) return false;
  if (filters.hideNoCS && !ac.callsign) return false;
  if (alt < filters.altMin) return false;
  if (alt > filters.altMax) return false;
  if ((ac.speed || 0) < filters.spdMin) return false;
  if (filters.countries) {
    const codes = filters.countries.split(',').map(s => s.trim().toUpperCase());
    if (!codes.includes((ac.country_code || '').toUpperCase())) return false;
  }
  if (filters.op) {
    const q = filters.op.toLowerCase();
    if (!(ac.operator || '').toLowerCase().includes(q)
        && !(ac.callsign || '').toLowerCase().includes(q)) return false;
  }
  return true;
}

// ---------- MARKERS ----------
// Kalman 2D constant-velocity smoother (lat/lon konum + hiz)
// Pozisyon update'leri ~5 sn arali geliyor; arada hizla extrapole et.
function kalmanUpdate(icao, lat, lon, t) {
  const k = kalman[icao];
  if (!k) {
    kalman[icao] = { lat, lon, vLat: 0, vLon: 0, t };
    return;
  }
  const dt = Math.max(0.01, t - k.t);
  // Yeni olcumden hiz hesabi
  const measVLat = (lat - k.lat) / dt;
  const measVLon = (lon - k.lon) / dt;
  // Sanity: cok yuksek hiz -> reset
  const dist = Math.hypot(lat - k.lat, lon - k.lon);
  if (dist / dt > 0.5) {  // ~derece/sn, makul ustu
    kalman[icao] = { lat, lon, vLat: 0, vLon: 0, t };
    return;
  }
  // Alpha-beta filter (basit Kalman varyantı)
  const alpha = 0.7, beta = 0.3;
  k.lat += alpha * (lat - k.lat);
  k.lon += alpha * (lon - k.lon);
  k.vLat += beta * (measVLat - k.vLat) * dt;
  k.vLon += beta * (measVLon - k.vLon) * dt;
  k.t = t;
}

function kalmanExtrapolate(icao, now) {
  const k = kalman[icao];
  if (!k) return null;
  const dt = now - k.t;
  if (dt > 30) return null;  // 30 sn'den eskiyse extrapole etme
  return [k.lat + k.vLat * dt, k.lon + k.vLon * dt];
}

// Her 250 ms'de marker'lari Kalman ile extrapole et (yumusak hareket)
setInterval(() => {
  if (heatMode || !allAircraft.length) return;
  const now = Date.now() / 1000;
  for (const icao in markers) {
    const pos = kalmanExtrapolate(icao, now);
    if (pos) markers[icao].setLatLng(pos);
  }
}, 250);

function updateMarkers(aircraft) {
  if (heatMode) {
    // Heatmap modu: marker'lari gizle, heatmap goster
    for (const icao in markers) {
      map.removeLayer(markers[icao]); delete markers[icao];
    }
    for (const icao in trails) {
      map.removeLayer(trails[icao]); delete trails[icao];
    }
    const points = aircraft.filter(a => a.lat != null && passFilter(a))
      .map(a => [a.lat, a.lon, Math.min(1, (a.altitude || 5000) / 40000)]);
    if (heatLayer) map.removeLayer(heatLayer);
    heatLayer = L.heatLayer(points, { radius: 20, blur: 25, max: 1,
      gradient: {0.0:'#2563eb', 0.3:'#10b981', 0.6:'#eab308', 1.0:'#ef4444'}
    }).addTo(map);
    return;
  }
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }

  const seen = new Set();
  for (const ac of aircraft) {
    if (!passFilter(ac)) continue;
    seen.add(ac.icao);
    if (ac.lat == null || ac.lon == null) continue;
    const isSel = ac.icao === selected;
    const icon = planeIcon(ac, isSel);
    // Kalman tracker
    kalmanUpdate(ac.icao, ac.lat, ac.lon, Date.now() / 1000);
    if (markers[ac.icao]) {
      markers[ac.icao].setLatLng([ac.lat, ac.lon]).setIcon(icon);
    } else {
      const m = L.marker([ac.lat, ac.lon], { icon, riseOnHover: true }).addTo(map);
      m.on('click', () => selectAircraft(ac.icao));
      m.bindTooltip(`<b>${ac.callsign || ac.icao}</b><br>${ac.altitude || '?'} ft`,
        { direction: 'top', offset: [0, -16] });
      markers[ac.icao] = m;
    }
    if (filters.showTrails && ac.track && ac.track.length >= 2) {
      const color = isSel ? '#f59e0b' : altColor(ac.altitude);
      const opacity = isSel ? 0.9 : 0.4;
      const weight = isSel ? 2.5 : 1.2;
      if (trails[ac.icao]) {
        trails[ac.icao].setLatLngs(ac.track).setStyle({ color, opacity, weight });
      } else {
        trails[ac.icao] = L.polyline(ac.track, { color, weight, opacity }).addTo(map);
      }
    } else if (trails[ac.icao]) {
      map.removeLayer(trails[ac.icao]); delete trails[ac.icao];
    }
    // Prediction line (sadece secili ucak icin)
    if (isSel && ac.predicted_route && ac.predicted_route.length >= 2) {
      if (predictionLines[ac.icao]) {
        predictionLines[ac.icao].setLatLngs(ac.predicted_route);
      } else {
        predictionLines[ac.icao] = L.polyline(ac.predicted_route, {
          color: '#f59e0b', weight: 2, opacity: 0.6, dashArray: '6,8'
        }).addTo(map);
      }
    } else if (predictionLines[ac.icao]) {
      map.removeLayer(predictionLines[ac.icao]);
      delete predictionLines[ac.icao];
    }
  }
  for (const icao in markers) {
    if (!seen.has(icao)) {
      map.removeLayer(markers[icao]); delete markers[icao];
      if (trails[icao]) { map.removeLayer(trails[icao]); delete trails[icao]; }
      if (predictionLines[icao]) { map.removeLayer(predictionLines[icao]); delete predictionLines[icao]; }
      if (selected === icao) closeDetail();
    }
  }
}

// ---------- LIST ----------
function updateList(aircraft) {
  const tbody = document.getElementById('ac-rows');
  const search = document.getElementById('search-input').value.toLowerCase();
  const filtered = aircraft.filter(a => {
    if (!passFilter(a)) return false;
    if (search && !(a.icao.toLowerCase().includes(search)
        || (a.callsign || '').toLowerCase().includes(search))) return false;
    return true;
  });
  filtered.sort((a, b) => (b.msg_count || 0) - (a.msg_count || 0));
  document.getElementById('list-count').textContent = `${filtered.length} / ${aircraft.length}`;
  let html = '';
  for (const ac of filtered) {
    const sel = ac.icao === selected ? 'selected' : '';
    const cs = ac.callsign || '';
    const alt = ac.altitude != null ? ac.altitude : '';
    const spd = ac.speed != null ? ac.speed.toFixed(0) : '';
    const hdg = ac.heading != null ? ac.heading.toFixed(0) : '';
    const flag = flagEmoji(ac.country_code);
    html += `<tr class="${sel}" data-icao="${ac.icao}">
      <td class="flag">${flag}</td>
      <td class="num">${ac.icao}</td>
      <td class="${cs ? 'cs' : 'dash'}">${cs || '--'}</td>
      <td class="${alt !== '' ? 'num' : 'dash'}">${alt || '--'}</td>
      <td class="${spd !== '' ? 'num' : 'dash'}">${spd || '--'}</td>
      <td class="${hdg !== '' ? 'num' : 'dash'}">${hdg ? hdg + '°' : '--'}</td>
    </tr>`;
  }
  tbody.innerHTML = html;
  tbody.querySelectorAll('tr').forEach(tr => {
    tr.onclick = () => selectAircraft(tr.dataset.icao);
  });
}

// ---------- DETAY ----------
function selectAircraft(icao) {
  selected = icao;
  const ac = allAircraft.find(a => a.icao === icao);
  if (ac && ac.lat != null && ac.lon != null) map.panTo([ac.lat, ac.lon]);
  renderDetail(ac);
  updateMarkers(allAircraft);
  updateList(allAircraft);
}
function closeDetail() {
  selected = null;
  document.getElementById('detail').classList.remove('open');
  updateMarkers(allAircraft);
  updateList(allAircraft);
}
function setField(id, val, unit) {
  const el = document.getElementById(id);
  if (val == null || val === '') { el.textContent = '--'; el.classList.add('muted'); return; }
  el.classList.remove('muted');
  el.innerHTML = val + (unit ? ` <span class="unit">${unit}</span>` : '');
}
const CATEGORIES = {
  1: 'Light', 2: 'Small', 3: 'Large', 4: 'High-Vortex',
  5: 'Heavy', 6: 'High-Performance', 7: 'Rotorcraft'
};
function loadPhoto(icao) {
  const wrap = document.getElementById('d-photo-wrap');
  const img = document.getElementById('d-photo');
  const credit = document.getElementById('d-photo-credit');
  wrap.style.display = 'none';
  fetch(`/api/photo/${icao}`).then(r => r.json()).then(p => {
    if (!p.thumbnail) return;
    img.src = p.thumbnail;
    img.onclick = () => window.open(p.link, '_blank');
    credit.innerHTML = `${p.aircraft || ''} ${p.registration ? '· ' + p.registration : ''} ${p.photographer ? '· © ' + p.photographer : ''}`;
    wrap.style.display = 'block';
  });
}

function renderDetail(ac) {
  const panel = document.getElementById('detail');
  if (!ac) { panel.classList.remove('open'); return; }
  loadPhoto(ac.icao);
  document.getElementById('d-cs').textContent = ac.callsign || ac.icao;
  document.getElementById('d-icao').textContent = ac.icao;
  document.getElementById('d-flag').textContent = flagEmoji(ac.country_code);
  document.getElementById('d-op').textContent = ac.operator || ac.country || '';
  const groundBadge = document.getElementById('d-ground');
  groundBadge.classList.toggle('show', !!ac.on_ground);
  groundBadge.textContent = 'GROUND';
  const holdBadge = document.getElementById('d-holding');
  holdBadge.classList.toggle('show', !!ac.holding);
  holdBadge.textContent = ac.holding ? `HOLDING ${ac.holding.turn?.toUpperCase()}` : 'HOLDING';

  setField('d-alt', ac.altitude != null ? ac.altitude.toLocaleString() : null, 'ft');
  setField('d-spd', ac.speed != null ? ac.speed.toFixed(0) : null, 'kt');
  setField('d-hdg', ac.heading != null ? ac.heading.toFixed(0) : null, '°');
  setField('d-vr', ac.vertical_rate != null ? ac.vertical_rate.toLocaleString() : null, 'fpm');
  const pos = (ac.lat != null && ac.lon != null)
    ? `${ac.lat.toFixed(3)}, ${ac.lon.toFixed(3)}` : null;
  setField('d-pos', pos);
  setField('d-sqk', ac.squawk);
  setField('d-cat', CATEGORIES[ac.category] || null);
  setField('d-msg', ac.msg_count);
  setField('d-wind', ac.wind ? `${ac.wind.wind_speed}kt ←${ac.wind.wind_from}°` : null);
  setField('d-pattern', ac.holding ? `${ac.holding.pattern} (${ac.holding.turn}, ${ac.holding.total_nm}nm)` : null);

  setField('d-mcp', ac.mcp_alt != null ? ac.mcp_alt.toLocaleString() : null, 'ft');
  setField('d-ias', ac.ias, 'kt');
  setField('d-mach', ac.mach != null ? ac.mach.toFixed(2) : null);
  setField('d-mhdg', ac.mag_heading != null ? ac.mag_heading.toFixed(0) : null, '°');
  setField('d-roll', ac.roll != null ? ac.roll.toFixed(1) : null, '°');
  setField('d-tas', ac.tas, 'kt');
  panel.classList.add('open');
}
document.getElementById('detail-close').onclick = closeDetail;

// ---------- FILTER PANEL ----------
function bindRange(id, valId, key) {
  const el = document.getElementById(id);
  const out = document.getElementById(valId);
  el.oninput = () => {
    filters[key] = parseInt(el.value);
    out.textContent = el.value;
    refresh();
  };
}
bindRange('alt-min', 'alt-min-val', 'altMin');
bindRange('alt-max', 'alt-max-val', 'altMax');
bindRange('spd-min', 'spd-min-val', 'spdMin');

document.getElementById('country-filter').oninput = e => { filters.countries = e.target.value; refresh(); };
document.getElementById('op-filter').oninput = e => { filters.op = e.target.value; refresh(); };
document.getElementById('hide-noPos').onchange = e => { filters.hideNoPos = e.target.checked; refresh(); };
document.getElementById('hide-noCS').onchange = e => { filters.hideNoCS = e.target.checked; refresh(); };
document.getElementById('show-trails').onchange = e => { filters.showTrails = e.target.checked; refresh(); };
document.getElementById('show-airports').onchange = e => {
  filters.showAirports = e.target.checked;
  if (filters.showAirports) airportLayer.addTo(map);
  else map.removeLayer(airportLayer);
};
document.getElementById('search-input').oninput = () => updateList(allAircraft);

document.getElementById('filter-reset').onclick = () => {
  Object.assign(filters, { altMin:0, altMax:45000, spdMin:0,
    countries:'', op:'', hideNoPos:false, hideNoCS:false,
    showTrails:true, showAirports:true });
  ['alt-min','alt-max','spd-min'].forEach(id => {
    const e = document.getElementById(id);
    e.value = (id === 'alt-max') ? 45000 : 0;
    document.getElementById(id+'-val').textContent = e.value;
  });
  document.getElementById('country-filter').value = '';
  document.getElementById('op-filter').value = '';
  document.getElementById('hide-noPos').checked = false;
  document.getElementById('hide-noCS').checked = false;
  document.getElementById('show-trails').checked = true;
  document.getElementById('show-airports').checked = true;
  airportLayer.addTo(map);
  refresh();
};

// ---------- PANEL TOGGLES ----------
function togglePanel(panelId, btnId) {
  const p = document.getElementById(panelId);
  const b = document.getElementById(btnId);
  const isOpen = p.classList.toggle('open');
  b.classList.toggle('active', isOpen);
}
document.getElementById('filter-btn').onclick = () => togglePanel('filter-panel', 'filter-btn');
document.getElementById('dash-btn').onclick = () => { togglePanel('dash-panel', 'dash-btn'); renderDashboard(); };
document.querySelectorAll('[data-close]').forEach(b => {
  b.onclick = () => {
    const p = document.getElementById(b.dataset.close);
    p.classList.remove('open');
    const btnId = b.dataset.close.replace('-panel', '-btn');
    document.getElementById(btnId)?.classList.remove('active');
  };
});

// ---------- HEATMAP ----------
document.getElementById('heatmap-btn').onclick = () => {
  heatMode = !heatMode;
  document.getElementById('heatmap-btn').classList.toggle('active', heatMode);
  refresh();
};

// ---------- TEMA ----------
function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('adsb-theme', t);
  map.removeLayer(tileLayer);
  tileLayer = L.tileLayer(t === 'dark' ? TILES.dark : TILES.light, {maxZoom:18}).addTo(map);
}
document.getElementById('theme-btn').onclick = () => {
  const cur = document.documentElement.getAttribute('data-theme');
  setTheme(cur === 'dark' ? 'light' : 'dark');
};
setTheme(localStorage.getItem('adsb-theme') || 'dark');

// ---------- DASHBOARD ----------
function renderDashboard() {
  const now = Date.now() / 1000;
  const active = allAircraft.filter(a => (now - a.last_seen) < 60);
  document.getElementById('d-uniq').textContent = allAircraft.length;
  document.getElementById('d-active').textContent = active.length;
  document.getElementById('d-airborne').textContent =
    allAircraft.filter(a => a.on_ground === false).length;
  document.getElementById('d-surface').textContent =
    allAircraft.filter(a => a.on_ground === true).length;
  document.getElementById('d-fix1').textContent = lastStats.fixed_1bit || 0;
  document.getElementById('d-fix2').textContent = lastStats.fixed_2bit || 0;

  // Top 10
  const top = [...allAircraft].sort((a,b) => (b.msg_count||0) - (a.msg_count||0)).slice(0,10);
  document.getElementById('dash-top').innerHTML = top.map(a =>
    `<div class="dash-row"><span>${flagEmoji(a.country_code)} ${a.callsign || a.icao}</span><b>${a.msg_count} msg</b></div>`
  ).join('');

  // Country distribution
  const ccCount = {};
  for (const a of allAircraft) {
    const cc = a.country_code || '??';
    ccCount[cc] = (ccCount[cc] || 0) + 1;
  }
  const sorted = Object.entries(ccCount).sort((a,b) => b[1]-a[1]).slice(0,10);
  document.getElementById('dash-countries').innerHTML = sorted.map(([cc,n]) =>
    `<div class="dash-row"><span>${flagEmoji(cc)} ${cc}</span><b>${n}</b></div>`
  ).join('');
}

// ---------- POLAR PLOT ----------
const polarCanvas = document.getElementById('polar');
const polarCtx = polarCanvas.getContext('2d');
const polarPoints = [];
function drawPolar() {
  const W = polarCanvas.width, H = polarCanvas.height;
  const cx = W/2, cy = H/2, R = W/2 - 10;
  polarCtx.clearRect(0,0,W,H);
  polarCtx.strokeStyle = getComputedStyle(document.documentElement)
    .getPropertyValue('--border');
  polarCtx.lineWidth = 1;
  // Concentric circles
  for (const f of [0.33, 0.66, 1.0]) {
    polarCtx.beginPath(); polarCtx.arc(cx, cy, R*f, 0, 2*Math.PI); polarCtx.stroke();
  }
  // Cross
  polarCtx.beginPath();
  polarCtx.moveTo(cx-R,cy); polarCtx.lineTo(cx+R,cy);
  polarCtx.moveTo(cx,cy-R); polarCtx.lineTo(cx,cy+R);
  polarCtx.stroke();
  // Points
  for (const p of polarPoints) {
    const ang = (p.brg - 90) * Math.PI / 180;
    const r = Math.min(R, p.dist / 300 * R);  // 300 NM full
    const x = cx + r*Math.cos(ang), y = cy + r*Math.sin(ang);
    polarCtx.fillStyle = altColor(p.alt) + '88';
    polarCtx.beginPath(); polarCtx.arc(x, y, 2, 0, 2*Math.PI); polarCtx.fill();
  }
  polarCtx.fillStyle = getComputedStyle(document.documentElement)
    .getPropertyValue('--text-dim');
  polarCtx.font = '9px Consolas';
  polarCtx.fillText('N', cx-3, 12);
}
function addPolarPoint(refLat, refLon, ac) {
  if (ac.lat == null || refLat == null) return;
  const dlat = (ac.lat - refLat) * Math.PI / 180;
  const dlon = (ac.lon - refLon) * Math.PI / 180;
  const r1 = refLat * Math.PI/180;
  const a = Math.sin(dlat/2)**2 + Math.cos(r1)*Math.cos(ac.lat*Math.PI/180)*Math.sin(dlon/2)**2;
  const dist = 2 * 3440 * Math.asin(Math.sqrt(a));   // NM
  const brg = (Math.atan2(Math.sin(dlon)*Math.cos(ac.lat*Math.PI/180),
    Math.cos(r1)*Math.sin(ac.lat*Math.PI/180) - Math.sin(r1)*Math.cos(ac.lat*Math.PI/180)*Math.cos(dlon)) * 180/Math.PI + 360) % 360;
  polarPoints.push({ brg, dist, alt: ac.altitude });
  if (polarPoints.length > 500) polarPoints.shift();
}

// ---------- SOCKET ----------
const socket = io();
let refLat = null, refLon = null;

function refresh() {
  updateMarkers(allAircraft);
  updateList(allAircraft);
  if (selected) renderDetail(allAircraft.find(a => a.icao === selected));
}

// Beep oynatici (Web Audio API)
function beep(freq=880, ms=200) {
  try {
    const ctx = window._actx || (window._actx = new (window.AudioContext||window.webkitAudioContext)());
    const o = ctx.createOscillator(); const g = ctx.createGain();
    o.frequency.value = freq; o.type = 'sine';
    g.gain.value = 0.15; o.connect(g); g.connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + ms/1000);
  } catch (e) {}
}

// Browser notification helper
function notify(title, body) {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'granted') {
    new Notification(title, { body, icon: '/static/airports.json' });
  } else if (Notification.permission !== 'denied') {
    Notification.requestPermission();
  }
}

function checkAlerts(aircraft) {
  for (const ac of aircraft) {
    if (alertedICAOs.has(ac.icao)) continue;
    if (ac.emergency) {
      alertedICAOs.add(ac.icao);
      beep(440, 400); setTimeout(() => beep(880, 400), 500);
      notify(`🚨 ${ac.emergency.label} - ${ac.callsign || ac.icao}`,
             `Squawk ${ac.emergency.squawk}. Position: ${ac.lat?.toFixed(2)}, ${ac.lon?.toFixed(2)}`);
    } else if (ac.notable && ac.notable.category === 'vip') {
      alertedICAOs.add(ac.icao);
      beep(660, 200);
      notify(`✈ ${ac.notable.label}`, `${ac.callsign || ac.icao}`);
    }
  }
}

socket.on('aircraft_update', data => {
  allAircraft = data.aircraft || [];
  checkAlerts(allAircraft);
  lastStats = data.stats || {};
  document.getElementById('ac-count').innerText = allAircraft.length;
  document.getElementById('msg-count').innerText = lastStats.df17_decoded || 0;
  document.getElementById('crc-count').innerText = lastStats.crc_ok || 0;
  document.getElementById('cs-count').innerText =
    allAircraft.filter(a => a.callsign).length;
  document.getElementById('pos-count').innerText =
    allAircraft.filter(a => a.lat != null).length;

  // Mode badge
  const mode = lastStats.feed_mode || 'sdr';
  document.getElementById('mode-badge').textContent = mode.toUpperCase();

  // Progress (file mode)
  const total = lastStats.feed_total_seconds;
  if (total && total > 0) {
    const sim = (lastStats.samples_processed || 0) / 2e6;
    const pct = Math.min(100, (sim / total) * 100);
    document.getElementById('progress-wrap').style.display = 'flex';
    document.getElementById('progress-label').innerText =
      `${sim.toFixed(0)}/${total.toFixed(0)}s${lastStats.feed_speed ? ' ' + lastStats.feed_speed + 'x' : ''}`;
    document.getElementById('progress-fill').style.width = pct + '%';
  }

  refresh();
  if (document.getElementById('dash-panel').classList.contains('open'))
    renderDashboard();

  // Polar
  if (refLat == null && data.config?.ref_lat) {
    refLat = data.config.ref_lat; refLon = data.config.ref_lon;
  }
  if (refLat != null) {
    for (const ac of allAircraft) addPolarPoint(refLat, refLon, ac);
    drawPolar();
  }
});

drawPolar();

// ========== SOLAR TERMINATOR ==========
// NOAA Solar Position formulu, basitlestirilmis
function sunPosition(date) {
  const rad = Math.PI / 180;
  const dayOfYear = Math.floor((date - new Date(date.getFullYear(), 0, 0)) / 86400000);
  const decl = 23.44 * Math.sin(rad * 360 * (dayOfYear - 81) / 365);
  const B = rad * 360 * (dayOfYear - 81) / 365;
  const eot = 9.87 * Math.sin(2*B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B);
  const minutesSinceUTCNoon = (date.getUTCHours() - 12) * 60 + date.getUTCMinutes() + eot;
  const solarLon = -(minutesSinceUTCNoon * 0.25);
  return { lat: decl, lon: solarLon };
}

function terminatorPolygon(date, points=180) {
  const sun = sunPosition(date);
  const antiLat = -sun.lat;
  const antiLon = sun.lon + 180;
  const rad = Math.PI / 180;
  const polyPts = [];
  for (let i = 0; i <= points; i++) {
    const ang = (i / points) * 2 * Math.PI;
    const offsetLat = 90 * Math.cos(ang);
    const offsetLon = 90 * Math.sin(ang) / Math.max(0.01, Math.cos(rad*offsetLat));
    let lat = antiLat + offsetLat;
    let lon = antiLon + offsetLon;
    if (lat > 90) lat = 90; if (lat < -90) lat = -90;
    while (lon > 180) lon -= 360;
    while (lon < -180) lon += 360;
    polyPts.push([lat, lon]);
  }
  return polyPts;
}

let terminatorLayer = null, sunMarker = null;

function updateTerminator() {
  const now = new Date();
  const sun = sunPosition(now);
  if (sunMarker) map.removeLayer(sunMarker);
  sunMarker = L.marker([sun.lat, sun.lon], { icon: L.divIcon({
    className: '',
    html: '<div style="font-size:24px;text-shadow:0 0 8px #f59e0b">☀</div>',
    iconSize: [24, 24], iconAnchor: [12, 12],
  })}).addTo(map);
  sunMarker.bindTooltip('☀ ' + sun.lat.toFixed(1) + '°, ' + sun.lon.toFixed(1) + '°',
    { direction: 'top' });
  const pts = terminatorPolygon(now);
  if (terminatorLayer) map.removeLayer(terminatorLayer);
  terminatorLayer = L.polyline(pts, {
    color: '#fbbf24', weight: 1.5, opacity: 0.5, dashArray: '4,6'
  }).addTo(map);
}
updateTerminator();
setInterval(updateTerminator, 5 * 60 * 1000);

// ========== METAR popup ==========
function showMetar(ap) {
  const icao = ap.icao;
  fetch(`/api/metar/${icao}`).then(r => r.json()).then(data => {
    let html = `<div style="min-width:280px"><b>${ap.iata || icao}</b> · ${ap.name}<br><br>`;
    if (data.metar?.raw) {
      html += `<div style="font-family:Consolas;font-size:11px;color:#4cc9f0">${data.metar.raw}</div><br>`;
      if (data.metar.temp_c != null)
        html += `🌡 ${data.metar.temp_c}°C  `;
      if (data.metar.wind_dir != null && data.metar.wind_kt != null)
        html += `💨 ${data.metar.wind_dir}°/${data.metar.wind_kt}kt  `;
      if (data.metar.visib != null)
        html += `👁 ${data.metar.visib}sm`;
      html += '<br>';
    } else { html += '<i>METAR yok</i><br>'; }
    if (data.taf?.raw) {
      html += `<br><small>TAF:</small><div style="font-family:Consolas;font-size:10px;color:#a78bfa;white-space:pre-wrap">${data.taf.raw}</div>`;
    }
    html += '</div>';
    L.popup({ maxWidth: 360 }).setLatLng([ap.lat, ap.lon]).setContent(html).openOn(map);
  });
}

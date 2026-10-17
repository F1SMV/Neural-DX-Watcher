/* ═══════════════════════════════════════════════════════════════════════
   DIAGRAMME DE LOBE — v13.2
   Lobe de rayonnement tracé sur la carte HF, centré sur le QTH.
   Pour chaque azimut θ (pas de 2°) :
     r(θ) = max_i d_i · exp(−Δ_i² / 2σ²)     Δ_i = écart angulaire θ / azimut station i
   Le polygone est ensuite projeté en latitude/longitude (formule de la
   destination sur sphère), donc il se déforme correctement sur Leaflet.
   ═══════════════════════════════════════════════════════════════════════ */

const LOBE_SIGMA_DEG = 12;   // largeur angulaire de chaque pétale
const LOBE_STEP_DEG  = 2;    // résolution du contour

function _lobeRad(d) { return d * Math.PI / 180; }
function _lobeDeg(r) { return r * 180 / Math.PI; }

// Azimut (0-360°, 0 = Nord, sens horaire) de (lat1,lon1) vers (lat2,lon2)
function lobeBearing(lat1, lon1, lat2, lon2) {
  const p1 = _lobeRad(lat1), p2 = _lobeRad(lat2), dl = _lobeRad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (_lobeDeg(Math.atan2(y, x)) + 360) % 360;
}

// Distance grand cercle en km (rayon terrestre 6371 km)
function lobeDistance(lat1, lon1, lat2, lon2) {
  const p1 = _lobeRad(lat1), p2 = _lobeRad(lat2);
  const dp = p2 - p1, dl = _lobeRad(lon2 - lon1);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)));
}

// Point situé à distKm de (lat,lon) selon l'azimut bearingDeg. Retourne [lat, lon].
function lobeDestination(lat, lon, bearingDeg, distKm) {
  const delta = distKm / 6371;
  const theta = _lobeRad(bearingDeg);
  const p1 = _lobeRad(lat), l1 = _lobeRad(lon);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(delta) + Math.cos(p1) * Math.sin(delta) * Math.cos(theta));
  const l2 = l1 + Math.atan2(Math.sin(theta) * Math.sin(delta) * Math.cos(p1),
                             Math.cos(delta) - Math.sin(p1) * Math.sin(p2));
  let lonDeg = ((_lobeDeg(l2) + 540) % 360) - 180;   // normalise dans [-180, 180]
  return [_lobeDeg(p2), lonDeg];
}

// Écart angulaire le plus court, dans [-180, 180]
function _lobeAngDiff(a, b) {
  return ((a - b) % 360 + 540) % 360 - 180;
}

// Rayon du lobe à l'azimut θ (km)
function lobeRadiusAt(theta, stations) {
  let r = 0;
  for (const s of stations) {
    const d = _lobeAngDiff(theta, s.bearing);
    const v = s.distance * Math.exp(-(d * d) / (2 * LOBE_SIGMA_DEG * LOBE_SIGMA_DEG));
    if (v > r) r = v;
  }
  return r;
}

// reports = [{lat, lon, distance_km?, snr?, call?}, ...]
// Retourne { polygon: [[lat,lon],...], stations: [...], farthest }
function buildLobePolygon(qth, reports) {
  const stations = (reports || [])
    .filter(e => e.lat != null && e.lon != null)
    .map(e => {
      const bearing = lobeBearing(qth.lat, qth.lon, e.lat, e.lon);
      const distance = (e.distance_km != null && e.distance_km > 0)
        ? e.distance_km : lobeDistance(qth.lat, qth.lon, e.lat, e.lon);
      return { call: e.call || '', bearing, distance, snr: e.snr ?? null, lat: e.lat, lon: e.lon };
    })
    .filter(s => s.distance > 0);

  const polygon = [];
  if (stations.length) {
    for (let a = 0; a < 360; a += LOBE_STEP_DEG) {
      const r = lobeRadiusAt(a, stations);
      if (r > 0) polygon.push(lobeDestination(qth.lat, qth.lon, a, r));
    }
  }
  const farthest = stations.reduce((b, s) => (!b || s.distance > b.distance ? s : b), null);
  return { polygon, stations, farthest };
}

if (typeof module !== 'undefined') {
  module.exports = { lobeBearing, lobeDistance, lobeDestination, lobeRadiusAt, buildLobePolygon };
}

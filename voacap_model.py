"""Modèle interne MUF/LUF partagé (v14).

Une seule source de vérité pour l'accueil (/api/voacap) et l'insight (/api/voacap/predict) :
- LUF continue en distance (plus de saut à 1000 km) ;
- heure solaire au POINT MILIEU du grand cercle, dans les deux vues ;
- rien d'autre : c'est une estimation interne, PAS du VOACAP.
"""
import math

R_EARTH_KM = 6371.0
DEFAULT_SFI = 100.0


def distance_km(lat1, lon1, lat2, lon2):
    """Distance du grand cercle (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(math.sqrt(a))


def midpoint_lon(lat1, lon1, lat2, lon2):
    """Longitude du point milieu du grand cercle, en degrés [-180, 180[."""
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2, l2 = math.radians(lat2), math.radians(lon2)
    bx = math.cos(p2) * math.cos(l2 - l1)
    by = math.cos(p2) * math.sin(l2 - l1)
    lon = math.degrees(l1 + math.atan2(by, math.cos(p1) + bx))
    return (lon + 180.0) % 360.0 - 180.0


def local_hour(hour_utc, mid_lon):
    """Heure solaire (entière, 0-23) au point milieu pour une heure UTC donnée."""
    return int(round(hour_utc + mid_lon / 15.0)) % 24


def _interp(x, points):
    """Interpolation linéaire, constante hors des bornes."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


# Ancrages (distance km, LUF MHz). Valeurs v13 conservées aux points d'ancrage.
_LUF_DAY = [(1000, 7.0), (5000, 5.5), (10000, 4.5)]
_LUF_NIGHT = [(1000, 4.0), (5000, 3.5), (10000, 3.0)]


def is_night(local_h):
    return local_h < 6 or local_h >= 20


def luf(dist_km, local_h):
    """LUF estimée (MHz), continue en distance, plus basse la nuit."""
    return _interp(dist_km, _LUF_NIGHT if is_night(local_h) else _LUF_DAY)


def muf_base(sfi, dist_km):
    """MUF de base (MHz) selon le SFI et la distance (formule empirique)."""
    base = 5.0 + (sfi - 60) * 0.18
    if dist_km < 500:
        factor = 0.6
    elif dist_km < 2000:
        factor = 0.8 + (dist_km - 500) / 7500
    elif dist_km < 8000:
        factor = 1.0 + (dist_km - 2000) / 20000
    else:
        factor = 1.3
    return min(35.0, max(4.0, base * factor))


def muf_at(sfi, dist_km, local_h):
    """MUF avec variation diurne (+20 % à midi solaire)."""
    return muf_base(sfi, dist_km) * (1.0 + 0.2 * math.cos(math.pi * (local_h - 12) / 12))


def reliability(freq_mhz, muf, luf_mhz, local_h, dist_km, kp):
    """Fiabilité 0-1 d'une bande à une heure solaire donnée."""
    if freq_mhz > muf * 1.15 or freq_mhz < luf_mhz * 0.85:
        return 0.0
    center = (muf + luf_mhz) / 2
    half = (muf - luf_mhz) / 2 if muf > luf_mhz else 1.0
    base = max(0.0, 1.0 - (abs(freq_mhz - center) / max(half, 0.1)) ** 1.5)
    night = is_night(local_h)
    if night and freq_mhz > 14:
        base *= max(0.1, 1.0 - (freq_mhz - 14) * 0.08)
    if not night and freq_mhz < 7:
        base *= max(0.1, 1.0 - (7 - freq_mhz) * 0.15)
    if kp is not None and float(kp) >= 5:
        base *= max(0.05, 1.0 - (float(kp) - 4) * 0.18)
    return min(1.0, max(0.0, base))


def profile(tx_lat, tx_lon, rx_lat, rx_lon, sfi, kp, freqs):
    """Profil sur 24 h UTC : {heure_utc: {mid_lon, local_hour, muf, luf, rel{freq: 0-1}}}.

    C'est le seul point d'entrée des deux vues : même entrée, même résultat.
    """
    if sfi is None:
        sfi = DEFAULT_SFI
    dist = distance_km(tx_lat, tx_lon, rx_lat, rx_lon)
    mid = midpoint_lon(tx_lat, tx_lon, rx_lat, rx_lon)
    out = {}
    for h in range(24):
        lh = local_hour(h, mid)
        muf = muf_at(float(sfi), dist, lh)
        lu = luf(dist, lh)
        out[h] = {
            "mid_lon": mid,
            "local_hour": lh,
            "muf": muf,
            "luf": lu,
            "rel": {f: reliability(f, muf, lu, lh, dist, kp) for f in freqs},
        }
    return out

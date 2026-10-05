"""Places on maps: addresses found with OpenStreetMap's Nominatim (free, no key; one lookup a second, as its rules ask,
and every answer kept on this PC so a place is looked up once), then written as KML (Google Earth, Google My Maps),
GPX (phones and GPS) and GeoJSON, with straight-line distances and a Google Maps directions link for the route in the
order given (opened in any browser; no key).

  'map of: Shop 12 Hall Road Lahore; Liberty Market Lahore; Emporium Mall Lahore'   'distance from Lahore to Islamabad'
"""

import html
import json
import math
import re
import time
import urllib.parse
from pathlib import Path

from ai_pc.core.config import STATE
from ai_pc.hub.http import Api

NAME, LABEL = "maps", "Maps: places to KML, GPX, GeoJSON; distances; Google Maps routes"
EXAMPLES = ["map of: Hall Road Lahore; Liberty Market Lahore; Emporium Mall Lahore", "distance from Lahore to Islamabad"]
CACHE = STATE / "apps" / "geocode.json"
UA = {"User-Agent": "AI-PC/1.0 (personal desktop maps)"}
TRANSPORT = None  # tests put a fake here
_last = [0.0]


def geocode(place, cache=None):
    """'Liberty Market Lahore' -> (lat, lon, the name OpenStreetMap gives it); '31.52,74.35' is taken as it is."""
    m = re.fullmatch(r"\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*", place)
    if m:
        return float(m.group(1)), float(m.group(2)), place.strip()
    path = Path(cache or CACHE)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    key = " ".join(place.lower().split())
    if key in data:
        return tuple(data[key])
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0 and TRANSPORT is None:
        time.sleep(wait)  # Nominatim's rule: at most one request a second
    _last[0] = time.time()
    r = Api("https://nominatim.openstreetmap.org", headers=UA, service="nominatim", transport=TRANSPORT).get(
        "search", params={"q": place, "format": "jsonv2", "limit": 1}
    )
    if not r:
        raise ValueError(f"'{place}' was not found on OpenStreetMap: add the city, e.g. '{place}, Lahore'")
    hit = (float(r[0]["lat"]), float(r[0]["lon"]), r[0].get("display_name", place))
    data[key] = hit
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return hit


def km(a, b):
    (la1, lo1), (la2, lo2) = a[:2], b[:2]
    p1, p2, dl = math.radians(la1), math.radians(la2), math.radians(lo2 - lo1)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def gmaps_link(names, pts):
    q = {"api": "1", "origin": f"{pts[0][0]:.6f},{pts[0][1]:.6f}", "destination": f"{pts[-1][0]:.6f},{pts[-1][1]:.6f}"}
    if len(pts) > 2:
        q["waypoints"] = "|".join(f"{p[0]:.6f},{p[1]:.6f}" for p in pts[1:-1][:9])
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(q)


def make(places, out, name="places", cache=None):
    pts = [geocode(p, cache) for p in places]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    marks = "".join(
        f"<Placemark><name>{html.escape(n)}</name><description>{html.escape(p[2])}</description><Point><coordinates>{p[1]:.6f},{p[0]:.6f},0"
        f"</coordinates></Point></Placemark>"
        for n, p in zip(places, pts)
    )
    route = (
        ""
        if len(pts) < 2
        else (
            "<Placemark><name>Route (in order)</name><LineString><tessellate>1</tessellate><coordinates>"
            + " ".join(f"{p[1]:.6f},{p[0]:.6f},0" for p in pts)
            + "</coordinates></LineString></Placemark>"
        )
    )
    (out / f"{name}.kml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{html.escape(name)}'
        f"</name>{marks}{route}</Document></kml>",
        encoding="utf-8",
    )
    wpts = "".join(f'<wpt lat="{p[0]:.6f}" lon="{p[1]:.6f}"><name>{html.escape(n)}</name></wpt>' for n, p in zip(places, pts))
    trk = (
        ""
        if len(pts) < 2
        else "<trk><name>Route</name><trkseg>" + "".join(f'<trkpt lat="{p[0]:.6f}" lon="{p[1]:.6f}"/>' for p in pts) + "</trkseg></trk>"
    )
    (out / f"{name}.gpx").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="AI PC" xmlns="http://www.topografix.com/GPX/1/1">{wpts}{trk}</gpx>',
        encoding="utf-8",
    )
    feats = [
        {"type": "Feature", "properties": {"name": n, "found_as": p[2]}, "geometry": {"type": "Point", "coordinates": [p[1], p[0]]}}
        for n, p in zip(places, pts)
    ]
    if len(pts) > 1:
        feats.append(
            {"type": "Feature", "properties": {"name": "Route"}, "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in pts]}}
        )
    (out / f"{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, indent=1), encoding="utf-8")
    legs = [km(a, b) for a, b in zip(pts, pts[1:])]
    return pts, legs, [out / f"{name}.{e}" for e in ("kml", "gpx", "geojson")], gmaps_link(places, pts) if len(pts) > 1 else None


def check(places, files):
    from lxml import etree

    k = etree.parse(str(files[0]))
    n_k = len(k.findall(".//{http://www.opengis.net/kml/2.2}Point"))
    g = etree.parse(str(files[1]))
    n_g = len(g.findall("{http://www.topografix.com/GPX/1/1}wpt"))
    j = json.loads(files[2].read_text(encoding="utf-8"))
    n_j = sum(1 for f in j["features"] if f["geometry"]["type"] == "Point")
    return [("KML, GPX and GeoJSON each hold every place", n_k == n_g == n_j == len(places))]


def parse(text, ctx):
    m = re.search(r"\bdistance\s+(?:from|between)\s+(.+?)\s+(?:to|and)\s+(.+?)\s*\??$", text, re.I)
    if m:
        return {"op": "distance", "places": [m.group(1).strip(), m.group(2).strip()]}
    m = re.match(r"^\s*(?:make\s+(?:a\s+)?)?(?:map|route|kml|gpx)\s*(?:of|for)?\s*(?:'([^']*)'|\"([^\"]*)\")?\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        places = [p.strip(" .") for p in re.split(r";|\n|\s+->\s+", m.group(3)) if p.strip(" .")]
        return {"op": "map", "places": places, "name": m.group(1) or m.group(2) or "places"} if places else None
    return None


def run(op, ctx):
    if op["op"] == "distance":
        a, b = (geocode(p) for p in op["places"])
        return (
            f"{op['places'][0]} to {op['places'][1]}: {km(a, b):,.1f} km in a straight line (the road is longer). Directions: "
            f"{gmaps_link(op['places'], [a, b])}"
        )
    pts, legs, files, link = make(op["places"], Path(ctx["out"]) / "maps", re.sub(r"[^\w-]+", "_", op.get("name", "places")))
    bad = [w for w, ok in check(op["places"], files) if not ok]
    return (
        f"{len(pts)} places mapped"
        + (f", {sum(legs):,.1f} km in straight lines in this order" if legs else "")
        + ": "
        + ", ".join(str(f) for f in files)
        + (" (checked)" if not bad else " NOT right: " + ", ".join(bad))
        + (f". Route in Google Maps: {link}" if link else "")
        + ". Open the KML in Google Earth or import it into Google My Maps."
    )

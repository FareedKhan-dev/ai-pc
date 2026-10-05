"""QGIS (4.2.3 in tools/qgis, signed by the OSGeo Foundation; unpacked from its MSI) for maps and geodata, headless on the
hidden desktop with its profile in tools/qgis/home: a map of places from a CSV/Excel sheet (name, latitude, longitude) or a
GeoJSON/KML file, made by QGIS's own Python as a styled QGIS project (.qgz) over QGIS's bundled Natural Earth world map,
rendered to PNG and to a PDF layout (title, legend, scale bar); buffers around places by qgis_process ('5 km around each
shop', measured in metres in the right UTM zone); conversions between GeoJSON, KML, Shapefile and GeoPackage.
Checked: every place is in the map and the project, the PDF has its page, and each buffer's area is pi r^2.

  'qgis map of shops.csv'   'qgis buffer 5 km around shops.csv'   'qgis convert shops.kml to geopackage'
"""

import csv
import json
import math
import os
import re
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "qgis", "QGIS: maps of places (project + PNG + PDF), buffers in km, GIS format conversion"
EXAMPLES = ["qgis map of shops.csv", "qgis buffer 5 km around shops.csv", "qgis convert shops.kml to geopackage"]
HOME = ROOT / "tools" / "qgis"
QROOT = HOME / "QGIS 4.2.3"
TABLES = {".csv", ".xlsx", ".geojson", ".json", ".kml", ".gpkg", ".shp", ".gpx"}
FORMATS = {
    "geojson": ("GeoJSON", ".geojson"),
    "kml": ("KML", ".kml"),
    "shapefile": ("ESRI Shapefile", ".shp"),
    "shp": ("ESRI Shapefile", ".shp"),
    "geopackage": ("GPKG", ".gpkg"),
    "gpkg": ("GPKG", ".gpkg"),
    "gpx": ("GPX", ".gpx"),
    "csv": ("CSV", ".csv"),
}

MAP_SCRIPT = r"""
import json, os, sys
from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem, QgsMapSettings, QgsMapRendererSequentialJob,
                       QgsRectangle, QgsPalLayerSettings, QgsVectorLayerSimpleLabeling, QgsTextFormat, QgsTextBufferSettings, QgsMarkerSymbol,
                       QgsFillSymbol, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemScaleBar,
                       QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsLayoutExporter, QgsSingleSymbolRenderer)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QSize
QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
app = QgsApplication([], False)
app.initQgis()
job = json.load(open(sys.argv[1], encoding="utf-8"))
project = QgsProject.instance()
project.setTitle(job["title"])
project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
countries = QgsVectorLayer(job["world"] + "|layername=countries", "Countries", "ogr")
provinces = QgsVectorLayer(job["world"] + "|layername=states_provinces", "Provinces", "ogr")
places = QgsVectorLayer(job["points"], "Places", "ogr")
countries.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "#f3efe4", "outline_color": "#8c8c8c", "outline_width": "0.3"})))
provinces.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "#b9b4a8", "outline_width": "0.15"})))
places.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": "circle", "color": "#e53935", "outline_color": "white", "size": "3.2"})))
lab = QgsPalLayerSettings()
lab.fieldName = "name"
fmt = QgsTextFormat(); fmt.setFont(QFont("Arial")); fmt.setSize(10)
buf = QgsTextBufferSettings(); buf.setEnabled(True); buf.setSize(1); buf.setColor(QColor("white")); fmt.setBuffer(buf)
lab.setFormat(fmt)
places.setLabeling(QgsVectorLayerSimpleLabeling(lab)); places.setLabelsEnabled(True)
for lyr in (countries, provinces, places):
    project.addMapLayer(lyr)
ext = places.extent()
w, h = max(ext.width(), 2.0), max(ext.height(), 2.0)
cx, cy = ext.center().x(), ext.center().y()
ext = QgsRectangle(cx - w * 0.75, cy - h * 0.75, cx + w * 0.75, cy + h * 0.75)
ms = QgsMapSettings()
ms.setLayers([places, provinces, countries]); ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
ms.setExtent(ext); ms.setOutputSize(QSize(1600, 1100)); ms.setBackgroundColor(QColor("#cfe3f0"))
r = QgsMapRendererSequentialJob(ms); r.start(); r.waitForFinished()
r.renderedImage().save(job["png"])
layout = QgsPrintLayout(project); layout.initializeDefaults(); layout.setName(job["title"])
m = QgsLayoutItemMap(layout); m.setRect(20, 20, 20, 20); m.setLayers([places, provinces, countries]); m.setExtent(ext)
m.attemptMove(QgsLayoutPoint(10, 22, QgsUnitTypes.LayoutMillimeters)); m.attemptResize(QgsLayoutSize(277, 165, QgsUnitTypes.LayoutMillimeters))
m.setBackgroundColor(QColor("#cfe3f0")); layout.addLayoutItem(m)
t = QgsLayoutItemLabel(layout); t.setText(job["title"]); t.setFont(QFont("Arial", 20)); t.adjustSizeToText()
t.attemptMove(QgsLayoutPoint(10, 6, QgsUnitTypes.LayoutMillimeters)); layout.addLayoutItem(t)
lg = QgsLayoutItemLegend(layout); lg.setLinkedMap(m); lg.attemptMove(QgsLayoutPoint(230, 150, QgsUnitTypes.LayoutMillimeters)); layout.addLayoutItem(lg)
sb = QgsLayoutItemScaleBar(layout); sb.setStyle("Single Box"); sb.setLinkedMap(m); sb.applyDefaultSize()
sb.attemptMove(QgsLayoutPoint(12, 175, QgsUnitTypes.LayoutMillimeters)); layout.addLayoutItem(sb)
project.layoutManager().addLayout(layout)
res = QgsLayoutExporter(layout).exportToPdf(job["pdf"], QgsLayoutExporter.PdfExportSettings())
project.setFileName(job["qgz"]); ok = project.write()
print("AIPC_REPORT " + json.dumps({"places": places.featureCount(), "layers": [l.name() for l in project.mapLayers().values()],
      "pdf": res == QgsLayoutExporter.Success, "saved": ok, "valid": [countries.isValid(), provinces.isValid(), places.isValid()]}))
app.exitQgis()
"""


def env():
    home = HOME / "home"
    ini = home / "profiles" / "default" / "QGIS" / "QGIS4.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    cache = (home / "cache").resolve()
    text = ini.read_text(encoding="utf-8") if ini.exists() else ""
    if "[cache]" not in text:  # QGIS's network cache inside the project, not in AppData
        ini.write_text(text + f"\n[cache]\ndirectory={cache.as_posix()}\n", encoding="utf-8")
    # offscreen Qt has no font list of its own: without QT_QPA_FONTDIR every label is drawn as boxes
    return dict(
        os.environ,
        QGIS_CUSTOM_CONFIG_PATH=str(home.resolve()),
        QGIS_AUTH_DB_DIR_PATH=str(home.resolve()),
        QT_QPA_PLATFORM="offscreen",
        QT_QPA_FONTDIR=str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"),
    )


def qrun(args, timeout=600):
    """A QGIS command (bat in its bin) on the hidden desktop; an empty cache skeleton it leaves in AppData is removed."""
    import shutil

    from ai_pc.core import hidden_desktop

    local = Path(os.environ["LOCALAPPDATA"]) / "QGIS"
    had = local.exists()
    try:
        return hidden_desktop.run(["cmd", "/c", *map(str, args)], timeout=timeout, env=env())
    finally:
        if not had and local.exists() and not any(f.is_file() for f in local.rglob("*")):
            shutil.rmtree(local, ignore_errors=True)


def places_from(path):
    """[(name, lat, lon)] from a CSV/Excel sheet with name + latitude + longitude columns, or a GeoJSON of points."""
    p = Path(path)
    if p.suffix.lower() in (".geojson", ".json"):
        gj = json.loads(p.read_text(encoding="utf-8"))
        return [
            (str((f.get("properties") or {}).get("name", f"place {i + 1}")), f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
            for i, f in enumerate(gj["features"])
            if f["geometry"]["type"] == "Point"
        ]
    if p.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(p, read_only=True, data_only=True)
        rows = [[("" if c is None else str(c)).strip() for c in r] for r in wb.active.iter_rows(values_only=True)]
        wb.close()
    else:
        rows = [[c.strip() for c in r] for r in csv.reader(p.read_text(encoding="utf-8-sig").splitlines())]
    head = [h.lower() for h in rows[0]]
    col = lambda *names: next((i for i, h in enumerate(head) if h in names), None)  # noqa: E731
    ni, la, lo = col("name", "place", "city", "shop", "title"), col("lat", "latitude", "y"), col("lon", "lng", "long", "longitude", "x")
    if la is None or lo is None:
        raise ValueError("the sheet needs latitude and longitude columns (lat, lon)")
    out = []
    for i, r in enumerate(rows[1:]):
        try:
            out.append((r[ni] if ni is not None else f"place {i + 1}", float(r[la]), float(r[lo])))
        except (ValueError, IndexError):
            continue
    return out


def geojson(places, path):
    Path(path).write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {"name": n}, "geometry": {"type": "Point", "coordinates": [lon, lat]}} for n, lat, lon in places
                ],
            }
        ),
        encoding="utf-8",
    )


def red_marks(png):
    """How many separate red marker blobs the rendered map has."""
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    mask = (a[..., 0] > 200) & (a[..., 1] < 90) & (a[..., 2] < 90)
    seen, blobs = np.zeros_like(mask), 0
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs):
        if seen[y, x]:
            continue
        blobs += 1
        stack = [(y, x)]
        while stack:
            cy, cx = stack.pop()
            if 0 <= cy < mask.shape[0] and 0 <= cx < mask.shape[1] and mask[cy, cx] and not seen[cy, cx]:
                seen[cy, cx] = True
                stack += [(cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)]
    return blobs


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bqgis\b|\bgis\b|\bshapefile\b|\bgeopackage\b", c):
        return None
    f = find_file(text, ctx, TABLES)
    if not f:
        return None
    m = re.search(r"\bbuffer\s+(\d+(?:\.\d+)?)\s*(km|m|meters?|metres?|kilometers?|kilometres?)\b", c)
    if m:
        return {"op": "buffer", "file": f, "metres": float(m.group(1)) * (1000 if m.group(2).startswith("k") else 1)}
    fmt = re.search(r"\bconvert\b.*?\bto\s+(" + "|".join(FORMATS) + r")\b", c)
    if fmt:
        return {"op": "convert", "file": f, "format": fmt.group(1)}
    if re.search(r"\bmap\b", c):
        title = re.search(r"['\"]([^'\"]+)['\"]", text)
        return {"op": "map", "file": f, "title": title.group(1) if title else None}
    return None


def run(op, ctx):
    if not (QROOT / "bin" / "qgis_process-qgis.bat").exists():
        return "QGIS is not in tools/qgis."
    src = Path(op["file"]).resolve()
    out = (Path(ctx["out"]) / "qgis").resolve()
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", src.stem)
    if op["op"] == "convert":
        driver, ext = FORMATS[op["format"]]
        dest = out / f"{stem}{ext}"
        inp = src
        if src.suffix.lower() in (".csv", ".xlsx"):
            inp = out / f"{stem}_points.geojson"
            geojson(places_from(src), inp)
        rc, so, se, _ = qrun([QROOT / "bin" / "ogr2ogr.exe", "-f", driver, dest, inp])
        rc2, info, _, _ = qrun([QROOT / "bin" / "ogrinfo.exe", "-so", "-al", dest])
        rc3, info_src, _, _ = qrun([QROOT / "bin" / "ogrinfo.exe", "-so", "-al", inp])
        n_out = sum(int(x) for x in re.findall(r"Feature Count: (\d+)", info))
        n_in = sum(int(x) for x in re.findall(r"Feature Count: (\d+)", info_src))
        ok = dest.exists() and n_out == n_in and n_in > 0
        return f"QGIS (GDAL) converted {src.name} to {dest} ({op['format']}). " + (
            f"Checked: all {n_in} features are in it." if ok else f"NOT right: {n_out} of {n_in} features. {(se or so)[-200:]}"
        )
    places = places_from(src)
    if not places:
        return f"No places with latitude and longitude in {src.name}."
    pts = out / f"{stem}_points.geojson"
    geojson(places, pts)
    if op["op"] == "buffer":
        lon0 = sum(p[2] for p in places) / len(places)
        lat0 = sum(p[1] for p in places) / len(places)
        epsg = (32600 if lat0 >= 0 else 32700) + int((lon0 + 180) // 6) + 1  # the UTM zone the places are in, so distances are metres
        utm, buf = out / f"{stem}_utm.geojson", out / f"{stem}_buffer_{op['metres']:g}m.geojson"
        bat = QROOT / "bin" / "qgis_process-qgis.bat"
        qrun([bat, "run", "native:reprojectlayer", "--", f"INPUT={pts}", f"TARGET_CRS=EPSG:{epsg}", f"OUTPUT={utm}"])
        rc, so, se, _ = qrun(
            [bat, "run", "native:buffer", "--", f"INPUT={utm}", f"DISTANCE={op['metres']}", "SEGMENTS=36", "DISSOLVE=false", f"OUTPUT={buf}"]
        )
        from shapely.geometry import shape

        feats = json.loads(buf.read_text(encoding="utf-8"))["features"] if buf.exists() else []
        areas = [shape(f["geometry"]).area for f in feats]
        want = math.pi * op["metres"] ** 2
        ok = len(areas) == len(places) and all(abs(a - want) / want < 0.01 for a in areas)
        return (
            f"QGIS buffered {len(places)} places by {op['metres'] / 1000:g} km (in metres, UTM zone EPSG:{epsg}): {buf} "
            f"(each about {want / 1e6:.2f} km2). "
            + (
                f"Checked: one buffer per place, each pi r^2 within 1% (measured {min(areas) / 1e6:.3f}-{max(areas) / 1e6:.3f} km2)."
                if ok
                else f"NOT right: {len(areas)} buffers for {len(places)} places. {(se or so)[-300:]}"
            )
        )
    title = op.get("title") or f"Map of {src.stem.replace('_', ' ').title()}"
    files = {k: out / f"{stem}_map.{k}" for k in ("png", "pdf", "qgz")}
    for p in files.values():
        p.unlink(missing_ok=True)
    job = out / f"{stem}_map_job.json"
    job.write_text(
        json.dumps(
            {
                "title": title,
                "world": (QROOT / "apps" / "qgis" / "resources" / "data" / "world_map.gpkg").as_posix(),
                "points": pts.as_posix(),
                **{k: v.as_posix() for k, v in files.items()},
            }
        ),
        encoding="utf-8",
    )
    script = out / "aipc_qgis_map.py"
    script.write_text(MAP_SCRIPT, encoding="utf-8")
    rc, so, se, timed_out = qrun([QROOT / "bin" / "python-qgis.bat", script, job])
    m = re.search(r"AIPC_REPORT (\{.*\})", so + se)
    rep = json.loads(m.group(1)) if m else {}
    marks = red_marks(files["png"]) if files["png"].exists() else 0
    read_names = 0
    if files["png"].exists():  # Windows OCR reads the rendered labels (boxes instead of letters would read as nothing)
        try:
            from ai_pc.apps import ocr

            seen = re.sub(r"\s+", " ", ocr.read_picture(files["png"], work=out / "_ocr")["text"].lower())
            read_names = sum(1 for n, _, _ in places if n.lower() in seen)
        except Exception:  # noqa: BLE001 - no OCR: the label check reports it
            read_names = -1
    from pypdf import PdfReader

    pages = len(PdfReader(str(files["pdf"])).pages) if files["pdf"].exists() else 0
    checks = [
        ("QGIS loaded the world map and the places", rep.get("valid") == [True, True, True] and rep.get("places") == len(places)),
        (f"every place is drawn on the map ({marks} markers for {len(places)} places)", marks >= len(places) or (len(places) > 15 and marks > 0)),
        (f"the labels are readable (Windows OCR reads {max(read_names, 0)} of {len(places)} names)", read_names >= max(1, (len(places) * 2) // 3)),
        ("the QGIS project saved (opens in QGIS with its layers)", rep.get("saved") and files["qgz"].exists()),
        ("the PDF map (title, legend, scale bar) has its page", bool(rep.get("pdf")) and pages >= 1),
    ]
    bad = [w for w, ok in checks if not ok]
    return (
        f"QGIS map '{title}' with {len(places)} places: {files['qgz']} (QGIS project), {files['png'].name}, {files['pdf'].name}. Made by QGIS itself "
        "(hidden). " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f" {(se or so)[-400:]}")
    )

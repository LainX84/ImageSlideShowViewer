"""Mappa delle foto con posizione GPS: una pagina HTML (OpenStreetMap + Leaflet) con un
segnaposto e una miniatura per ogni foto, aperta nel browser predefinito.
"""
import base64
import html
import json
import os
import tempfile
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from . import APP_NAME, codecs, exifutil
from .i18n import tr
from .utils import is_video

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
<style>html,body,#map{{height:100%;margin:0;font-family:sans-serif}}
.pop img{{max-width:220px;max-height:220px;display:block;margin-bottom:4px}}
#title{{position:absolute;z-index:1000;top:10px;left:60px;background:#fff;padding:6px 10px;
border-radius:6px;box-shadow:0 1px 4px #0005;font-size:14px}}</style></head>
<body><div id="title">{title}</div><div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
const pts = {points};
const map = L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 19,
  attribution: '&copy; OpenStreetMap'}}).addTo(map);
const group = L.markerClusterGroup();
const bounds = [];
for (const p of pts) {{
  const m = L.marker([p.lat, p.lon]);
  m.bindPopup('<div class="pop">' + (p.img ? '<img src="' + p.img + '">' : '') +
              '<b>' + p.name + '</b><br>' + p.date + '<br><a href="' + p.url + '">' + p.open + '</a></div>');
  group.addLayer(m); bounds.push([p.lat, p.lon]);
}}
map.addLayer(group);
if (bounds.length) map.fitBounds(bounds, {{padding: [40, 40], maxZoom: 15}}); else map.setView([42, 12], 5);
</script></body></html>
"""


def collect(progress, paths):
    out = []
    for i, p in enumerate(paths):
        if progress(i, len(paths), tr("Lettura posizioni: {name}", name=os.path.basename(p))):
            raise InterruptedError
        if is_video(p):
            continue
        ex = exifutil.read(p)
        if not ex["gps"]:
            continue
        img, _e = codecs.read_qimage(p, 220)
        data = ""
        if not img.isNull():
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "JPG", 80)
            data = "data:image/jpeg;base64," + base64.b64encode(bytes(ba)).decode()
        d = time.strftime(tr("%d/%m/%Y %H:%M"), time.localtime(ex["date"])) if ex["date"] else ""
        out.append({"lat": ex["gps"][0], "lon": ex["gps"][1], "name": html.escape(os.path.basename(p)),
                    "date": d, "img": data, "url": QUrl.fromLocalFile(p.split("|")[0]).toString(),
                    "open": html.escape(tr("Apri il file"))})
    return out


def show_map(parent, paths, title):
    from .worker import run_with_progress
    pts = run_with_progress(parent, tr("Mappa delle foto…"), collect, paths)
    if pts is None:
        return
    if not pts:
        QMessageBox.information(parent, APP_NAME, tr("Nessuna foto con la posizione GPS."))
        return
    page = PAGE.format(title=html.escape(f"{title} – {len(pts)} " + tr("foto")),
                       points=json.dumps(pts))
    fd, path = tempfile.mkstemp(prefix="isv-mappa-", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(page)
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))

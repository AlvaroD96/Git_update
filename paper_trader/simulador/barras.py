"""Barras de 5 minutos de Yahoo (archivo guardado o en vivo) y la resolución de una operación.

Una operación se resuelve caminando las barras que vienen después de la entrada:
- si una barra abre por debajo del stop (gap), sale al precio de apertura;
- si una barra toca el stop y el objetivo a la vez, se asume el stop (conservador);
- si llega a la hora "flat by" sin tocar nada, sale al cierre de la última barra.
"""
import gzip
import json
import urllib.request
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
APERTURA = time(9, 30)


def cargar_chart(archivo=None, simbolo=None, rango="5d"):
    """Devuelve el JSON del chart v8 de Yahoo, desde un archivo o desde internet."""
    if archivo:
        p = Path(archivo)
        abrir = gzip.open if p.suffix == ".gz" else open
        with abrir(p, "rt") as f:
            return json.load(f)
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{simbolo}"
        f"?interval=5m&range={rango}&includePrePost=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def barras(chart):
    """Lista de barras completas de la sesión regular: dicts con dt (NY), o, h, l, c, v."""
    res = chart["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        dt = datetime.fromtimestamp(ts, NY)
        if dt.minute % 5 or dt.second or dt.time() < APERTURA or dt.time() >= time(16, 0):
            continue
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out.append({"dt": dt, "o": o, "h": h, "l": l, "c": c, "v": q["volume"][i] or 0})
    return out


def sesiones(chart):
    """Fechas (date) con sesión completa en el archivo, en orden."""
    por_dia = {}
    for b in barras(chart):
        por_dia.setdefault(b["dt"].date(), 0)
        por_dia[b["dt"].date()] += 1
    return [d for d, n in sorted(por_dia.items()) if n >= 70]


def _hm(s):
    h, m = s.split(":")
    return time(int(h), int(m))


def resolver(chart, fecha, hora_entrada, entrada, stop, objetivo, flat_by="15:55"):
    """Camina las barras después de la entrada. hora_entrada = cierre de la barra de entrada (HH:MM).

    Devuelve dict(precio, motivo, hora, terminado) o None si no hay barras después de la entrada.
    """
    t0, tf = _hm(hora_entrada), _hm(flat_by)
    dia = [b for b in barras(chart) if b["dt"].date() == fecha and b["dt"].time() >= t0]
    ultimo = None
    for b in dia:
        fin_t = _sumar5(b["dt"].time())  # la barra de 10:10 cierra a las 10:15
        if b["o"] <= stop:
            return dict(precio=round(b["o"], 2), motivo="stop (gap)", hora=_s(b["dt"].time()), terminado=True)
        if b["o"] >= objetivo:
            return dict(precio=round(b["o"], 2), motivo="objetivo (gap)", hora=_s(b["dt"].time()), terminado=True)
        if b["l"] <= stop:
            return dict(precio=stop, motivo="stop", hora=_s(fin_t), terminado=True)
        if b["h"] >= objetivo:
            return dict(precio=objetivo, motivo="objetivo", hora=_s(fin_t), terminado=True)
        ultimo = b
        if fin_t >= tf:
            return dict(precio=round(b["c"], 2), motivo="cierre (flat by)", hora=_s(fin_t), terminado=True)
    if ultimo is None:
        return None
    return dict(precio=round(ultimo["c"], 2), motivo="sigue abierta", hora=_s(_sumar5(ultimo["dt"].time())),
                terminado=False)


def _sumar5(t):
    m = t.hour * 60 + t.minute + 5
    return time(m // 60, m % 60)


def _s(t):
    return t.strftime("%H:%M")

"""Estrategias intradía (solo compras) sobre barras de 5 minutos.

Cada estrategia mira SOLO las barras ya cerradas (hoy[:i+1]) y las sesiones anteriores, y dice si la barra i
da la señal. La entrada es el cierre de esa barra; el stop lo propone la estrategia; el objetivo es
entrada + R x riesgo. Una señal por estrategia por día (la primera).

- orb       Ruptura del rango de apertura (igual que trader-entry / trader-exit)
- nivel20   Ruptura del máximo de 20 días (como `trader-entry --setup level`)
- vwap      Recupera el VWAP después de estar debajo
- bandera   Bandera alcista: subida fuerte, consolidación estrecha y ruptura
- rebote    Rebote de sobreventa: RSI(14) de 5 min cruza 30 hacia arriba en un día rojo
"""
import math
from datetime import time

from . import barras as B

MIN_ENTRADA = time(9, 45)    # no_entries_before de las skills
MAX_ENTRADA = time(15, 30)   # no_entries_after
RIESGO_MIN = 0.002           # stop a menos de 0.2 % de la entrada: demasiado justo para el spread
RIESGO_MAX = 0.04            # stop a más de 4 %: no es un day trade


def _abajo(x):
    return math.floor(x * 100 + 1e-9) / 100


def fin_barra(b):
    return B._sumar5(b["dt"].time())


class Contexto:
    """Lo que se sabe antes de abrir: sesiones previas (listas de barras)."""

    def __init__(self, previas):
        self.previas = previas
        self.prev_close = previas[-1][-1]["c"] if previas else None
        ult20 = previas[-20:]
        self.max20 = max(max(b["h"] for b in d) for d in ult20) if len(ult20) == 20 else None
        # cierres previos para calentar el RSI
        self.cierres_previos = [b["c"] for d in previas[-2:] for b in d]


def vwap(hoy, i):
    pv = vol = 0.0
    for b in hoy[: i + 1]:
        tp = (b["h"] + b["l"] + b["c"]) / 3
        pv += tp * b["v"]
        vol += b["v"]
    return pv / vol if vol else hoy[i]["c"]


def serie_vwap(hoy):
    out, pv, vol = [], 0.0, 0.0
    for b in hoy:
        tp = (b["h"] + b["l"] + b["c"]) / 3
        pv += tp * b["v"]
        vol += b["v"]
        out.append(pv / vol if vol else b["c"])
    return out


def rsi(cierres, n=14):
    """RSI de Wilder; devuelve lista alineada con cierres (None al principio)."""
    out = [None] * len(cierres)
    if len(cierres) <= n:
        return out
    g = p = 0.0
    for k in range(1, n + 1):
        d = cierres[k] - cierres[k - 1]
        g += max(d, 0)
        p += max(-d, 0)
    g, p = g / n, p / n
    out[n] = 100 if p == 0 else 100 - 100 / (1 + g / p)
    for k in range(n + 1, len(cierres)):
        d = cierres[k] - cierres[k - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        p = (p * (n - 1) + max(-d, 0)) / n
        out[k] = 100 if p == 0 else 100 - 100 / (1 + g / p)
    return out


# --- reglas: cada una devuelve (stop, motivo) si la barra i da la señal, o None -------------------

def _orb(hoy, i, ctx):
    if i < 3:
        return None
    orh = max(b["h"] for b in hoy[:3])
    orl = min(b["l"] for b in hoy[:3])
    if hoy[i]["c"] <= orh:
        return None
    return _abajo((orh + orl) / 2), f"cerró en {hoy[i]['c']:.2f}, sobre el máximo del rango de apertura {orh:.2f}"


def _nivel20(hoy, i, ctx):
    if ctx.max20 is None or hoy[i]["c"] <= ctx.max20:
        return None
    stop = _abajo(min(b["l"] for b in hoy[max(0, i - 2): i + 1]))
    return stop, f"cerró en {hoy[i]['c']:.2f}, sobre el máximo de 20 días {ctx.max20:.2f}"


def _vwap(hoy, i, ctx):
    if i < 6:
        return None
    vw = serie_vwap(hoy[: i + 1])
    if hoy[i]["c"] <= vw[i]:
        return None
    if not all(hoy[k]["c"] < vw[k] for k in range(i - 3, i)):
        return None
    stop = _abajo(min(b["l"] for b in hoy[i - 3: i + 1]))
    return stop, f"recuperó el VWAP {vw[i]:.2f} tras 3 barras debajo"


def _bandera(hoy, i, ctx):
    apertura = hoy[0]["o"]
    for largo in range(3, 9):              # barras de la bandera
        p = i - largo - 1                  # la barra del máximo (la punta del mástil)
        if p < 1:
            break
        bandera = hoy[p + 1: i]
        punta = hoy[p]["h"]
        if punta < max(b["h"] for b in hoy[: p + 1]):
            continue                       # la punta tiene que ser el máximo del día hasta ahí
        base = min(b["l"] for b in hoy[: p + 1])
        mastil = punta - base
        if mastil < apertura * 0.015:      # subida de al menos 1.5 %
            continue
        alto = max(b["h"] for b in bandera)
        bajo = min(b["l"] for b in bandera)
        if alto > punta or bajo < punta - mastil * 0.5 or (alto - bajo) > mastil * 0.5:
            continue                       # retroceso de más de la mitad o bandera muy ancha
        if hoy[i]["c"] > punta:
            return _abajo(bajo), (f"mástil +{100 * mastil / base:.1f}%, bandera de {largo} barras "
                                  f"({bajo:.2f}–{alto:.2f}); cerró sobre {punta:.2f}")
    return None


def _rebote(hoy, i, ctx):
    if ctx.prev_close is None or i < 2:
        return None
    minimo = min(b["l"] for b in hoy[: i + 1])
    if minimo > ctx.prev_close * 0.985:    # el día tiene que haber caído al menos 1.5 %
        return None
    r = rsi(ctx.cierres_previos + [b["c"] for b in hoy[: i + 1]])
    if r[-2] is None or not (r[-2] < 30 <= r[-1]) or hoy[i]["c"] <= hoy[i]["o"]:
        return None
    return _abajo(minimo), f"RSI(14, 5 min) cruzó 30 hacia arriba ({r[-1]:.0f}) con el día {100 * (hoy[i]['c'] / ctx.prev_close - 1):+.1f}%"


ESTRATEGIAS = {
    "orb": ("Ruptura del rango de apertura", _orb),
    "nivel20": ("Ruptura del máximo de 20 días", _nivel20),
    "vwap": ("Recupera el VWAP", _vwap),
    "bandera": ("Bandera alcista", _bandera),
    "rebote": ("Rebote de sobreventa (RSI)", _rebote),
}
OPCIONES = [(k, v[0]) for k, v in ESTRATEGIAS.items()]


def nombre(clave):
    return ESTRATEGIAS.get(clave, (clave,))[0]


def senal(clave, hoy, i, ctx, objetivo_r=2.0):
    """La señal de la estrategia en la barra i, solo si es la primera del día. dict o None."""
    regla = ESTRATEGIAS[clave][1]
    if not (MIN_ENTRADA <= fin_barra(hoy[i]) <= MAX_ENTRADA):
        return None
    r = regla(hoy, i, ctx)
    if not r:
        return None
    for j in range(i):                     # ¿ya hubo una señal antes hoy? entonces esta no cuenta
        if MIN_ENTRADA <= fin_barra(hoy[j]) and regla(hoy, j, ctx):
            return None
    stop, motivo = r
    entrada = round(hoy[i]["c"], 2)
    riesgo = entrada - stop
    if riesgo <= entrada * RIESGO_MIN or riesgo > entrada * RIESGO_MAX:
        return None
    return {
        "estrategia": clave, "nombre": nombre(clave), "indice": i,
        "hora": fin_barra(hoy[i]).strftime("%H:%M"), "entrada": entrada, "stop": stop,
        "objetivo": round(entrada + objetivo_r * riesgo, 2), "riesgo": round(riesgo, 2), "motivo": motivo,
    }


def primera_senal(clave, hoy, ctx, objetivo_r=2.0, hasta=None):
    regla = ESTRATEGIAS[clave][1]
    for i in range(len(hoy) if hasta is None else min(hasta + 1, len(hoy))):
        if not (MIN_ENTRADA <= fin_barra(hoy[i]) <= MAX_ENTRADA):
            continue
        if regla(hoy, i, ctx):
            # es la primera vez que la regla se cumple: si el riesgo no sirve, ese día no hay operación
            return senal(clave, hoy, i, ctx, objetivo_r)
    return None


def dias(chart):
    """{fecha: [barras]} solo con sesiones completas (78 barras)."""
    por_dia = {}
    for b in B.barras(chart):
        por_dia.setdefault(b["dt"].date(), []).append(b)
    return {d: bs for d, bs in sorted(por_dia.items())}


def contexto(todos, fecha):
    previas = [bs for d, bs in todos.items() if d < fecha and len(bs) >= 70]
    return Contexto(previas)


def resolver(bars_despues, entrada, stop, objetivo, flat_by="15:55"):
    """Igual que barras.resolver pero sobre una lista de barras ya filtrada."""
    tf = B._hm(flat_by)
    ultimo = None
    for b in bars_despues:
        fin = fin_barra(b)
        if b["o"] <= stop:
            return dict(precio=round(b["o"], 2), motivo="stop (gap)", hora=B._s(b["dt"].time()), terminado=True)
        if b["o"] >= objetivo:
            return dict(precio=round(b["o"], 2), motivo="objetivo (gap)", hora=B._s(b["dt"].time()), terminado=True)
        if b["l"] <= stop:
            return dict(precio=stop, motivo="stop", hora=B._s(fin), terminado=True)
        if b["h"] >= objetivo:
            return dict(precio=objetivo, motivo="objetivo", hora=B._s(fin), terminado=True)
        ultimo = b
        if fin >= tf:
            return dict(precio=round(b["c"], 2), motivo="cierre (flat by)", hora=B._s(fin), terminado=True)
    if ultimo is None:
        return None
    return dict(precio=round(ultimo["c"], 2), motivo="sigue abierta", hora=B._s(fin_barra(ultimo)), terminado=False)


def backtest(clave, todos, fecha, objetivo_r=2.0, max_dias=40):
    """La misma estrategia en las sesiones ANTERIORES a fecha (nunca mira el día que estás practicando)."""
    fechas = [d for d, bs in todos.items() if d < fecha and len(bs) >= 70][-max_dias:]
    trades = []
    for d in fechas:
        hoy = todos[d]
        ctx = contexto(todos, d)
        s = primera_senal(clave, hoy, ctx, objetivo_r)
        if not s:
            continue
        r = resolver(hoy[s["indice"] + 1:], s["entrada"], s["stop"], s["objetivo"])
        if not r:
            continue
        R = round((r["precio"] - s["entrada"]) / s["riesgo"], 2)
        trades.append({"fecha": str(d), "hora": s["hora"], "entrada": s["entrada"], "salida": r["precio"],
                       "motivo": r["motivo"], "R": R})
    n = len(trades)
    rs = [t["R"] for t in trades]
    return {
        "estrategia": clave, "nombre": nombre(clave), "sesiones": len(fechas), "senales": n,
        "objetivo": sum(1 for t in trades if t["motivo"].startswith("objetivo")),
        "stop": sum(1 for t in trades if t["motivo"].startswith("stop")),
        "cierre": sum(1 for t in trades if t["motivo"].startswith("cierre")),
        "ganadoras": sum(1 for r in rs if r > 0),
        "pct": round(100 * sum(1 for r in rs if r > 0) / n) if n else None,
        "r_prom": round(sum(rs) / n, 3) if n else None,
        "r_total": round(sum(rs), 2),
        "trades": trades[-12:],
    }

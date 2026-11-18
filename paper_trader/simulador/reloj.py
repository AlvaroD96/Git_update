"""Modo reloj: una sesión pasada que avanza barra por barra.

Solo ves las barras ya cerradas. En cualquier momento puedes comprar (al cierre de la última barra) con el stop
y el objetivo de una estrategia o los tuyos; la app corre la máquina del tiempo, el tamaño y el riesgo en ese
instante. Con la posición abierta, cada barra nueva revisa el stop y el objetivo; puedes vender a mano;
a la hora "flat by" se cierra sola.
"""
import random
from datetime import date
from functools import lru_cache

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import barras as B
from . import estrategias as E
from . import pipeline
from .models import Operacion, SesionReloj


@lru_cache(maxsize=8)
def _todos(ruta):
    return E.dias(B.cargar_chart(archivo=ruta))


def datos(ses):
    todos = _todos(ses.archivo_datos)
    hoy = todos[ses.fecha]
    return hoy, E.contexto(todos, ses.fecha), todos


def _hora(b):
    return E.fin_barra(b).strftime("%H:%M")


# --- avanzar ---------------------------------------------------------------------------------------

def _revisar_barra(ses, b):
    """Una barra nueva: ¿tocó el stop o el objetivo de lo que está abierto? ¿llegó la hora de cerrar?"""
    for op in ses.operaciones.filter(estado=Operacion.ABIERTA):
        r = E.resolver([b], op.entrada, op.stop, op.objetivo, op.flat_by)
        if r and r["terminado"]:
            pipeline.cerrar(op, r["precio"], r["motivo"], r["hora"])
            op.save()
            ses.log(r["hora"], f"Cerrada por {r['motivo']} a ${r['precio']:.2f}: {op.pnl:+.2f} ({op.r_multiple:+.2f}R)")


def _senales_en(hoy, i, ctx, objetivo_r):
    return [s for k in E.ESTRATEGIAS if (s := E.senal(k, hoy, i, ctx, objetivo_r))]


def avanzar(ses, n=1, hasta_senal=False):
    hoy, ctx, _ = datos(ses)
    r_obj = ses.cuenta.objetivo_r
    for _ in range(n):
        if ses.indice >= len(hoy):
            break
        b = hoy[ses.indice]
        ses.indice += 1
        _revisar_barra(ses, b)
        nuevas = _senales_en(hoy, ses.indice - 1, ctx, r_obj)
        for s in nuevas:
            ses.log(s["hora"], f"Señal «{s['nombre']}»: {s['motivo']}")
        if hasta_senal and nuevas:
            break
    if ses.indice >= len(hoy):
        terminar(ses)
    ses.save()


def terminar(ses):
    """Fin de la sesión: cierra lo abierto y calcula qué habría pasado con lo que descartaste."""
    hoy, _, _ = datos(ses)
    ses.indice = len(hoy)
    for op in ses.operaciones.filter(estado=Operacion.ABIERTA):
        pipeline.cerrar(op, hoy[-1]["c"], "cierre de la sesión", _hora(hoy[-1]))
        op.save()
    for op in ses.operaciones.filter(estado=Operacion.DESCARTADA, salida_precio__isnull=True):
        i0 = next((k for k, b in enumerate(hoy) if _hora(b) == op.hora_decision), None)
        if i0 is None:
            continue
        r = E.resolver(hoy[i0 + 1:], op.entrada, op.stop, op.objetivo, op.flat_by)
        if r and r["terminado"]:
            pipeline.cerrar(op, r["precio"], r["motivo"], r["hora"])
            op.save()
    if not ses.terminada:
        ses.log(_hora(hoy[-1]), "Fin de la sesión.")
    ses.terminada = True


# --- gráfico ----------------------------------------------------------------------------------------

def grafico(hoy, indice, ctx, ops):
    W, H, izq, der, arr, aba = 920, 360, 8, 70, 12, 26
    vis = hoy[:indice]
    paso = (W - izq - der) / 78
    niveles = []
    if indice >= 3:
        orh, orl = max(b["h"] for b in hoy[:3]), min(b["l"] for b in hoy[:3])
        niveles += [(orh, "var(--mut)", "máx. rango"), (orl, "var(--mut)", "mín. rango")]
    for op in ops:
        if op.estado in (Operacion.ABIERTA, Operacion.PENDIENTE):
            niveles += [(op.entrada, "var(--ac)", "entrada"), (op.stop, "var(--bad)", "stop"),
                        (op.objetivo, "var(--ok)", "objetivo")]
    lo = min(b["l"] for b in vis)
    hi = max(b["h"] for b in vis)
    if ctx.max20 and lo * 0.98 <= ctx.max20 <= hi * 1.02:
        niveles.append((ctx.max20, "var(--warn)", "máx. 20 días"))
    lo = min([lo] + [n[0] for n in niveles])
    hi = max([hi] + [n[0] for n in niveles])
    pad = (hi - lo) * 0.06 or hi * 0.005
    lo, hi = lo - pad, hi + pad

    def y(p):
        return arr + (hi - p) / (hi - lo) * (H - arr - aba)

    def x(k):
        return izq + k * paso + paso / 2

    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Gráfico de velas de 5 minutos" '
         f'style="display:block;font:11px system-ui">']
    for h in range(10, 16):  # líneas de hora
        k = (h * 60 - 570) / 5
        s.append(f'<line x1="{x(k) - paso / 2:.1f}" x2="{x(k) - paso / 2:.1f}" y1="{arr}" y2="{H - aba}" '
                 f'style="stroke:var(--bd)"/><text x="{x(k) - paso / 2:.1f}" y="{H - 8}" text-anchor="middle" '
                 f'style="fill:var(--mut)">{h}:00</text>')
    vw = E.serie_vwap(vis)
    if len(vis) > 1:
        pts = " ".join(f"{x(k):.1f},{y(v):.1f}" for k, v in enumerate(vw))
        s.append(f'<polyline points="{pts}" fill="none" style="stroke:#a855f7;stroke-width:1.5;opacity:.8"/>')
    for k, b in enumerate(vis):
        sube = b["c"] >= b["o"]
        col = "var(--ok)" if sube else "var(--bad)"
        top, bot = y(max(b["o"], b["c"])), y(min(b["o"], b["c"]))
        s.append(f'<line x1="{x(k):.1f}" x2="{x(k):.1f}" y1="{y(b["h"]):.1f}" y2="{y(b["l"]):.1f}" style="stroke:{col}"/>'
                 f'<rect x="{x(k) - paso * 0.35:.1f}" y="{top:.1f}" width="{paso * 0.7:.1f}" '
                 f'height="{max(bot - top, 1):.1f}" style="fill:{col}"><title>{_hora(b)} '
                 f'O {b["o"]:.2f} H {b["h"]:.2f} L {b["l"]:.2f} C {b["c"]:.2f}</title></rect>')
    for p, col, txt in niveles:
        s.append(f'<line x1="{izq}" x2="{W - der}" y1="{y(p):.1f}" y2="{y(p):.1f}" '
                 f'style="stroke:{col};stroke-dasharray:4 3"/>'
                 f'<text x="{W - der + 4}" y="{y(p) + 4:.1f}" style="fill:{col}">{p:.2f}</text>'
                 f'<text x="{W - der - 4}" y="{y(p) - 3:.1f}" text-anchor="end" style="fill:{col};font-size:10px">{txt}</text>')
    for op in ops:  # flechas de entrada y salida
        k = next((i for i, b in enumerate(vis) if _hora(b) == op.hora_decision), None)
        if k is not None and op.estado != Operacion.DESCARTADA:
            s.append(f'<path d="M{x(k):.1f},{y(op.entrada) + 6:.1f} l-5,9 h10 z" style="fill:var(--ac)"><title>compra {op.entrada}</title></path>')
        if op.salida_hora and op.estado == Operacion.CERRADA:
            k2 = next((i for i, b in enumerate(vis) if _hora(b) == op.salida_hora), None)
            if k2 is not None:
                s.append(f'<path d="M{x(k2):.1f},{y(op.salida_precio) - 6:.1f} l-5,-9 h10 z" style="fill:var(--warn)"><title>venta {op.salida_precio}</title></path>')
    ult = vis[-1]["c"]
    s.append(f'<rect x="{W - der + 1}" y="{y(ult) - 8:.1f}" width="{der - 2}" height="16" rx="3" style="fill:var(--tx)"/>'
             f'<text x="{W - der + 4}" y="{y(ult) + 4:.1f}" style="fill:var(--card);font-weight:600">{ult:.2f}</text>')
    s.append("</svg>")
    return mark_safe("".join(s))


# --- vistas -----------------------------------------------------------------------------------------

@require_POST
def nuevo(request):
    from .views import archivos_demo, cuenta_actual, fechas_practica
    demo = {d["simbolo"]: d for d in archivos_demo()}
    sim = request.POST.get("simbolo_demo", "")
    if sim not in demo:
        messages.error(request, "Elige un símbolo con datos guardados.")
        return redirect("panel")
    f = request.POST.get("fecha") or ""
    fecha = date.fromisoformat(f) if f else random.choice(fechas_practica(demo[sim]["ruta"]))
    est = request.POST.get("estrategia", "orb")
    ses = SesionReloj.objects.create(cuenta=cuenta_actual(), simbolo=sim, archivo_datos=demo[sim]["ruta"],
                                     fecha=fecha, estrategia=est if est in E.ESTRATEGIAS else "orb")
    ses.log("09:45", "Abre la sesión. Ya se ven las 3 barras del rango de apertura.")
    ses.save()
    return redirect("reloj", pk=ses.pk)


def ver(request, pk):
    ses = get_object_or_404(SesionReloj, pk=pk)
    hoy, ctx, todos = datos(ses)
    vis = hoy[: ses.indice]
    ops = list(ses.operaciones.order_by("pk"))
    abiertas = [o for o in ops if o.estado == Operacion.ABIERTA]
    pendiente = next((o for o in ops if o.estado == Operacion.PENDIENTE), None)
    precio = vis[-1]["c"]
    r_obj = ses.cuenta.objetivo_r
    senales = [] if ses.terminada else _senales_en(hoy, ses.indice - 1, ctx, r_obj)
    # stop sugerido para una compra manual: el mínimo de las últimas 3 barras
    stop_sug = E._abajo(min(b["l"] for b in vis[-3:]))
    if stop_sug >= precio:
        stop_sug = E._abajo(precio * 0.995)
    obj_sug = round(precio + r_obj * (precio - stop_sug), 2)
    for o in abiertas:
        o.latente = round((precio - o.entrada) * (o.acciones or 0), 2)
        o.r_latente = round((precio - o.entrada) / (o.entrada - o.stop), 2)
    return render(request, "simulador/reloj.html", {
        "ses": ses, "grafico": grafico(hoy, ses.indice, ctx, ops), "ops": ops, "abiertas": abiertas,
        "pendiente": pendiente, "precio": precio, "hora": _hora(vis[-1]), "senales": senales,
        "cambio": round(100 * (precio / ctx.prev_close - 1), 2) if ctx.prev_close else None,
        "vwap": round(E.serie_vwap(vis)[-1], 2), "stop_sug": stop_sug, "obj_sug": obj_sug,
        "estrategias": E.OPCIONES, "nombre_estrategia": E.nombre(ses.estrategia),
        "bt": E.backtest(ses.estrategia, todos, ses.fecha, r_obj),
        "eventos": list(reversed(ses.eventos))[:40], "barras_restantes": len(hoy) - ses.indice,
    })


@require_POST
def accion(request, pk):
    ses = get_object_or_404(SesionReloj, pk=pk)
    a = request.POST.get("accion", "")
    if ses.terminada and a not in ("estrategia",):
        return redirect("reloj", pk=pk)
    pendiente = ses.operaciones.filter(estado=Operacion.PENDIENTE).first()
    if a.startswith("avanzar") or a in ("senal", "final", "terminar"):
        if pendiente:
            messages.error(request, "Primero decide si tomas o descartas la operación analizada.")
            return redirect("detalle", pk=pendiente.pk)
        if a == "senal":
            avanzar(ses, 999, hasta_senal=True)
        elif a in ("final", "terminar"):
            avanzar(ses, 999)
        else:
            avanzar(ses, int(a.replace("avanzar", "") or 1))
    elif a == "estrategia":
        est = request.POST.get("estrategia")
        if est in E.ESTRATEGIAS:
            ses.estrategia = est
            ses.save()
    elif a == "vender":
        hoy, _, _ = datos(ses)
        b = hoy[ses.indice - 1]
        for op in ses.operaciones.filter(estado=Operacion.ABIERTA):
            pipeline.cerrar(op, b["c"], "venta manual", _hora(b))
            op.save()
            ses.log(_hora(b), f"Vendiste a mano a ${b['c']:.2f}: {op.pnl:+.2f} ({op.r_multiple:+.2f}R)")
        ses.save()
    elif a == "comprar":
        return _comprar(request, ses, pendiente)
    return redirect("reloj", pk=pk)


def _comprar(request, ses, pendiente):
    if pendiente:
        return redirect("detalle", pk=pendiente.pk)
    hoy, ctx, _ = datos(ses)
    b = hoy[ses.indice - 1]
    entrada = round(b["c"], 2)
    clave = request.POST.get("senal") or "manual"
    if clave != "manual":
        senal = E.senal(clave, hoy, ses.indice - 1, ctx, ses.cuenta.objetivo_r)
        if not senal:
            messages.error(request, "Esa señal ya no está activa.")
            return redirect("reloj", pk=ses.pk)
    else:
        try:
            from .views import numero
            stop = numero(request.POST["stop"])
            objetivo = numero(request.POST["objetivo"])
        except (KeyError, ValueError):
            messages.error(request, "Escribe el stop y el objetivo.")
            return redirect("reloj", pk=ses.pk)
        if not stop < entrada < objetivo:
            messages.error(request, f"Para comprar a ${entrada:.2f} el stop debe estar debajo y el objetivo encima.")
            return redirect("reloj", pk=ses.pk)
        senal = {"estrategia": "manual", "nombre": "Mi plan", "hora": _hora(b), "entrada": entrada,
                 "stop": round(stop, 2), "objetivo": round(objetivo, 2), "riesgo": round(entrada - stop, 2),
                 "motivo": "compra manual con tu stop y objetivo", "stop_label": "tu stop"}
    op = Operacion.objects.create(cuenta=ses.cuenta, modo=Operacion.PRACTICA, simbolo=ses.simbolo,
                                  archivo_datos=ses.archivo_datos, fecha_sesion=ses.fecha, sesion=ses,
                                  estrategia=senal["estrategia"])
    pipeline.analizar(op, senal=senal)
    op.save()
    ses.log(senal["hora"], f"Analizaste una compra a ${entrada:.2f} ({senal['nombre']}).")
    ses.save()
    return redirect("detalle", pk=op.pk)

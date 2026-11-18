import csv
import json
import random
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import barras, pipeline
from .models import Cuenta, Operacion


def cuenta_actual():
    return Cuenta.objects.order_by("pk").first() or Cuenta.objects.create()


def archivos_demo():
    """Archivos de 60 días de barras de 5 min: SIMBOLO-*.json(.gz) en datos_demo/."""
    out = []
    for p in sorted(settings.DATOS_DEMO_DIR.glob("*.json*")):
        if p.name.startswith("wall"):
            continue
        out.append({"simbolo": p.name.split("-")[0].upper(), "ruta": str(p), "nombre": p.name})
    return out


def fechas_practica(ruta):
    """La máquina del tiempo necesita 20 sesiones previas: solo se puede practicar desde la sesión 21."""
    return barras.sesiones(barras.cargar_chart(archivo=ruta))[20:]


def _estadisticas(cuenta):
    tomadas = [o for o in cuenta.operaciones.filter(estado=Operacion.CERRADA)]
    descartadas = [o for o in cuenta.operaciones.filter(estado=Operacion.DESCARTADA) if o.r_multiple is not None]

    def resumen(ops):
        if not ops:
            return None
        rs = [o.r_multiple for o in ops if o.r_multiple is not None]
        return {
            "n": len(ops),
            "ganadoras": sum(1 for o in ops if (o.pnl or 0) > 0),
            "pct": round(100 * sum(1 for o in ops if (o.pnl or 0) > 0) / len(ops)),
            "r_prom": round(sum(rs) / len(rs), 2) if rs else None,
            "pnl": round(sum(o.pnl or 0 for o in ops), 2),
        }

    return {"tomadas": resumen(tomadas), "descartadas": resumen(descartadas)}


def panel(request):
    cuenta = cuenta_actual()
    demo = archivos_demo()
    return render(request, "simulador/panel.html", {
        "cuenta": cuenta,
        "ops": cuenta.operaciones.all()[:30],
        "stats": _estadisticas(cuenta),
        "demo": demo,
        "fechas": {d["simbolo"]: fechas_practica(d["ruta"]) for d in demo},
    })


@require_POST
def nueva(request):
    cuenta = cuenta_actual()
    modo = request.POST.get("modo", Operacion.PRACTICA)
    op = Operacion(cuenta=cuenta, modo=modo)
    if modo == Operacion.PRACTICA:
        demo = {d["simbolo"]: d for d in archivos_demo()}
        sim = request.POST.get("simbolo_demo", "")
        if sim not in demo:
            messages.error(request, "Elige un símbolo con datos guardados.")
            return redirect("panel")
        op.simbolo, op.archivo_datos = sim, demo[sim]["ruta"]
        fechas = fechas_practica(op.archivo_datos)
        f = request.POST.get("fecha") or ""
        op.fecha_sesion = date.fromisoformat(f) if f else random.choice(fechas)
    else:
        op.simbolo = request.POST.get("simbolo", "").strip().upper()
        if not op.simbolo:
            messages.error(request, "Escribe un símbolo.")
            return redirect("panel")
    op.save()
    pipeline.analizar(op)
    op.save()
    return redirect("detalle", pk=op.pk)


def detalle(request, pk):
    op = get_object_or_404(Operacion, pk=pk)
    r = op.resultados
    return render(request, "simulador/detalle.html", {
        "op": op,
        "entry": r.get("entry"), "plan": r.get("exit"), "tm": r.get("timemachine"),
        "sizing": (r.get("budget") or {}).get("sizing"), "orden": ((r.get("budget") or {}).get("orders") or [None])[0],
        "riesgo": ((r.get("risk") or {}).get("results") or [None])[0], "news": r.get("news"),
    })


@require_POST
def decidir(request, pk):
    op = get_object_or_404(Operacion, pk=pk, estado=Operacion.PENDIENTE)
    accion = request.POST.get("accion")
    op.nota_decision = request.POST.get("nota", "").strip()
    op.decidida_en = timezone.now()
    cuenta = op.cuenta
    if accion == "tomar":
        if op.veredicto_riesgo != "PASS" and not request.POST.get("ignorar_riesgo"):
            messages.error(request, "trader-risk bloqueó esta orden. Marca la casilla si igual quieres simularla.")
            return redirect("detalle", pk=pk)
        if not op.acciones:
            messages.error(request, "El tamaño es 0 acciones: no hay nada que comprar.")
            return redirect("detalle", pk=pk)
        if op.costo > cuenta.efectivo:
            messages.error(request, "No alcanza el efectivo ficticio.")
            return redirect("detalle", pk=pk)
        cuenta.efectivo -= op.costo
        cuenta.save()
        op.estado = Operacion.ABIERTA
    else:
        op.estado = Operacion.DESCARTADA
    op.save()
    if op.modo == Operacion.PRACTICA:  # en práctica el resto del día ya existe: lo mostramos de inmediato
        return resolver(request, pk)
    return redirect("detalle", pk=pk)


@require_POST
def resolver(request, pk):
    op = get_object_or_404(Operacion, pk=pk)
    if op.resuelta:
        return redirect("detalle", pk=pk)
    try:
        pipeline.resolver(op)
    except Exception as e:  # sin internet, archivo roto...
        messages.error(request, f"No pude obtener las barras: {e}")
        return redirect("detalle", pk=pk)
    if op.resuelta and op.estado == Operacion.ABIERTA:
        op.cuenta.efectivo += op.salida_precio * op.acciones
        op.cuenta.save()
        op.estado = Operacion.CERRADA
    op.save()
    return redirect("detalle", pk=pk)


@require_POST
def reiniciar(request):
    cuenta = cuenta_actual()
    cuenta.operaciones.all().delete()
    cuenta.efectivo = cuenta.saldo_inicial
    cuenta.save()
    messages.success(request, "Cuenta reiniciada.")
    return redirect("panel")


def escaner(request):
    ctx = {"resultado": None}
    if request.method == "POST":
        modo = request.POST.get("modo")
        ws = settings.WORKSPACES_DIR / "escaner"
        ws.mkdir(parents=True, exist_ok=True)
        if modo == "demo":
            args = ["orb", "--offline", str(settings.DATOS_DEMO_DIR / "wall5m-2026-10-19.json.gz"),
                    "--now", "2026-10-19 " + (request.POST.get("hora") or "10:15"), "--min-price", "0", "--no-write"]
        else:
            simbolos = request.POST.get("simbolos", "").replace(" ", "")
            args = [modo] + (["--symbols", simbolos] if simbolos else [])
        datos, err = pipeline.correr("scanner", args, ws, timeout=900)
        ctx.update(resultado=datos, error=None if datos else err, modo=modo)
    return render(request, "simulador/escaner.html", ctx)


def exportar_csv(request):
    cuenta = cuenta_actual()
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="diario_trading.csv"'
    w = csv.writer(resp)
    campos = ["id", "modo", "simbolo", "fecha_sesion", "hora_decision", "estado", "entrada", "stop", "objetivo",
              "acciones", "max_perdida", "p_objetivo", "p_stop", "veredicto_riesgo", "veredicto_tm",
              "nota_decision", "salida_precio", "salida_motivo", "salida_hora", "pnl", "r_multiple"]
    w.writerow(campos)
    for o in cuenta.operaciones.order_by("pk"):
        w.writerow([getattr(o, "pk" if c == "id" else c) for c in campos])
    return resp


def exportar_ordenes(request):
    """Las órdenes de tus operaciones tomadas en el formato de Alpaca (place_stock_order).

    Es el puente a dinero real: se las das a /trader-broker en Claude, que muestra el ticket,
    te pide un "sí" explícito y usa paper trading por defecto. La app nunca envía nada.
    """
    ops = cuenta_actual().operaciones.filter(estado__in=[Operacion.ABIERTA, Operacion.CERRADA]).order_by("pk")
    ordenes = []
    for o in ops:
        orden = ((o.resultados.get("budget") or {}).get("orders") or [None])[0]
        if orden:
            ordenes.append({"operacion": o.pk, "fecha": str(o.fecha_sesion), "nota": o.nota_decision, **orden})
    return JsonResponse({"paper": True, "aviso": "Solo para revisar con /trader-broker. Nada se envió a un broker.",
                         "orders": ordenes}, json_dumps_params={"indent": 2, "ensure_ascii": False})


@require_POST
def reglas(request):
    cuenta = cuenta_actual()
    for campo in ("max_perdida_operacion", "max_perdida_diaria", "min_reward_risk", "objetivo_r"):
        if request.POST.get(campo):
            setattr(cuenta, campo, float(request.POST[campo]))
    if request.POST.get("max_operaciones_dia"):
        cuenta.max_operaciones_dia = int(request.POST["max_operaciones_dia"])
    if request.POST.get("regla_stop"):
        cuenta.regla_stop = request.POST["regla_stop"].strip()
    if request.POST.get("saldo_inicial"):
        nuevo = float(request.POST["saldo_inicial"])
        cuenta.efectivo += nuevo - cuenta.saldo_inicial
        cuenta.saldo_inicial = nuevo
    cuenta.save()
    messages.success(request, "Reglas guardadas. Se aplican a los próximos análisis.")
    return redirect("panel")

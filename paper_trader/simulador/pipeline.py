"""Corre las skills de day-trader-skill en orden, como lo harías con Claude:

entrada (trader-entry) -> salida (trader-exit) -> máquina del tiempo (trader-timemachine)
-> tamaño (trader-budget) -> riesgo (trader-risk) [+ noticias (trader-news) en vivo]

Cada análisis tiene su propia carpeta workspaces/op<ID>/trader/ con los JSON que escriben
las skills, para que puedas revisarlos (o dárselos a Claude) después.
"""
import json
import os
import subprocess
import sys
from datetime import date

from django.conf import settings

from . import barras

SCRIPTS = {
    "entry": "trader-entry/entry.py",
    "exit": "trader-exit/exit.py",
    "timemachine": "trader-timemachine/timemachine.py",
    "budget": "trader-budget/size.py",
    "risk": "trader-risk/check.py",
    "news": "trader-news/news.py",
    "scanner": "trader-scanner/scan.py",
}


class ErrorSkill(Exception):
    pass


def correr(skill, args, cwd, timeout=600):
    """Corre un script de una skill con --json y devuelve (datos, texto_error)."""
    script = settings.SKILLS_DIR / SCRIPTS[skill]
    if not script.exists():
        raise ErrorSkill(f"No encuentro {script}. ¿Están instaladas las skills en .claude/skills?")
    cmd = [sys.executable, str(script), *args, "--json"]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        return json.loads(p.stdout), p.stderr.strip()
    except json.JSONDecodeError:
        msg = (p.stderr or p.stdout).strip() or f"{skill} terminó con código {p.returncode}"
        return None, msg


def workspace(op):
    ws = settings.WORKSPACES_DIR / f"op{op.pk}"
    (ws / "trader").mkdir(parents=True, exist_ok=True)
    cuenta = op.cuenta
    (ws / "trader" / "config.json").write_text(json.dumps(cuenta.config_skills(), indent=2))
    (ws / "trader" / "portfolio.json").write_text(json.dumps({"cash": round(cuenta.efectivo, 2), "positions": []}))
    return ws


def _hora_del_gatillo(op, ws, offline):
    """En práctica buscamos el momento exacto del gatillo para decidir justo ahí (sin mirar el futuro)."""
    datos, err = correr("entry", ["check", op.simbolo, *offline, "--now", f"{op.fecha_sesion} 15:30"], ws)
    if not datos:
        raise ErrorSkill(err)
    if datos.get("status") != "triggered":
        return None, datos
    return datos["trigger"]["close_time"], datos


def analizar(op):
    """Llena op con los resultados de todas las skills. No toma ninguna decisión."""
    ws = workspace(op)
    op.resultados, op.errores = {}, []
    offline, now = [], []
    try:
        if op.modo == op.PRACTICA:
            offline = ["--offline", op.archivo_datos]
            hora, datos = _hora_del_gatillo(op, ws, offline)
            if hora is None:
                op.resultados["entry"] = datos
                op.estado = op.SIN_SENAL
                return op
            op.hora_decision = hora
            now = ["--now", f"{op.fecha_sesion} {hora}"]

        datos, err = correr("entry", ["check", op.simbolo, *offline, *now, "--write"], ws)
        if not datos:
            raise ErrorSkill(f"trader-entry: {err}")
        op.resultados["entry"] = datos
        if op.fecha_sesion is None:
            op.fecha_sesion = date.fromisoformat(datos["date"])
        if datos.get("status") != "triggered":
            op.estado = op.SIN_SENAL
            return op
        op.hora_decision = op.hora_decision or datos["trigger"]["close_time"]

        cuenta = op.cuenta
        datos, err = correr("exit", ["plan", *offline, *now, "--stop", cuenta.regla_stop,
                                     "--target", f"{cuenta.objetivo_r:g}R", "--write"], ws)
        if not datos:
            raise ErrorSkill(f"trader-exit: {err}")
        op.resultados["exit"] = datos
        op.entrada, op.stop, op.objetivo = datos["entry"], datos["stop"], datos["target"]
        op.flat_by = datos.get("flat_by") or "15:55"

        datos, err = correr("timemachine", ["run", *offline, *now, "--replays", "5000", "--write"], ws)
        if datos:
            mc = datos["mc"]
            datos["mc"] = {k: v for k, v in mc.items() if k != "bands"}  # las bandas pesan mucho
            op.resultados["timemachine"] = datos
            op.p_objetivo, op.p_stop = mc["p_target"], mc["p_stop"]
            op.veredicto_tm = (datos.get("verdict") or "")[:200]
        else:
            op.errores.append(f"Máquina del tiempo: {err}")

        datos, err = correr("budget", [*now, "--write"], ws)
        if not datos:
            raise ErrorSkill(f"trader-budget: {err}")
        op.resultados["budget"] = datos
        s = datos["sizing"]
        if s.get("refusal"):
            op.errores.append(f"Tamaño: {s['refusal']}")
        op.acciones, op.max_perdida = s.get("qty"), s.get("max_loss")

        datos, err = correr("risk", [*now, "--no-write"], ws)
        if not datos:
            raise ErrorSkill(f"trader-risk: {err}")
        op.resultados["risk"] = datos
        r = (datos.get("results") or [{}])[0]
        op.veredicto_riesgo = r.get("verdict", "")
        extra = limite_diario(op)
        if extra:
            op.veredicto_riesgo = "BLOCK"
            r.setdefault("reasons", []).append(extra)

        if op.modo == op.VIVO:
            args = ["--tickers", op.simbolo, "--hours", "24", "--dry-run"]
            if not os.environ.get("SEC_USER_AGENT"):
                args.append("--no-sec")
            datos, err = correr("news", args, ws)
            if datos:
                op.resultados["news"] = datos
            else:
                op.errores.append(f"Noticias: {err}")
        op.estado = op.PENDIENTE
    except (ErrorSkill, subprocess.TimeoutExpired, KeyError) as e:
        op.estado = op.ERROR
        op.errores.append(str(e))
    return op


def limite_diario(op):
    """trader-risk lleva la cuenta diaria en su propio log; aquí la llevamos con la base de datos."""
    hoy = op.cuenta.operaciones.filter(fecha_sesion=op.fecha_sesion, estado__in=[op.ABIERTA, op.CERRADA]).exclude(pk=op.pk)
    if hoy.count() >= op.cuenta.max_operaciones_dia:
        return f"ya tomaste {hoy.count()} operaciones ese día (máximo {op.cuenta.max_operaciones_dia})"
    perdido = -sum(min(o.pnl or 0, 0) for o in hoy) + sum(o.max_perdida or 0 for o in hoy if o.estado == op.ABIERTA)
    if perdido + (op.max_perdida or 0) > op.cuenta.max_perdida_diaria:
        return (f"pérdida del día en riesgo ${perdido + (op.max_perdida or 0):,.2f} "
                f"pasaría el límite diario ${op.cuenta.max_perdida_diaria:,.2f}")
    return None


def resolver(op):
    """Calcula cómo terminó (o cómo habría terminado) la operación según las barras reales."""
    if op.entrada is None or not op.hora_decision:
        return op
    if op.modo == op.PRACTICA:
        chart = barras.cargar_chart(archivo=op.archivo_datos)
    else:
        chart = barras.cargar_chart(simbolo=op.simbolo)
    r = barras.resolver(chart, op.fecha_sesion, op.hora_decision, op.entrada, op.stop, op.objetivo, op.flat_by)
    if r is None:
        op.errores.append("Todavía no hay barras después de la entrada.")
        return op
    if not r["terminado"]:
        op.salida_motivo = f"sigue abierta (último {r['precio']} a las {r['hora']})"
        return op
    qty = op.acciones or 0
    op.salida_precio, op.salida_motivo, op.salida_hora = r["precio"], r["motivo"], r["hora"]
    op.pnl = round((r["precio"] - op.entrada) * qty, 2)
    riesgo = op.entrada - op.stop
    op.r_multiple = round((r["precio"] - op.entrada) / riesgo, 2) if riesgo > 0 else None
    return op

"""Descarga 60 días de barras de 5 minutos de Yahoo para practicar sin internet.

    python manage.py descargar_datos TSLA NVDA AMD

Guarda datos_demo/SIMBOLO-60d5m.json.gz (el mismo formato que leen las skills con --offline).
"""
import gzip
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from simulador import barras


class Command(BaseCommand):
    help = "Descarga 60 días de barras de 5 minutos de Yahoo para el modo práctica."

    def add_arguments(self, parser):
        parser.add_argument("simbolos", nargs="+")

    def handle(self, *args, **opts):
        settings.DATOS_DEMO_DIR.mkdir(exist_ok=True)
        for i, sim in enumerate(s.upper() for s in opts["simbolos"]):
            if i:
                time.sleep(1)  # pausa amable con Yahoo
            try:
                chart = barras.cargar_chart(simbolo=sim, rango="60d")
            except Exception as e:
                raise CommandError(f"{sim}: no pude descargar ({e})")
            n = len(barras.sesiones(chart))
            destino = settings.DATOS_DEMO_DIR / f"{sim}-60d5m.json.gz"
            with gzip.open(destino, "wt") as f:
                json.dump(chart, f)
            self.stdout.write(f"{sim}: {n} sesiones completas -> {destino.name} "
                              f"({max(n - 20, 0)} días para practicar)")

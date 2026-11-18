from django.contrib import admin

from .models import Cuenta, Operacion


@admin.register(Cuenta)
class CuentaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "efectivo", "max_perdida_operacion", "max_perdida_diaria", "max_operaciones_dia")


@admin.register(Operacion)
class OperacionAdmin(admin.ModelAdmin):
    list_display = ("pk", "simbolo", "fecha_sesion", "modo", "estado", "acciones", "pnl", "r_multiple")
    list_filter = ("estado", "modo")

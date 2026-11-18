from django.db import models


class Cuenta(models.Model):
    """Una cuenta de dinero ficticio con tus reglas de riesgo."""

    nombre = models.CharField(max_length=60, default="Práctica")
    saldo_inicial = models.FloatField(default=10000)
    efectivo = models.FloatField(default=10000)
    max_perdida_operacion = models.FloatField("pérdida máx. por operación (USD)", default=50)
    max_perdida_diaria = models.FloatField("pérdida máx. diaria (USD)", default=150)
    max_operaciones_dia = models.IntegerField("operaciones máx. por día", default=3)
    min_reward_risk = models.FloatField("reward:risk mínimo", default=1.0)
    objetivo_r = models.FloatField("objetivo en R", default=2.0)
    regla_stop = models.CharField(
        "regla del stop", max_length=20, default="or-mid",
        help_text="or-mid (mitad del rango), or-low (mínimo del rango), 1% , atr:1.5 ...",
    )
    creada = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    def config_skills(self):
        """El trader/config.json que leen trader-budget y trader-risk."""
        return {
            "budget": round(self.efectivo, 2),
            "max_loss_per_trade_usd": self.max_perdida_operacion,
            "max_daily_loss_usd": self.max_perdida_diaria,
            "max_trades_per_day": self.max_operaciones_dia,
            "min_reward_risk": self.min_reward_risk,
            "paper": True,
        }

    @property
    def abiertas(self):
        return self.operaciones.filter(estado=Operacion.ABIERTA)

    @property
    def capital(self):
        """Efectivo + lo invertido en posiciones abiertas (a precio de entrada)."""
        return self.efectivo + sum(o.costo for o in self.abiertas)


class SesionReloj(models.Model):
    """Una sesión de práctica que avanza barra por barra (modo reloj)."""

    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="sesiones")
    simbolo = models.CharField(max_length=10)
    archivo_datos = models.CharField(max_length=300)
    fecha = models.DateField()
    indice = models.IntegerField(default=3, help_text="cuántas barras de 5 min ya se ven")
    estrategia = models.CharField(max_length=12, default="orb")
    terminada = models.BooleanField(default=False)
    eventos = models.JSONField(default=list)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]

    def __str__(self):
        return f"Reloj {self.simbolo} {self.fecha}"

    def log(self, hora, texto):
        self.eventos.append({"hora": hora, "texto": texto})


class Operacion(models.Model):
    PRACTICA, VIVO = "practica", "vivo"
    MODOS = [(PRACTICA, "Práctica (datos guardados)"), (VIVO, "En vivo (Yahoo, internet)")]

    PENDIENTE, SIN_SENAL, ERROR = "pendiente", "sin_senal", "error"
    ABIERTA, CERRADA, DESCARTADA = "abierta", "cerrada", "descartada"
    ESTADOS = [
        (PENDIENTE, "Esperando tu decisión"),
        (SIN_SENAL, "Sin señal de entrada"),
        (ERROR, "Error en el análisis"),
        (ABIERTA, "Tomada, abierta"),
        (CERRADA, "Tomada, cerrada"),
        (DESCARTADA, "Descartada"),
    ]

    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE, related_name="operaciones")
    modo = models.CharField(max_length=10, choices=MODOS, default=PRACTICA)
    simbolo = models.CharField(max_length=10)
    archivo_datos = models.CharField(max_length=300, blank=True)
    estrategia = models.CharField(max_length=12, default="orb")
    sesion = models.ForeignKey(SesionReloj, null=True, blank=True, on_delete=models.CASCADE, related_name="operaciones")
    fecha_sesion = models.DateField(null=True, blank=True)
    hora_decision = models.CharField(max_length=5, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default=PENDIENTE)

    # El plan (de trader-entry / trader-exit / trader-budget)
    entrada = models.FloatField(null=True, blank=True)
    stop = models.FloatField(null=True, blank=True)
    objetivo = models.FloatField(null=True, blank=True)
    acciones = models.IntegerField(null=True, blank=True)
    max_perdida = models.FloatField(null=True, blank=True)
    flat_by = models.CharField(max_length=5, default="15:55")

    # Lo que dijeron las skills
    p_objetivo = models.FloatField(null=True, blank=True)
    p_stop = models.FloatField(null=True, blank=True)
    veredicto_tm = models.CharField(max_length=200, blank=True)
    veredicto_riesgo = models.CharField(max_length=10, blank=True)
    resultados = models.JSONField(default=dict)
    errores = models.JSONField(default=list)

    # Tu decisión
    nota_decision = models.TextField(blank=True)
    decidida_en = models.DateTimeField(null=True, blank=True)

    # El resultado (real si la tomaste, hipotético si la descartaste)
    salida_precio = models.FloatField(null=True, blank=True)
    salida_motivo = models.CharField(max_length=40, blank=True)
    salida_hora = models.CharField(max_length=5, blank=True)
    pnl = models.FloatField(null=True, blank=True)
    r_multiple = models.FloatField(null=True, blank=True)

    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]

    def __str__(self):
        return f"{self.simbolo} {self.fecha_sesion or ''} ({self.get_estado_display()})"

    @property
    def costo(self):
        return (self.entrada or 0) * (self.acciones or 0)

    @property
    def tomada(self):
        return self.estado in (self.ABIERTA, self.CERRADA)

    @property
    def resuelta(self):
        return self.salida_precio is not None

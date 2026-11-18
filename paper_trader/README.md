# Simulador de trading (dinero ficticio)

Una app Django local que usa las 11 skills de [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(instaladas en `../.claude/skills/`) para practicar day trading con dinero falso y llevar un diario de tus decisiones.

> Educación, no asesoría financiera. La mayoría de la gente que hace day trading pierde dinero.
> La app **nunca** envía órdenes a un broker.

## Instalar y correr

```bash
cd paper_trader
python3 -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Abre http://127.0.0.1:8000. No hace falta ninguna API key.

## Cómo se usa

1. **Práctica (sin internet).** Elige un día pasado (o al azar). La app avanza el reloj hasta el momento exacto
   en que se activa la ruptura del rango de apertura y corre las skills **solo con los datos hasta ese momento**:
   - `trader-entry`: ¿rompió el rango de apertura? ¿a qué hora y precio?
   - `trader-exit`: stop (mitad del rango) y objetivo (2R)
   - `trader-timemachine`: 5,000 sesiones simuladas + la misma regla en los días anteriores
   - `trader-budget`: cuántas acciones según tu pérdida máxima por operación
   - `trader-risk`: PASS o BLOCK contra tus reglas (más el límite diario que lleva la app)
2. **Decides**: tomar o descartar, y escribes **por qué**.
3. La app camina las barras reales del resto del día y te muestra el resultado: stop, objetivo o cierre a las 15:55.
   Si la descartaste, igual te muestra qué *habría* pasado.
4. El panel compara tus operaciones tomadas contra las descartadas (P&L, % ganadoras, R promedio).
   Así ves si tu criterio agrega valor sobre seguir la regla a ciegas.

**En vivo** (con internet, mercado abierto después de las 9:50 ET): escribes un símbolo y corre lo mismo con datos de
Yahoo, más `trader-news`. El botón *Actualizar* revisa más tarde si tocó el stop o el objetivo. El **Escáner**
corre `trader-scanner` (demo guardado del 19 oct 2026, o en vivo).

### Más datos para practicar

Viene TSLA (60 días). Para agregar otras acciones (necesita internet):

```bash
python manage.py descargar_datos NVDA AMD AAPL
```

Cada archivo de 60 días da unos 39 días de práctica (la máquina del tiempo necesita 20 sesiones previas).

## De la simulación a dinero real

- **Diario CSV** (`/exportar/diario.csv`): todas tus decisiones con tu razón y el resultado. Pásaselo a Claude:
  *"revisa mi diario: ¿en qué casos mis descartes fueron mejores que la regla?"*
- **Órdenes (Alpaca JSON)** (`/exportar/ordenes.json`): las órdenes bracket de lo que tomaste, en el formato de
  `place_stock_order` de Alpaca. Es el puente con `/trader-broker` en Claude, que muestra el ticket, te pide un
  "sí" explícito y usa **paper trading** por defecto. Pasar a dinero real es tu decisión, en tu configuración.
- Sugerencia: no pases a real hasta tener muchas operaciones (50 o más) con R promedio positivo en práctica *y* en paper en vivo.

## Cómo funciona por dentro

- `simulador/pipeline.py` corre los scripts de las skills con `--json` (y `--offline`/`--now` en práctica).
  Cada análisis guarda sus archivos en `workspaces/op<ID>/trader/`.
- `simulador/barras.py` lee las barras de 5 minutos de Yahoo y resuelve la salida. Si una barra toca el stop y
  el objetivo a la vez, asume el stop (conservador). Un gap por debajo del stop sale a la apertura.
- Las reglas (pérdida máxima, límite diario, R objetivo, regla del stop) se editan en el panel
  (*Reglas de riesgo y cuenta*) y se pasan a las skills como `trader/config.json`.
- Variables: `TRADER_SKILLS_DIR` (otra carpeta de skills), `SEC_USER_AGENT` ("Tu Nombre tu@correo") para
  las noticias de la SEC.

## Límites

- Solo largos (compras), solo la ruptura del rango de apertura (lo que soportan `trader-entry` y `trader-exit`).
- Los textos que generan las skills están en inglés.
- La simulación no tiene comisiones ni slippage; en real los stops pueden llenarse peor.
- Los datos de Yahoo son gratis, no oficiales y con retraso.

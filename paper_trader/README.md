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

### ⏱️ Modo reloj (recomendado)

Revives un día pasado **barra por barra**, como si estuvieras frente a la pantalla:

- Empieza a las 9:45 con las 3 barras del rango de apertura. Avanzas 5 min (tecla **→**), 15 min, 1 hora,
  **hasta la próxima señal** (tecla **S**) o hasta el cierre.
- El gráfico muestra velas de 5 minutos, el VWAP, el rango de apertura, el máximo de 20 días y tu entrada/stop/objetivo.
- Cuando una estrategia da señal, aparece con su stop y objetivo. Puedes **analizarla** o comprar con **tu propio plan**
  (stop y objetivo que tú eliges). «Analizar» corre la máquina del tiempo, el tamaño y el riesgo con los datos hasta ese
  minuto; después tomas o descartas.
- Con la posición abierta ves la ganancia/pérdida latente en dólares y en R. Cada barra nueva revisa el stop y el
  objetivo; puedes **vender a mano**; a las 15:55 se cierra sola.
- Al terminar el día, las compras que descartaste se resuelven igual (hipotéticamente) para comparar.

### Estrategias

| clave | estrategia | señal (solo compras, una por día) | stop |
| --- | --- | --- | --- |
| `orb` | Ruptura del rango de apertura | primer cierre sobre el máximo de los primeros 15 min (usa las skills `trader-entry` y `trader-exit`) | mitad del rango |
| `nivel20` | Ruptura del máximo de 20 días | primer cierre sobre el máximo de las 20 sesiones anteriores | mínimo de las últimas 3 barras |
| `vwap` | Recupera el VWAP | cierra sobre el VWAP después de 3 barras debajo (desde las 10:00) | mínimo de las últimas 4 barras |
| `bandera` | Bandera alcista | subida de 1.5 %+, consolidación de 3–8 barras que retrocede menos de la mitad, cierre sobre la punta | mínimo de la bandera |
| `rebote` | Rebote de sobreventa | día que cayó 1.5 %+, RSI(14) de 5 min cruza 30 hacia arriba con vela verde | mínimo del día |

Objetivo: tu R (2R por defecto). No hay entradas antes de las 9:45 ni después de las 15:30, y se descartan stops a
menos de 0.2 % o a más de 4 % de la entrada. Cada estrategia muestra su **historia**: la misma regla en las sesiones
anteriores al día que practicas (nunca el mismo día). Las reglas están en `simulador/estrategias.py`: agregar una
es escribir una función y sumarla al diccionario `ESTRATEGIAS`.

### 🎯 Práctica rápida

1. Elige una estrategia y un día pasado (o al azar). La app avanza el reloj hasta el momento exacto
   de la primera señal y corre las skills **solo con los datos hasta ese momento**:
   - la entrada: `trader-entry` para `orb`, o la regla de la estrategia
   - el plan: `trader-exit` para `orb`, o el stop de la estrategia y tu R (escrito en `trader/plan.json` igual que `trader-exit`)
   - `trader-timemachine`: 5,000 sesiones simuladas + la misma regla en los días anteriores
   - `trader-budget`: cuántas acciones según tu pérdida máxima por operación
   - `trader-risk`: PASS o BLOCK contra tus reglas (más el límite diario que lleva la app)
2. **Decides**: tomar o descartar, y escribes **por qué**.
3. La app camina las barras reales del resto del día y te muestra el resultado: stop, objetivo o cierre a las 15:55.
   Si la descartaste, igual te muestra qué *habría* pasado.
4. El panel compara tus operaciones tomadas contra las descartadas (P&L, % ganadoras, R promedio).
   Así ves si tu criterio agrega valor sobre seguir la regla a ciegas.

### 📡 En vivo

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

- Solo compras (largos), en barras de 5 minutos.
- La sección «Historia» de `trader-timemachine` solo conoce la ruptura del rango de apertura; para las otras
  estrategias la app muestra su propio backtest.
- El modo reloj usa los datos guardados (práctica); en vivo se usa el análisis por símbolo.
- Los textos que generan las skills están en inglés.
- La simulación no tiene comisiones ni slippage; en real los stops pueden llenarse peor.
- Los datos de Yahoo son gratis, no oficiales y con retraso.

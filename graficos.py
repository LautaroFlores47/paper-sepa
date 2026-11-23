#!/usr/bin/env python3
"""
graficos.py — figuras del paper (T35) y análisis de H5.

Lee los CSV de la corrida final (carpeta datos/) y genera en salida/:
  fig1_espacio      espacio en disco de A y B-WO por escala (compacto)
  fig2_carga        tiempo de carga diaria por día, escala 90
  fig3_consultas    razón de tiempos B-WO / A con IC 95%, configuración por defecto y todo en memoria
  fig4_cadenas      H5: frecuencia de cambios contra razón de filas A / B, por cadena
Cada figura en PNG (300 dpi, para Word) y PDF (vectorial).
También escribe salida/h5.md con la tabla de H5.
"""
import argparse
import csv
import os
import random
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--resultados", default="resultados", help="carpeta con tamanos.csv, carga_eN.csv, consultas*.csv")
ap.add_argument("--t13", default=r"C:\sepa-crudos\t13", help="carpeta con cambios_por_comercio.csv")
ap.add_argument("--salida", default="figuras", help="dónde guardar las figuras")
args = ap.parse_args()
D, T13, S = args.resultados, args.t13, args.salida
os.makedirs(S, exist_ok=True)
RESUMEN = []

# Paleta validada (orden categórico fijo): A azul, B-WO naranja, B-GiST aqua
COL = {"a": "#2a78d6", "b_wo": "#eb6834", "b_gist": "#1baf7a"}
NOMBRE = {"a": "A (una fila por día)", "b_wo": "B-WO (tramos + WITHOUT OVERLAPS)", "b_gist": "B-GiST (tramos, sin restricción)"}
TINTA, TINTA2, GRILLA = "#0b0b0b", "#52514e", "#e4e3de"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": TINTA2, "axes.labelcolor": TINTA,
    "xtick.color": TINTA2, "ytick.color": TINTA2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRILLA, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "legend.frameon": False, "savefig.facecolor": "white", "figure.facecolor": "white",
})
coma = FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))


def leer(nombre, carpeta=None):
    with open(os.path.join(carpeta or D, nombre), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def guardar(fig, nombre):
    fig.savefig(os.path.join(S, nombre + ".png"), dpi=300, bbox_inches="tight")
    fig.savefig(os.path.join(S, nombre + ".pdf"), bbox_inches="tight")
    plt.close(fig)


def bootstrap(valores, semilla=20261122, n=10_000):
    rnd = random.Random(semilla)
    meds = sorted(statistics.median(rnd.choices(valores, k=len(valores))) for _ in range(n))
    return meds[int(0.025 * n)], meds[int(0.975 * n) - 1]


def num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


# ------------------------------------------------------------------ Figura 1: espacio
tam = {}
for r in leer("tamanos.csv"):
    tam[(r["momento"], int(r["escala"]), r["modelo"])] = r   # la última corrida pisa a la anterior
fig, ax = plt.subplots(figsize=(6.3, 3.0))
escalas = [30, 60, 90]
ancho = 0.36
for i, m in enumerate(["a", "b_wo"]):
    vals = [int(tam[("compacto", e, m)]["bytes_total"]) / 1e6 for e in escalas]
    xs = [k + (i - 0.5) * (ancho + 0.03) for k in range(3)]
    ax.bar(xs, vals, width=ancho, color=COL[m], label=NOMBRE[m], edgecolor="white", linewidth=1)
    for x, v in zip(xs, vals):
        ax.text(x, v + 8, f"{num(v)} MB", ha="center", va="bottom", fontsize=8, color=TINTA)
for k, e in enumerate(escalas):
    ra = int(tam[("compacto", e, "a")]["bytes_total"]) / int(tam[("compacto", e, "b_wo")]["bytes_total"])
    fa = int(tam[("compacto", e, "a")]["filas"]) / int(tam[("compacto", e, "b_wo")]["filas"])
    RESUMEN.append(f"Espacio {e} días: A/B-WO = {num(ra, 2)} (filas {num(fa, 2)})")
    ax.text(k, -95, f"A ocupa {num(ra)}× más\n({num(fa)}× más filas)", ha="center", va="top", fontsize=8, color=TINTA2)
ax.set_xticks(range(3), [f"{e} días" for e in escalas])
ax.set_ylabel("Tamaño total compacto (MB)")
ax.set_ylim(0, 620)
ax.yaxis.set_major_formatter(coma)
ax.tick_params(axis="x", length=0, pad=4)
ax.legend(loc="upper left", fontsize=8)
ax.set_title("B-WO ocupa entre 14 y 20 veces menos que A", loc="left", fontsize=10, color=TINTA)
fig.subplots_adjust(bottom=0.28)
guardar(fig, "fig1_espacio")

# ------------------------------------------------------------------ Figura 2: carga diaria
c90 = leer("carga_e90.csv")
fig, ax = plt.subplots(figsize=(6.3, 3.0))
estilos = {"a": ("-", "o"), "b_gist": ("--", "s"), "b_wo": ("-", "^")}
for m in ["a", "b_gist", "b_wo"]:
    pts = sorted((int(r["dia_n"]), float(r["segundos"])) for r in c90 if r["modelo"] == m)
    ax.plot([p[0] for p in pts], [p[1] for p in pts], ls=estilos[m][0], color=COL[m], lw=1.6,
            marker=estilos[m][1], markersize=2.6, markevery=6, label=NOMBRE[m])
ax.set_xlabel("Día de carga (escala 90: 01/02 a 01/05/2025)")
ax.set_ylabel("Segundos por día")
ax.set_xlim(0, 91)
ax.yaxis.set_major_formatter(coma)
ax.annotate("día 1: carga inicial", xy=(1, 1.81), xytext=(8, 3.3), fontsize=7.5, color=TINTA2,
            arrowprops=dict(arrowstyle="-", color=TINTA2, lw=0.7))
ax.annotate("01/05 (feriado): se cierran 35 mil tramos", xy=(90, 1.71), xytext=(28, 3.95), fontsize=7.5,
            color=TINTA2, arrowprops=dict(arrowstyle="-", color=TINTA2, lw=0.7))
ax.legend(loc="upper left", fontsize=8, ncol=1)
ax.set_title("La carga de A crece con el historial; la de B se mantiene", loc="left", fontsize=10, color=TINTA)
guardar(fig, "fig2_carga")

# ------------------------------------------------------------------ Figura 3: consultas
def razones(nombre):
    t = {}
    for r in leer(nombre):
        t.setdefault((int(r["escala"]), r["consulta"], int(r["caso"])), {})[r["modelo"]] = float(r["segundos"])
    out = {}
    for (e, q, _), v in t.items():
        out.setdefault((e, q), []).append(v["b_wo"] / v["a"])
    res = {k: (statistics.median(v), *bootstrap(v)) for k, v in out.items()}
    for (e, q), (m, lo, hi) in sorted(res.items(), key=lambda x: (x[0][1], x[0][0])):
        RESUMEN.append(f"{nombre} {q} {e} días: B-WO/A = {num(m, 3)} [IC {num(lo, 3)} – {num(hi, 3)}]")
    return res


r128, r1gb = razones("consultas.csv"), razones("consultas_1gb.csv")
etq = {"Q1": "Q1 precio puntual", "Q2": "Q2 sucursal en un día", "Q3": "Q3 historia de un producto",
       "Q4": "Q4 resumen del período"}
fig, axs = plt.subplots(1, 2, figsize=(6.6, 3.4), sharey=True)
filas = [(q, e) for q in ["Q1", "Q2", "Q3", "Q4"] for e in (30, 60, 90)]
ys = list(range(len(filas)))[::-1]
for ax, datos, titulo in ((axs[0], r128, "Configuración por defecto (128 MB)"),
                          (axs[1], r1gb, "Todo en memoria (1 GB + precarga)")):
    ax.axvspan(0.9, 1.1, color=GRILLA, alpha=0.7, lw=0)
    ax.axvline(1, color=TINTA2, lw=0.8)
    for y, (q, e) in zip(ys, filas):
        med, lo, hi = datos[(e, q)]
        dif = not (lo <= 1 <= hi) and (med < 0.9 or med > 1.1)
        color = COL["b_wo"] if dif and med < 1 else (COL["a"] if dif else TINTA2)
        ax.plot([lo, hi], [y, y], color=color, lw=1.6)
        ax.plot(med, y, "o", color=color, markersize=4.5, markeredgecolor="white", markeredgewidth=0.8)
    ax.set_xscale("log")
    ax.set_xlim(0.03, 2.2)
    ax.set_xticks([0.05, 0.1, 0.25, 0.5, 1, 2])
    ax.xaxis.set_major_formatter(coma)
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda *_: ""))
    ax.set_title(titulo, fontsize=8.5, color=TINTA, loc="left")
    ax.grid(axis="y", visible=False)
    for k in range(1, 4):
        ax.axhline(ys[3 * k] + 0.5, color=GRILLA, lw=0.8)
axs[0].set_yticks(ys, [f"{etq[q] if e == 30 else ''}  {e} d" for q, e in filas], fontsize=7.5)
axs[0].tick_params(axis="y", length=0)
fig.supxlabel("Tiempo B-WO / tiempo A, mediana e IC 95% (escala log). Naranja: B-WO más rápida; "
              "gris: sin diferencia detectable\n(banda gris: ±10%)", fontsize=7.5, color=TINTA2, y=0.0)
fig.suptitle("B-WO gana siempre en Q2 y Q4; en Q1 y Q3 la ventaja depende de la memoria",
             fontsize=10, color=TINTA, x=0.02, ha="left")
fig.tight_layout(rect=(0, 0.05, 1, 0.99), h_pad=0.2)
guardar(fig, "fig3_consultas")

# ------------------------------------------------------------------ H5 + Figura 4
# Filas por comercio en e90.a y e90.b_wo: salen de la consulta SQL de H5 (ver el doc del proyecto)
filas_db = {"10": (2246470, 99845), "12": (599405, 22335), "13": (591631, 13231),
            "3": (95874, 4203), "9": (2923199, 98022)}   # consulta en PostgreSQL, escala 90
cad = []
for r in leer("cambios_por_comercio.csv", T13):
    fa, fb = filas_db[r["id_comercio"]]
    cad.append({"id": r["id_comercio"], "nombre": r["nombre"], "p": float(r["p"]), "fa": fa, "fb": fb,
                "razon": fa / fb, "teorica": 90 / (1 + float(r["p"]) * 89)})
cad.sort(key=lambda c: -c["p"])
for letra, c in zip("ABCDE", cad):
    c["letra"] = f"Cadena {letra}"


def rangos(v):
    orden = sorted(range(len(v)), key=lambda i: v[i])
    rk = [0] * len(v)
    for pos, i in enumerate(orden):
        rk[i] = pos + 1
    return rk


def spearman(x, y):
    rx, ry = rangos(x), rangos(y)
    n = len(x)
    return 1 - 6 * sum((a - b) ** 2 for a, b in zip(rx, ry)) / (n * (n * n - 1))


rho = spearman([c["p"] for c in cad], [c["razon"] for c in cad])
rho4 = spearman([c["p"] for c in cad if c["id"] != "3"], [c["razon"] for c in cad if c["id"] != "3"])
with open(os.path.join(S, "h5.md"), "w", encoding="utf-8") as f:
    f.write("| Cadena | Comercio | p diario | Filas A | Filas B | A / B medido | A / B según la fórmula |\n")
    f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
    for c in cad:
        miles = lambda n: f"{n:,}".replace(",", ".")   # noqa: E731
        f.write(f"| {c['letra']} | {c['id']} · {c['nombre']} | {num(100 * c['p'], 2)}% | {miles(c['fa'])} | "
                f"{miles(c['fb'])} | {num(c['razon'])} | {num(c['teorica'])} |\n")
    f.write(f"\nCorrelación de Spearman entre p y A/B: {num(rho, 2)} (5 cadenas); sin la cadena del comercio 3: {num(rho4, 2)}.\n")

fig, ax = plt.subplots(figsize=(5.2, 3.2))
xs = [i / 1000 for i in range(5, 22)]
ax.plot([100 * x for x in xs], [90 / (1 + x * 89) for x in xs], color=TINTA2, lw=1, ls="--")
ax.text(1.35, 90 / (1 + 0.0135 * 89) + 2.2, "fórmula sin ausencias\nN / (1 + p·(N − 1)), N = 90", fontsize=7.5,
        color=TINTA2)
for c in cad:
    ax.plot(100 * c["p"], c["razon"], "o", color=COL["b_wo"], markersize=7, markeredgecolor="white", markeredgewidth=1)
    dx = -0.07 if c["id"] in ("3",) else 0.05
    ax.text(100 * c["p"] + dx, c["razon"] + (1.6 if c["id"] != "3" else -3.4), c["letra"], fontsize=8,
            ha="right" if dx < 0 else "left", color=TINTA)
ax.set_xlabel("Precios que cambian por día, p (%)")
ax.set_ylabel("Filas A / filas B (90 días)")
ax.xaxis.set_major_formatter(coma)
ax.set_ylim(15, 60)
ax.set_title("Más cambios, menos ahorro; los días sin dato\nbajan el ahorro debajo de la fórmula", loc="left",
             fontsize=10, color=TINTA)
guardar(fig, "fig4_cadenas")

print("\n".join(RESUMEN))
print()
print(open(os.path.join(S, "h5.md"), encoding="utf-8").read())
print("Listo:", sorted(os.listdir(S)))

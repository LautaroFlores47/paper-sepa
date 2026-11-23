#!/usr/bin/env python3
"""
analizar_carga.py — Espacio (H1b) y costo de carga diaria (H3a y H3b), con el método de la sección 3.

Lee resultados/tamanos.csv y resultados/carga_e30.csv, carga_e60.csv, carga_e90.csv.

Espacio: razón A / B en filas y en bytes, en las tres escalas, "tras_vacuum" (uso real) y "compacto".

Carga, con mediciones emparejadas por día:
  H3a: B-WO contra A            (razón = tiempo B-WO / tiempo A del mismo día)
  H3b: B-WO contra B-GiST       (razón = tiempo B-WO / tiempo B-GiST del mismo día)
  Para cada comparación: mediana de las razones e intervalo de confianza del 95% por bootstrap
  (10.000 remuestreos, semilla fija). Hay diferencia si el intervalo no incluye 1 y además la
  mediana de la razón está fuera de 0,9–1,1.
  Análisis principal (el que fija el protocolo): escala 30, sus 30 días.
  Análisis de sensibilidad: escala 90, días 2 a 90 (sin el día 1, que es la carga inicial).

Uso:  python analizar_carga.py
Escribe resultados/analisis_carga.md
"""
import argparse
import csv
import os
import random
import statistics

SEMILLA = 20261122
REMUESTREOS = 10_000


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def bootstrap_mediana(valores, semilla=SEMILLA, n=REMUESTREOS):
    rnd = random.Random(semilla)
    k = len(valores)
    meds = sorted(statistics.median(rnd.choices(valores, k=k)) for _ in range(n))
    return meds[int(0.025 * n)], meds[int(0.975 * n) - 1]


def comparar(filas, escala, modelo, referencia, dias=None):
    t = {}
    for r in filas:
        if int(r["escala"]) == escala and r["modelo"] in (modelo, referencia):
            dia = int(r["dia_n"])
            if dias is None or dia in dias:
                t.setdefault(dia, {})[r["modelo"]] = float(r["segundos"])
    razones = [v[modelo] / v[referencia] for v in t.values() if modelo in v and referencia in v and v[referencia] > 0]
    med = statistics.median(razones)
    lo, hi = bootstrap_mediana(razones)
    estadistica = not (lo <= 1 <= hi)
    practica = med < 0.9 or med > 1.1
    if estadistica and practica:
        veredicto = f"{modelo} es {'MÁS LENTO' if med > 1 else 'MÁS RÁPIDO'} que {referencia}"
    else:
        veredicto = "sin diferencia detectable"
    return {"pares": len(razones), "mediana_razon": med, "ic95": (lo, hi), "veredicto": veredicto}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resultados", default="resultados")
    args = ap.parse_args()
    R = args.resultados

    # ---------------------------------------------------------------- espacio
    tam = leer(os.path.join(R, "tamanos.csv"))
    ultimo = {}
    for r in tam:   # si se corrió más de una vez, vale la última medición
        ultimo[(r["momento"], int(r["escala"]), r["modelo"])] = r
    lineas = ["# Espacio y carga diaria", "", "## Espacio (H1b)", "",
              "| Escala | Momento | Filas A | Filas B | A/B filas | MB A | MB B-WO | MB B-GiST | A/B-WO bytes | ¿H1b se cumple? |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for esc in (30, 60, 90):
        for mom in ("tras_vacuum", "compacto"):
            a, bw, bg = (ultimo.get((mom, esc, m)) for m in ("a", "b_wo", "b_gist"))
            if not (a and bw):
                continue
            fa, fb = int(a["filas"]), int(bw["filas"])
            ba, bb = int(a["bytes_total"]), int(bw["bytes_total"])
            rf, rb = fa / fb, ba / bb
            cumple = "sí" if (bb < ba and rb < rf) else "NO"
            lineas.append(f"| {esc} | {mom} | {fa:,} | {fb:,} | {rf:.1f} | {ba / 1e6:.1f} | {bb / 1e6:.1f} | "
                          f"{int(bg['bytes_total']) / 1e6 if bg else float('nan'):.1f} | {rb:.1f} | {cumple} |")

    # ---------------------------------------------------------------- carga
    filas = []
    for esc in (30, 60, 90):
        ruta = os.path.join(R, f"carga_e{esc}.csv")
        if os.path.exists(ruta):
            filas += leer(ruta)
    lineas += ["", "## Carga diaria: tiempos por modelo (segundos)", "",
               "| Escala | Modelo | Mediana | Percentil 95 | Rango intercuartílico | Máximo | Día del máximo |",
               "| --- | --- | --- | --- | --- | --- | --- |"]
    for esc in (30, 60, 90):
        for m in ("a", "b_gist", "b_wo"):
            s = sorted((float(r["segundos"]), int(r["dia_n"])) for r in filas
                       if int(r["escala"]) == esc and r["modelo"] == m)
            if not s:
                continue
            v = [x for x, _ in s]
            q = statistics.quantiles(v, n=100)
            lineas.append(f"| {esc} | {m} | {statistics.median(v):.3f} | {q[94]:.3f} | {q[24]:.3f} – {q[74]:.3f} | "
                          f"{v[-1]:.3f} | {s[-1][1]} |")

    lineas += ["", "## Comparaciones emparejadas (bootstrap, 10.000 remuestreos, semilla fija)", "",
               "| Análisis | Comparación | Pares | Mediana de la razón | IC 95% | Veredicto |",
               "| --- | --- | --- | --- | --- | --- |"]
    analisis = [("Principal: escala 30, días 1–30", 30, None),
                ("Sensibilidad: escala 90, días 2–90", 90, set(range(2, 91)))]
    for nombre, esc, dias in analisis:
        if not any(int(r["escala"]) == esc for r in filas):
            continue
        for modelo, ref, h in (("b_wo", "a", "H3a"), ("b_wo", "b_gist", "H3b")):
            c = comparar(filas, esc, modelo, ref, dias)
            lineas.append(f"| {nombre} | {h}: {modelo} / {ref} | {c['pares']} | {c['mediana_razon']:.2f} | "
                          f"{c['ic95'][0]:.2f} – {c['ic95'][1]:.2f} | {c['veredicto']} |")
    lineas += ["", "Lectura de la razón: 0,50 = tarda la mitad; 2,00 = tarda el doble. "
               "Regla: hay diferencia si el IC 95% no incluye 1 y la mediana está fuera de 0,9–1,1."]

    salida = os.path.join(R, "analisis_carga.md")
    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))
    print(f"\nGuardado en {salida}")


if __name__ == "__main__":
    main()

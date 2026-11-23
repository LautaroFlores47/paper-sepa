#!/usr/bin/env python3
"""
medir_consultas.py — T23, T24, T31 y análisis de H2a / H2b: tiempos de Q1 a Q4 en A y en B-WO.

Consultas (misma respuesta lógica en los dos modelos; el script lo verifica caso por caso):
  Q1 puntual, angosta   precio de un producto en una sucursal en una fecha
  Q2 puntual, amplia    precios de todos los productos de una sucursal en una fecha
  Q3 histórica, angosta serie diaria de precios de un producto en una sucursal en toda la ventana
                        (en B incluye expandir los tramos a días)
  Q4 histórica, amplia  por cada clave: precio mínimo, máximo y cantidad de cambios en la ventana
                        (un día sin dato no cuenta como cambio; en B se compara con el tramo anterior)

Protocolo (sección 3 del plan, con el cambio aprobado el 22/11: solo caché caliente):
  - 30 casos por consulta y escala, sorteados con semilla fija; Q4 no tiene parámetros: 30 repeticiones.
  - Cada caso se corre en A y en B-WO; el orden se alterna (impar: A primero, par: B primero).
  - Antes de medir, 5 corridas de calentamiento por consulta y modelo, que se descartan.
  - El tiempo es el de ejecutar y traer el resultado completo (lo que esperaría una aplicación).
  - Se guarda un EXPLAIN (ANALYZE, BUFFERS) por consulta, modelo y escala, para la discusión.
  - Análisis: razón B-WO / A por caso, mediana e IC 95% por bootstrap (10.000 remuestreos, semilla fija).

Nota (corregido el 22/11): los parámetros se convierten explícitamente a int y date en el SQL.
Sin eso, psycopg manda los números chicos como smallint; el B-tree de A lo acepta, pero el índice
GiST de B (btree_gist) no compara smallint con int, y PostgreSQL termina leyendo toda la tabla B.

Uso (con $env:PGPASSWORD definido):   python medir_consultas.py
Escribe resultados/consultas.csv, resultados/analisis_consultas.md y resultados/planes/*.txt
"""
import argparse
import csv
import datetime as dt
import os
import random
import statistics
import sys
import time

import psycopg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analizar_carga import bootstrap_mediana  # noqa: E402  (mismo bootstrap que la carga)

SEMILLA = 20261122
CASOS = 30
CALENTAMIENTO = 5


def sql(escala, hasta):
    e = f"e{escala}"
    fin = f"date '{hasta}' + 1"
    return {
        "Q1": {"a": f"SELECT precio_lista FROM {e}.a WHERE sucursal_id = %(s)s::int AND producto_id = %(p)s::int AND fecha = %(f)s::date",
               "b_wo": f"SELECT precio_lista FROM {e}.b_wo WHERE sucursal_id = %(s)s::int AND producto_id = %(p)s::int "
                       f"AND vigencia @> %(f)s::date"},
        "Q2": {"a": f"SELECT producto_id, precio_lista FROM {e}.a WHERE sucursal_id = %(s)s::int AND fecha = %(f)s::date "
                    f"ORDER BY producto_id",
               "b_wo": f"SELECT producto_id, precio_lista FROM {e}.b_wo WHERE sucursal_id = %(s)s::int "
                       f"AND vigencia @> %(f)s::date ORDER BY producto_id"},
        "Q3": {"a": f"SELECT fecha, precio_lista FROM {e}.a WHERE sucursal_id = %(s)s::int AND producto_id = %(p)s::int "
                    f"ORDER BY fecha",
               "b_wo": f"SELECT g::date AS fecha, precio_lista FROM {e}.b_wo, "
                       f"generate_series(lower(vigencia), coalesce(upper(vigencia), {fin}) - 1, interval '1 day') g "
                       f"WHERE sucursal_id = %(s)s::int AND producto_id = %(p)s::int ORDER BY 1"},
        "Q4": {"a": f"""SELECT sucursal_id, producto_id, min(precio_lista), max(precio_lista), count(*) FILTER (WHERE cambio)
                        FROM (SELECT sucursal_id, producto_id, precio_lista,
                                     precio_lista <> lag(precio_lista) OVER w AND fecha = lag(fecha) OVER w + 1 AS cambio
                              FROM {e}.a WINDOW w AS (PARTITION BY sucursal_id, producto_id ORDER BY fecha)) t
                        GROUP BY 1, 2 ORDER BY 1, 2""",
               "b_wo": f"""SELECT sucursal_id, producto_id, min(precio_lista), max(precio_lista), count(*) FILTER (WHERE cambio)
                           FROM (SELECT sucursal_id, producto_id, precio_lista,
                                        precio_lista <> lag(precio_lista) OVER w
                                        AND lower(vigencia) = lag(upper(vigencia)) OVER w AS cambio
                                 FROM {e}.b_wo WINDOW w AS (PARTITION BY sucursal_id, producto_id ORDER BY lower(vigencia))) t
                           GROUP BY 1, 2 ORDER BY 1, 2"""},
    }


def sortear(conn, escala, desde, hasta, rnd):
    """Casos con respuesta existente: se elige un tramo al azar de B y una fecha dentro de él."""
    e = f"e{escala}"
    tramos = conn.execute(f"SELECT sucursal_id, producto_id, lower(vigencia), "
                          f"coalesce(upper(vigencia), date '{hasta}' + 1) FROM {e}.b_wo "
                          f"ORDER BY sucursal_id, producto_id, lower(vigencia)").fetchall()
    sucursales = [r[0] for r in conn.execute(f"SELECT DISTINCT sucursal_id FROM {e}.b_wo ORDER BY 1")]
    dias = (hasta - desde).days + 1
    casos = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for _ in range(CASOS + CALENTAMIENTO):
        s, p, lo, hi = rnd.choice(tramos)
        casos["Q1"].append({"s": s, "p": p, "f": lo + dt.timedelta(days=rnd.randrange((hi - lo).days))})
        casos["Q2"].append({"s": rnd.choice(sucursales), "f": desde + dt.timedelta(days=rnd.randrange(dias))})
        s3, p3, _, _ = rnd.choice(tramos)
        casos["Q3"].append({"s": s3, "p": p3})
        casos["Q4"].append({})
    return casos


def correr(conn, consulta, params):
    t0 = time.perf_counter()
    filas = conn.execute(consulta, params).fetchall()
    return time.perf_counter() - t0, filas


def normalizar(filas):
    return sorted(tuple(str(x) for x in f) for f in filas)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--escalas", nargs="+", type=int, default=[30, 60, 90])
    ap.add_argument("--desde", default="2025-02-01")
    ap.add_argument("--resultados", default="resultados")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--puerto", default="5432")
    ap.add_argument("--base", default="sepa")
    ap.add_argument("--usuario", default="postgres")
    ap.add_argument("--precalentar", action="store_true",
                    help="antes de cada escala, carga A, B-WO y sus índices en la memoria de PostgreSQL (pg_prewarm)")
    args = ap.parse_args()
    R = args.resultados
    os.makedirs(os.path.join(R, "planes"), exist_ok=True)
    desde = dt.date.fromisoformat(args.desde)
    rnd = random.Random(SEMILLA)
    registros, distintas = [], 0

    with psycopg.connect(host=args.host, port=args.puerto, dbname=args.base, user=args.usuario,
                         autocommit=True) as conn:
        version = conn.execute("SELECT version()").fetchone()[0]
        ajustes = {k: conn.execute(f"SHOW {k}").fetchone()[0] for k in
                   ("shared_buffers", "work_mem", "jit", "max_parallel_workers_per_gather", "effective_cache_size")}
        print(version)
        print("Configuración:", ajustes)
        for esc in args.escalas:
            hasta = desde + dt.timedelta(days=esc - 1)
            consultas = sql(esc, hasta)
            casos = sortear(conn, esc, desde, hasta, rnd)
            if args.precalentar:
                conn.execute("CREATE EXTENSION IF NOT EXISTS pg_prewarm")
                objetos = [r[0] for r in conn.execute(
                    "SELECT quote_ident(schemaname) || '.' || quote_ident(indexname) FROM pg_indexes "
                    "WHERE schemaname = %s AND tablename IN ('a', 'b_wo')", (f"e{esc}",))]
                paginas = 0
                for obj in [f"e{esc}.a", f"e{esc}.b_wo"] + objetos:
                    paginas += conn.execute("SELECT pg_prewarm(%s::regclass)", (obj,)).fetchone()[0]
                print(f"  e{esc}: precalentadas {paginas:,} páginas ({paginas * 8 / 1024:.0f} MB)")
            for q, por_modelo in consultas.items():
                lista = casos[q]
                # calentamiento
                for params in lista[:CALENTAMIENTO]:
                    for m in ("a", "b_wo"):
                        correr(conn, por_modelo[m], params)
                # un plan por consulta y modelo
                for m in ("a", "b_wo"):
                    plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS) " + por_modelo[m], lista[CALENTAMIENTO]).fetchall()
                    with open(os.path.join(R, "planes", f"e{esc}_{q}_{m}.txt"), "w", encoding="utf-8") as f:
                        f.write(f"-- parámetros: {lista[CALENTAMIENTO]}\n" + "\n".join(r[0] for r in plan) + "\n")
                # medición
                for i, params in enumerate(lista[CALENTAMIENTO:], 1):
                    print(f"\r  e{esc} {q}: caso {i}/{CASOS}   ", end="", flush=True)
                    orden = ("a", "b_wo") if i % 2 else ("b_wo", "a")
                    res = {}
                    for m in orden:
                        seg, filas = correr(conn, por_modelo[m], params)
                        res[m] = filas
                        registros.append({"escala": esc, "consulta": q, "caso": i, "modelo": m,
                                          "segundos": round(seg, 6), "filas": len(filas),
                                          "parametros": " ".join(f"{k}={v}" for k, v in params.items())})
                    if normalizar(res["a"]) != normalizar(res["b_wo"]):
                        distintas += 1
                        print(f"  ATENCIÓN: e{esc} {q} caso {i}: A y B-WO devuelven cosas distintas ({params})")
                print(f"\r  e{esc} {q}: listo          ")

    with open(os.path.join(R, "consultas.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(registros[0]))
        w.writeheader()
        w.writerows(registros)

    # ------------------------------------------------------------------ análisis
    hip = {"Q1": "H2a", "Q2": "H2a", "Q3": "H2b", "Q4": "H2b"}
    lineas = ["# Consultas Q1 a Q4 (H2a y H2b)", "",
              f"{version}. Configuración: {ajustes}. Solo caché caliente (cambio al protocolo aprobado el 22/11)."
              + (" Tablas e índices precalentados con pg_prewarm antes de cada escala." if args.precalentar else ""),
              f"Casos en que A y B-WO devolvieron respuestas distintas: **{distintas}** (tiene que ser 0).", "",
              "| Escala | Consulta | Hipótesis | Mediana A (ms) | Mediana B-WO (ms) | P95 A (ms) | P95 B-WO (ms) | "
              "Mediana razón B-WO/A | IC 95% | Veredicto |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for esc in args.escalas:
        for q in ("Q1", "Q2", "Q3", "Q4"):
            t = {}
            for r in registros:
                if r["escala"] == esc and r["consulta"] == q:
                    t.setdefault(r["caso"], {})[r["modelo"]] = r["segundos"]
            a = [v["a"] for v in t.values()]
            b = [v["b_wo"] for v in t.values()]
            razones = [v["b_wo"] / v["a"] for v in t.values() if v["a"] > 0]
            med = statistics.median(razones)
            lo, hi = bootstrap_mediana(razones)
            if not (lo <= 1 <= hi) and (med < 0.9 or med > 1.1):
                ver = "B-WO más rápida" if med < 1 else "B-WO más lenta"
            else:
                ver = "sin diferencia detectable"
            p95 = lambda v: statistics.quantiles(v, n=100)[94]   # noqa: E731
            lineas.append(f"| {esc} | {q} | {hip[q]} | {1000 * statistics.median(a):.2f} | {1000 * statistics.median(b):.2f} | "
                          f"{1000 * p95(a):.2f} | {1000 * p95(b):.2f} | {med:.2f} | {lo:.2f} – {hi:.2f} | {ver} |")
    lineas += ["", "H2a (Q1, Q2): se refuta si B-WO es más rápida que A. "
               "H2b (Q3, Q4): se refuta si B-WO no es más rápida que A.",
               "Razón 0,50 = B-WO tarda la mitad; 2,00 = el doble. Hay diferencia si el IC 95% no incluye 1 "
               "y la mediana está fuera de 0,9–1,1."]
    salida = os.path.join(R, "analisis_consultas.md")
    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))
    print(f"\nGuardado en {salida}; planes en {os.path.join(R, 'planes')}")


if __name__ == "__main__":
    main()

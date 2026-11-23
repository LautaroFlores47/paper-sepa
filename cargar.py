#!/usr/bin/env python3
"""
cargar.py — T17, T18, T20, T21, T26 y T27: crea las tablas del experimento y las carga día por día.

Modelos (todos con las mismas columnas de datos y sobre las mismas dimensiones):
  a      una fila por (sucursal, producto, fecha)                 PK B-tree (sucursal_id, producto_id, fecha)
  b_gist una fila por tramo de precio, con daterange             índice GiST (sucursal_id, producto_id, vigencia), SIN restricción
  b_wo   igual que b_gist, pero con                              PRIMARY KEY (sucursal_id, producto_id, vigencia WITHOUT OVERLAPS)

Escalas: cada escala (30, 60 o 90 días) es un esquema aparte (e30, e60, e90) cargado desde cero.

Carga incremental (la misma lógica que tendría un sistema real que recibe un archivo por día):
  - A: se insertan las observaciones del día.
  - B: en una transacción por día
       1) se cierran los tramos abiertos cuya clave no vino hoy o vino con otro precio
          (un día sin dato corta el tramo: no se inventan precios)
       2) se abre un tramo [hoy, ∞) para cada clave que no tiene tramo abierto
     Un tramo abierto (sin fin) significa "vigente hasta el último día cargado".
  Solo se mide el tiempo de aplicar el día al modelo; preparar la tabla temporal del día no se cuenta.

Uso (PowerShell, con $env:PGPASSWORD ya definido):
  python cargar.py --limpio C:\\sepa-crudos\\limpio --escala 30 --modelos a b_gist b_wo
Escribe resultados/carga_e30.csv (tiempos por día) y resultados/tamanos.csv (tamaños al terminar).
Necesita: python -m pip install "psycopg[binary]"
"""
import argparse
import csv
import datetime as dt
import gzip
import os
import sys
import time

import psycopg

DIAS_VENTANA_DESDE = "2025-02-01"


def conectar(args):
    return psycopg.connect(host=args.host, port=args.puerto, dbname=args.base, user=args.usuario,
                           autocommit=True)


def version_mayor(conn):
    return int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000


def preparar_base(conn, limpio):
    """Extensión, dimensiones y tabla con todas las observaciones limpias (una sola vez)."""
    conn.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    conn.execute("CREATE SCHEMA IF NOT EXISTS dim")
    existe = conn.execute("SELECT to_regclass('dim.observacion') IS NOT NULL").fetchone()[0]
    if existe:
        return
    print("Cargando dimensiones y observaciones limpias (una sola vez)...")
    conn.execute("""CREATE TABLE dim.sucursal (sucursal_id int PRIMARY KEY, id_comercio text, id_bandera text,
                     id_sucursal text, nombre text, tipo text, calle text, numero text, latitud text, longitud text,
                     codigo_postal text, localidad text, provincia text, fecha_ultimo_dato date)""")
    conn.execute("""CREATE TABLE dim.producto (producto_id int PRIMARY KEY, id_comercio text, id_producto text,
                     descripcion text, marca text, cantidad_presentacion text, unidad_medida_presentacion text)""")
    conn.execute("""CREATE TABLE dim.observacion (fecha date NOT NULL, sucursal_id int NOT NULL,
                     producto_id int NOT NULL, precio_lista numeric(12,2) NOT NULL)""")
    with conn.cursor() as cur:
        for tabla, archivo, abrir in (("dim.sucursal", "sucursales.csv", open),
                                      ("dim.producto", "productos.csv", open),
                                      ("dim.observacion", "observaciones.csv.gz", gzip.open)):
            with abrir(os.path.join(limpio, archivo), "rb") as f, \
                    cur.copy(f"COPY {tabla} FROM STDIN WITH (FORMAT csv, HEADER true)") as cp:
                while bloque := f.read(1 << 20):
                    cp.write(bloque)
    conn.execute("CREATE INDEX ON dim.observacion (fecha)")
    for t in ("dim.sucursal", "dim.producto", "dim.observacion"):
        conn.execute(f"ANALYZE {t}")
    n = conn.execute("SELECT count(*) FROM dim.observacion").fetchone()[0]
    print(f"  {n:,} observaciones")


def crear_tablas(conn, esquema, modelos, pg):
    conn.execute(f"DROP SCHEMA IF EXISTS {esquema} CASCADE")
    conn.execute(f"CREATE SCHEMA {esquema}")
    datos = "sucursal_id int NOT NULL, producto_id int NOT NULL, precio_lista numeric(12,2) NOT NULL"
    if "a" in modelos:
        conn.execute(f"""CREATE TABLE {esquema}.a (fecha date NOT NULL, {datos},
                         PRIMARY KEY (sucursal_id, producto_id, fecha))""")
    if "b_gist" in modelos:
        conn.execute(f"CREATE TABLE {esquema}.b_gist ({datos}, vigencia daterange NOT NULL)")
        conn.execute(f"CREATE INDEX b_gist_idx ON {esquema}.b_gist USING gist (sucursal_id, producto_id, vigencia)")
    if "b_wo" in modelos:
        if pg >= 18:
            restriccion = "PRIMARY KEY (sucursal_id, producto_id, vigencia WITHOUT OVERLAPS)"
        else:   # solo para probar el script en versiones viejas: NO sirve para medir
            print("  AVISO: PostgreSQL < 18, b_wo se crea con EXCLUDE (solo prueba, no para el paper)")
            restriccion = ("CONSTRAINT b_wo_pkey EXCLUDE USING gist "
                           "(sucursal_id WITH =, producto_id WITH =, vigencia WITH &&)")
        conn.execute(f"CREATE TABLE {esquema}.b_wo ({datos}, vigencia daterange NOT NULL, {restriccion})")


def cargar_dia_a(cur, esquema, d):
    cur.execute(f"INSERT INTO {esquema}.a (fecha, sucursal_id, producto_id, precio_lista) "
                "SELECT fecha, sucursal_id, producto_id, precio_lista FROM stg")
    return cur.rowcount, 0


def cargar_dia_b(cur, esquema, tabla, d):
    t = f"{esquema}.{tabla}"
    cur.execute(f"""UPDATE {t} b SET vigencia = daterange(lower(b.vigencia), %(d)s)
                    WHERE upper_inf(b.vigencia)
                      AND NOT EXISTS (SELECT 1 FROM stg s WHERE s.sucursal_id = b.sucursal_id
                                      AND s.producto_id = b.producto_id AND s.precio_lista = b.precio_lista)""",
                {"d": d})
    cerrados = cur.rowcount
    cur.execute(f"""INSERT INTO {t} (sucursal_id, producto_id, precio_lista, vigencia)
                    SELECT s.sucursal_id, s.producto_id, s.precio_lista, daterange(%(d)s, NULL)
                    FROM stg s
                    WHERE NOT EXISTS (SELECT 1 FROM {t} b WHERE b.sucursal_id = s.sucursal_id
                                      AND b.producto_id = s.producto_id AND upper_inf(b.vigencia))""",
                {"d": d})
    return cur.rowcount, cerrados


def tamanos(conn, esquema, tabla):
    q = """SELECT pg_relation_size(c.oid), pg_indexes_size(c.oid), pg_total_relation_size(c.oid),
                  (SELECT count(*) FROM {t})
           FROM pg_class c WHERE c.oid = %s::regclass"""
    t = f"{esquema}.{tabla}"
    return conn.execute(q.format(t=t), (t,)).fetchone()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limpio", required=True, help="carpeta 'limpio' de preparar_dataset.py")
    ap.add_argument("--escala", type=int, required=True, choices=[30, 60, 90])
    ap.add_argument("--modelos", nargs="+", default=["a", "b_gist", "b_wo"], choices=["a", "b_gist", "b_wo"])
    ap.add_argument("--desde", default=DIAS_VENTANA_DESDE)
    ap.add_argument("--resultados", default="resultados")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--puerto", default="5432")
    ap.add_argument("--base", default="sepa")
    ap.add_argument("--usuario", default="postgres")
    args = ap.parse_args()
    if not os.environ.get("PGPASSWORD") and args.host == "localhost":
        print("Tip: definí $env:PGPASSWORD para que no te pida la contraseña.")

    os.makedirs(args.resultados, exist_ok=True)
    esquema = f"e{args.escala}"
    desde = dt.date.fromisoformat(args.desde)
    dias = [desde + dt.timedelta(i) for i in range(args.escala)]

    with conectar(args) as conn:
        pg = version_mayor(conn)
        version = conn.execute("SELECT version()").fetchone()[0]
        print(version)
        preparar_base(conn, args.limpio)
        crear_tablas(conn, esquema, args.modelos, pg)

        log_path = os.path.join(args.resultados, f"carga_{esquema}.csv")
        with open(log_path, "w", newline="", encoding="utf-8") as flog:
            w = csv.writer(flog)
            w.writerow(["escala", "modelo", "dia_n", "fecha", "filas_dia", "insertadas", "cerradas", "segundos"])
            for n, d in enumerate(dias, 1):
                conn.execute("DROP TABLE IF EXISTS stg")
                conn.execute("CREATE TEMP TABLE stg AS SELECT * FROM dim.observacion WHERE fecha = %s", (d,))
                conn.execute("ANALYZE stg")
                filas = conn.execute("SELECT count(*) FROM stg").fetchone()[0]
                # orden alternado entre modelos para no favorecer siempre al mismo con la caché
                orden = args.modelos if n % 2 else list(reversed(args.modelos))
                for m in orden:
                    t0 = time.perf_counter()
                    with conn.transaction(), conn.cursor() as cur:
                        ins, cer = cargar_dia_a(cur, esquema, d) if m == "a" else cargar_dia_b(cur, esquema, m, d)
                    seg = time.perf_counter() - t0   # incluye el COMMIT: es parte del costo real de cargar
                    w.writerow([args.escala, m, n, d, filas, ins, cer, round(seg, 4)])
                print(f"\r  día {n}/{len(dias)} ({d}) · {filas:,} observaciones", end="", flush=True)
        print()

        for m in args.modelos:
            conn.execute(f"ANALYZE {esquema}.{m}")
        ruta_t = os.path.join(args.resultados, "tamanos.csv")
        nuevo = not os.path.exists(ruta_t)
        with open(ruta_t, "a", newline="", encoding="utf-8") as ft:
            w = csv.writer(ft)
            if nuevo:
                w.writerow(["momento", "escala", "modelo", "filas", "bytes_tabla", "bytes_indices", "bytes_total",
                            "version", "registrado"])
            # tres momentos: recién cargado (con lo que dejaron los UPDATE), después de un VACUUM común,
            # y compacto (VACUUM FULL reconstruye tabla e índices: es la comparación de espacio más justa)
            for momento in ("tras_carga", "tras_vacuum", "compacto"):
                for m in args.modelos:
                    if momento == "tras_vacuum":
                        conn.execute(f"VACUUM (ANALYZE) {esquema}.{m}")
                    elif momento == "compacto":
                        conn.execute(f"VACUUM (FULL, ANALYZE) {esquema}.{m}")
                for m in args.modelos:
                    tabla, idx, total, filas = tamanos(conn, esquema, m)
                    w.writerow([momento, args.escala, m, filas, tabla, idx, total, version.split(" on ")[0],
                                dt.datetime.now().isoformat(timespec="seconds")])
                    if momento != "tras_carga":
                        print(f"  {momento:11s} {m:7s} {filas:>11,} filas · tabla {tabla / 1e6:8.1f} MB · "
                              f"índices {idx / 1e6:8.1f} MB · total {total / 1e6:8.1f} MB")
        import statistics
        with open(log_path, encoding="utf-8") as f:
            filas_log = list(csv.DictReader(f))
        for m in args.modelos:
            s = [float(r["segundos"]) for r in filas_log if r["modelo"] == m]
            print(f"  carga diaria {m:7s}: mediana {statistics.median(s):.3f} s · máximo {max(s):.3f} s")
        print(f"Tiempos por día: {log_path}\nTamaños: {ruta_t}")


if __name__ == "__main__":
    main()

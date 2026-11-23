#!/usr/bin/env python3
"""
verificar_equivalencia.py — T28: comprueba que A, B-GiST y B-WO guardan exactamente la misma información.

Para una escala (e30, e60 o e90):
  1. A tiene que ser igual, fila por fila, a las observaciones limpias de esos días.
  2. Expandiendo cada tramo de B a sus días (un tramo abierto llega hasta el último día cargado),
     tiene que salir exactamente A. Se comprueba para B-GiST y para B-WO.
  3. B-GiST no tiene restricción: se verifica aparte que no tenga tramos superpuestos.
  4. Los índices GiST de B-GiST y B-WO tienen que ser equivalentes (mismas columnas y clases de operadores).
     Si no lo son, la comparación de H3b no vale.

Uso:  python verificar_equivalencia.py --escala 30
"""
import argparse
import datetime as dt
import sys

import psycopg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--escala", type=int, required=True, choices=[30, 60, 90])
    ap.add_argument("--desde", default="2025-02-01")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--puerto", default="5432")
    ap.add_argument("--base", default="sepa")
    ap.add_argument("--usuario", default="postgres")
    args = ap.parse_args()
    e = f"e{args.escala}"
    desde = dt.date.fromisoformat(args.desde)
    hasta = desde + dt.timedelta(days=args.escala - 1)
    ok = True

    def informar(nombre, valor, esperado=0):
        nonlocal ok
        bien = valor == esperado
        ok &= bien
        print(f"  {'PASA   ' if bien else 'NO PASA'}  {nombre}: {valor:,}")

    with psycopg.connect(host=args.host, port=args.puerto, dbname=args.base, user=args.usuario) as conn:
        q = lambda sql, p=None: conn.execute(sql, p).fetchone()[0]   # noqa: E731
        print(f"Escala {e} ({desde} a {hasta})")
        fuente = (f"SELECT fecha, sucursal_id, producto_id, precio_lista FROM dim.observacion "
                  f"WHERE fecha BETWEEN '{desde}' AND '{hasta}'")
        a = f"SELECT fecha, sucursal_id, producto_id, precio_lista FROM {e}.a"
        informar("filas de la fuente que faltan en A", q(f"SELECT count(*) FROM ({fuente} EXCEPT ALL {a}) x"))
        informar("filas de A que no están en la fuente", q(f"SELECT count(*) FROM ({a} EXCEPT ALL {fuente}) x"))
        for b in ("b_gist", "b_wo"):
            if q("SELECT to_regclass(%s) IS NULL", (f"{e}.{b}",)):
                print(f"  (no existe {e}.{b}, se saltea)")
                continue
            expandido = (f"SELECT g::date AS fecha, sucursal_id, producto_id, precio_lista FROM {e}.{b}, "
                         f"generate_series(lower(vigencia), coalesce(upper(vigencia), date '{hasta}' + 1) - 1, "
                         f"interval '1 day') g")
            informar(f"filas de A que faltan al expandir {b}", q(f"SELECT count(*) FROM ({a} EXCEPT ALL {expandido}) x"))
            informar(f"filas que sobran al expandir {b}", q(f"SELECT count(*) FROM ({expandido} EXCEPT ALL {a}) x"))
            informar(f"tramos de {b} con fin anterior o igual al inicio",
                     q(f"SELECT count(*) FROM {e}.{b} WHERE isempty(vigencia)"))
        if not q("SELECT to_regclass(%s) IS NULL", (f"{e}.b_gist",)):
            informar("pares de tramos superpuestos en b_gist",
                     q(f"""SELECT count(*) FROM {e}.b_gist x JOIN {e}.b_gist y
                           ON x.sucursal_id = y.sucursal_id AND x.producto_id = y.producto_id
                          AND x.ctid < y.ctid AND x.vigencia && y.vigencia"""))
        if not q("SELECT to_regclass(%s) IS NULL", (f"{e}.b_gist",)) and \
                not q("SELECT to_regclass(%s) IS NULL", (f"{e}.b_wo",)):
            sql = """SELECT am.amname, array_agg(a.attname ORDER BY k.ord), array_agg(oc.opcname ORDER BY k.ord)
                     FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_am am ON am.oid = ic.relam
                     CROSS JOIN LATERAL unnest(i.indkey, i.indclass) WITH ORDINALITY AS k(attnum, opc, ord)
                     JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                     JOIN pg_opclass oc ON oc.oid = k.opc
                     WHERE i.indrelid = %s::regclass GROUP BY am.amname"""
            g = conn.execute(sql, (f"{e}.b_gist",)).fetchall()
            w = conn.execute(sql, (f"{e}.b_wo",)).fetchall()
            iguales = g == w and len(g) == 1
            ok &= iguales
            print(f"  {'PASA   ' if iguales else 'NO PASA'}  índices equivalentes: b_gist {g} · b_wo {w}")
    print("\nResultado:", "EQUIVALENTES (hito H3 en lo que respecta a los datos)" if ok else "HAY DIFERENCIAS")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

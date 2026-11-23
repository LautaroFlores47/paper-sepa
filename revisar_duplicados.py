#!/usr/bin/env python3
"""
revisar_duplicados.py — T13 (parte 2): de dónde salen las claves repetidas en un mismo día.

Usa la asignación de paquetes que dejó analizar_ventana.py (t13/asignacion_paquetes.csv) y busca,
dentro de cada archivo, productos que aparecen más de una vez para la misma sucursal.

Responde:
  - qué comercios los tienen y cuántos son;
  - si las filas repetidas tienen el MISMO precio (repetición inofensiva) o precios DISTINTOS (conflicto);
  - si las filas repetidas difieren en descripción, marca o presentación (dos productos con el mismo código).

Uso:
  python revisar_duplicados.py --carpeta C:\\sepa-crudos
Escribe t13/duplicados_resumen.csv y t13/duplicados_ejemplos.csv
"""
import argparse
import os

import pandas as pd

CLAVE = ["id_comercio", "id_bandera", "id_sucursal", "id_producto"]
COLS = CLAVE + ["productos_descripcion", "productos_marca", "productos_cantidad_presentacion",
                "productos_unidad_medida_presentacion", "productos_precio_lista",
                "productos_precio_unitario_promo1", "productos_precio_unitario_promo2"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carpeta", required=True)
    args = ap.parse_args()
    t13 = os.path.join(args.carpeta, "t13")
    asig = pd.read_csv(os.path.join(t13, "asignacion_paquetes.csv"), dtype=str)
    usados = asig[(asig["repetido"] == "False") & asig["fecha_propia"].notna()]
    por_archivo = usados.groupby("base")["id_comercio"].apply(set).to_dict()

    resumen, ejemplos = [], []
    for i, (base, comercios) in enumerate(sorted(por_archivo.items()), 1):
        print(f"\r  revisando {i}/{len(por_archivo)}   ", end="", flush=True)
        ruta = os.path.join(args.carpeta, "recorte", f"{base}_productos.csv.gz")
        p = pd.read_csv(ruta, dtype=str, keep_default_na=False, usecols=lambda c: c in COLS)
        p = p[p["id_comercio"].isin(comercios)]
        d = p[p.duplicated(CLAVE, keep=False)]
        if d.empty:
            continue
        g = d.groupby(CLAVE)
        info = g.agg(veces=("productos_precio_lista", "size"),
                     precios_distintos=("productos_precio_lista", "nunique"),
                     descripciones_distintas=("productos_descripcion", "nunique"),
                     presentaciones_distintas=("productos_cantidad_presentacion", "nunique")).reset_index()
        info["base"] = base
        resumen.append(info)
        if len(ejemplos) < 60:
            ejemplos.append(d.sort_values(CLAVE).head(12).assign(base=base))
    print()
    if not resumen:
        print("No hay claves repetidas en los paquetes usados.")
        return
    r = pd.concat(resumen, ignore_index=True)
    r["tipo"] = "mismo precio"
    r.loc[r["precios_distintos"] > 1, "tipo"] = "precios distintos"
    r.loc[(r["precios_distintos"] > 1) & ((r["descripciones_distintas"] > 1) | (r["presentaciones_distintas"] > 1)),
          "tipo"] = "precios distintos y producto distinto"
    tabla = (r.groupby(["id_comercio", "tipo"]).agg(claves_dia=("veces", "size"), filas_extra=("veces", lambda s: int((s - 1).sum())),
                                                    dias=("base", "nunique"), productos=("id_producto", "nunique"))
             .reset_index())
    tabla.to_csv(os.path.join(t13, "duplicados_resumen.csv"), index=False)
    pd.concat(ejemplos, ignore_index=True).to_csv(os.path.join(t13, "duplicados_ejemplos.csv"), index=False)
    print(tabla.to_string(index=False))
    print(f"\nTotal de filas extra: {int((r['veces'] - 1).sum()):,}")
    print(f"Detalle: {os.path.join(t13, 'duplicados_resumen.csv')} y duplicados_ejemplos.csv")


if __name__ == "__main__":
    main()

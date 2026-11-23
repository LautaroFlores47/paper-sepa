#!/usr/bin/env python3
"""
preparar_dataset.py — T14 a T16: dataset limpio, listo para cargar en PostgreSQL.

Parte de lo que decidió la T13 (analizar_ventana.py):
  - t13/asignacion_paquetes.csv : qué paquete de cada comercio se usa y con qué fecha propia
  - t13/comercios.csv           : qué comercios se incluyen
Y aplica las reglas de limpieza en este orden, contando cuántas filas saca cada una:
  1. comercio excluido (congelado, precios inválidos o baja cobertura)
  2. paquete repetido o con fecha propia fuera de la ventana
  3. precio de lista inválido (vacío, texto, cero o negativo)  -> esa clave queda "sin dato" ese día
  4. filas repetidas idénticas (misma clave, día y precio)     -> se deja una
  5. misma clave y día con precios distintos                   -> la clave queda "sin dato" ese día

Genera en <carpeta>/limpio:
  observaciones.csv.gz   fecha, sucursal_id, producto_id, precio_lista   (es lo que se carga en A y B)
  sucursales.csv         sucursal_id + datos de la sucursal (dimensión compartida por A y B)
  productos.csv          producto_id + descripción, marca y presentación (dimensión compartida)
  comercios.csv          comercios incluidos
  ausencias.csv          cada día sin dato de una clave entre dos observaciones, con su motivo
  reporte_limpieza.md    cuántas filas sacó cada regla, para el paper (T14)

Uso:
  python preparar_dataset.py --carpeta C:\\sepa-crudos --desde 2025-02-01 --hasta 2025-05-01
"""
import argparse
import datetime as dt
import os

import pandas as pd

LEER = ["id_comercio", "id_bandera", "id_sucursal", "id_producto", "productos_descripcion",
        "productos_marca", "productos_cantidad_presentacion", "productos_unidad_medida_presentacion",
        "productos_precio_lista"]
SUC = ["id_comercio", "id_bandera", "id_sucursal", "sucursales_nombre", "sucursales_tipo", "sucursales_calle",
       "sucursales_numero", "sucursales_latitud", "sucursales_longitud", "sucursales_codigo_postal",
       "sucursales_localidad", "sucursales_provincia"]
CLAVE = ["id_comercio", "id_bandera", "id_sucursal", "id_producto"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carpeta", required=True)
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    args = ap.parse_args()
    desde, hasta = dt.date.fromisoformat(args.desde), dt.date.fromisoformat(args.hasta)
    t13 = os.path.join(args.carpeta, "t13")
    rec = os.path.join(args.carpeta, "recorte")
    sal = os.path.join(args.carpeta, "limpio")
    os.makedirs(sal, exist_ok=True)

    asig = pd.read_csv(os.path.join(t13, "asignacion_paquetes.csv"), dtype=str)
    com = pd.read_csv(os.path.join(t13, "comercios.csv"), dtype=str)
    incluidos = set(com.loc[com["decision"] == "incluir", "id_comercio"])
    asig["fecha_propia"] = pd.to_datetime(asig["fecha_propia"], errors="coerce").dt.date
    asig["valido"] = (asig["repetido"] == "False") & asig["fecha_propia"].notna() & \
        asig["fecha_propia"].between(desde, hasta)
    bases = sorted(asig["base"].unique())
    usar = {(r.base, r.id_comercio): r.fecha_propia for r in asig[asig["valido"]].itertuples()}
    paquetes_por_comercio = asig[asig["valido"]].groupby("id_comercio")["fecha_propia"].apply(set).to_dict()

    conteo = {"filas_leidas": 0, "comercio_excluido": 0, "paquete_repetido_o_fuera_de_ventana": 0,
              "precio_invalido": 0, "repetidas_identicas": 0, "conflicto_precios_distintos": 0}
    partes, sucs, prods = [], [], []
    for i, base in enumerate(bases, 1):
        print(f"\r  leyendo {i}/{len(bases)}   ", end="", flush=True)
        p = pd.read_csv(os.path.join(rec, f"{base}_productos.csv.gz"), dtype=str, keep_default_na=False,
                        usecols=lambda c: c in LEER)
        conteo["filas_leidas"] += len(p)
        incl = p["id_comercio"].isin(incluidos)
        conteo["comercio_excluido"] += int((~incl).sum())
        p = p[incl]
        p["fecha"] = [usar.get((base, c)) for c in p["id_comercio"]]
        sin_fecha = p["fecha"].isna()
        conteo["paquete_repetido_o_fuera_de_ventana"] += int(sin_fecha.sum())
        p = p[~sin_fecha]
        if p.empty:
            continue
        precio = pd.to_numeric(p["productos_precio_lista"].str.replace(",", ".", regex=False), errors="coerce")
        p["precio_lista"] = precio.where(precio > 0).round(2)
        prods.append(p.drop_duplicates(["id_comercio", "id_producto"])[
            ["id_comercio", "id_producto", "productos_descripcion", "productos_marca",
             "productos_cantidad_presentacion", "productos_unidad_medida_presentacion", "fecha"]])
        partes.append(p[CLAVE + ["fecha", "precio_lista"]])
        s = pd.read_csv(os.path.join(rec, f"{base}_sucursales.csv.gz"), dtype=str, keep_default_na=False,
                        usecols=lambda c: c in SUC)
        sucs.append(s[s["id_comercio"].isin(set(p["id_comercio"]))].assign(fecha=p["fecha"].iloc[0]))
    print()

    o = pd.concat(partes, ignore_index=True)
    for c in CLAVE:
        o[c] = o[c].astype("category")
    # 3) precios inválidos: se anotan como ausencia y se sacan
    invalidos = o[o["precio_lista"].isna()][CLAVE + ["fecha"]]
    conteo["precio_invalido"] = len(invalidos)
    o = o[o["precio_lista"].notna()]
    # 4) repetidas idénticas
    antes = len(o)
    o = o.drop_duplicates(CLAVE + ["fecha", "precio_lista"])
    conteo["repetidas_identicas"] = antes - len(o)
    # 5) conflictos: misma clave y día, precios distintos -> sin dato
    conf = o.duplicated(CLAVE + ["fecha"], keep=False)
    conflictos = o[conf][CLAVE + ["fecha"]].drop_duplicates()
    conteo["conflicto_precios_distintos"] = int(conf.sum())
    o = o[~conf]

    # dimensiones (los datos descriptivos se toman de la fecha más reciente en que se vieron)
    suc = (pd.concat(sucs, ignore_index=True).sort_values("fecha")
           .drop_duplicates(["id_comercio", "id_bandera", "id_sucursal"], keep="last"))
    claves_suc = o[["id_comercio", "id_bandera", "id_sucursal"]].drop_duplicates().astype(str)
    suc = claves_suc.merge(suc, how="left", on=["id_comercio", "id_bandera", "id_sucursal"])
    suc = suc.sort_values(["id_comercio", "id_bandera", "id_sucursal"]).reset_index(drop=True)
    suc.insert(0, "sucursal_id", range(1, len(suc) + 1))
    suc = suc.rename(columns={"fecha": "fecha_ultimo_dato"})
    prod = (pd.concat(prods, ignore_index=True).sort_values("fecha")
            .drop_duplicates(["id_comercio", "id_producto"], keep="last").drop(columns="fecha"))
    claves_prod = o[["id_comercio", "id_producto"]].drop_duplicates().astype(str)
    prod = claves_prod.merge(prod, how="left", on=["id_comercio", "id_producto"])
    prod = prod.sort_values(["id_comercio", "id_producto"]).reset_index(drop=True)
    prod.insert(0, "producto_id", range(1, len(prod) + 1))

    o = o.astype({c: str for c in CLAVE})
    o = o.merge(suc[["sucursal_id", "id_comercio", "id_bandera", "id_sucursal"]],
                on=["id_comercio", "id_bandera", "id_sucursal"]) \
         .merge(prod[["producto_id", "id_comercio", "id_producto"]], on=["id_comercio", "id_producto"])
    o = o.sort_values(["fecha", "sucursal_id", "producto_id"])[["fecha", "sucursal_id", "producto_id", "precio_lista"]]

    # ausencias: días sin dato entre dos observaciones de la misma clave, con su motivo
    a = o.sort_values(["sucursal_id", "producto_id", "fecha"]).copy()
    a["fecha"] = pd.to_datetime(a["fecha"])
    misma = a["sucursal_id"].eq(a["sucursal_id"].shift()) & a["producto_id"].eq(a["producto_id"].shift())
    hueco = misma & (a["fecha"] - a["fecha"].shift()).dt.days.gt(1)
    previa = a["fecha"].shift()
    h = a[hueco].assign(desde=previa[hueco] + pd.Timedelta(days=1), hasta=a.loc[hueco, "fecha"] - pd.Timedelta(days=1))
    h["dia"] = [pd.date_range(d, x).date.tolist() for d, x in zip(h["desde"], h["hasta"])]
    h = h.explode("dia")[["sucursal_id", "producto_id", "dia"]]
    h = h.merge(suc[["sucursal_id", "id_comercio"]], on="sucursal_id")
    h["motivo"] = [("el producto no figura" if d in paquetes_por_comercio.get(c, set())
                    else "el comercio no tiene datos ese día") for c, d in zip(h["id_comercio"], h["dia"])]
    # precisión: si ese día la clave vino con precio inválido o en conflicto, ese es el motivo
    marcas = {}
    for df, motivo in ((invalidos, "precio inválido"), (conflictos, "precios distintos el mismo día")):
        if len(df):
            m = df.astype(str).merge(suc[["sucursal_id", "id_comercio", "id_bandera", "id_sucursal"]].astype(str),
                                     on=["id_comercio", "id_bandera", "id_sucursal"])
            m = m.merge(prod[["producto_id", "id_comercio", "id_producto"]].astype(str), on=["id_comercio", "id_producto"])
            for r in m.itertuples():
                marcas[(int(r.sucursal_id), int(r.producto_id), str(r.fecha))] = motivo
    if marcas:
        h["motivo"] = [marcas.get((s, p, str(d)), mo) for s, p, d, mo in
                       zip(h["sucursal_id"], h["producto_id"], h["dia"], h["motivo"])]

    # salida
    o.to_csv(os.path.join(sal, "observaciones.csv.gz"), index=False, compression="gzip")
    suc.to_csv(os.path.join(sal, "sucursales.csv"), index=False)
    prod.to_csv(os.path.join(sal, "productos.csv"), index=False)
    com[com["decision"] == "incluir"].to_csv(os.path.join(sal, "comercios.csv"), index=False)
    h.to_csv(os.path.join(sal, "ausencias.csv"), index=False)

    motivos = h.groupby(["id_comercio", "motivo"]).size().rename("dias_clave").reset_index()
    lineas = [f"# T14 · Limpieza del recorte {desde} a {hasta}", "",
              f"Generado el {dt.datetime.now():%Y-%m-%d %H:%M} con preparar_dataset.py.", "",
              "| Regla | Filas que saca |", "| --- | --- |"]
    for k in ("comercio_excluido", "paquete_repetido_o_fuera_de_ventana", "precio_invalido",
              "repetidas_identicas", "conflicto_precios_distintos"):
        lineas.append(f"| {k.replace('_', ' ')} | {conteo[k]:,} |")
    lineas += ["", f"- Filas leídas del recorte: {conteo['filas_leidas']:,}",
               f"- **Observaciones finales: {len(o):,}** (tendría que coincidir con las filas A a 90 días de la T13)",
               f"- Sucursales: {len(suc)} · productos: {len(prod):,} · comercios: {len(incluidos)}",
               f"- Días sin dato entre dos observaciones (clave × día): {len(h):,}", "",
               "| Comercio | Motivo de la ausencia | Clave × día |", "| --- | --- | --- |"]
    lineas += [f"| {r.id_comercio} | {r.motivo} | {r.dias_clave:,} |" for r in motivos.itertuples()]
    with open(os.path.join(sal, "reporte_limpieza.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas[4:]))
    print(f"\nArchivos en {sal}")


if __name__ == "__main__":
    main()

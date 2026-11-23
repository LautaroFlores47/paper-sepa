#!/usr/bin/env python3
"""
verificar_condiciones.py — Filtro de viabilidad del paper SEPA (Semana 1).

Mide las 3 condiciones antes de programar nada:
  C1. ¿Tenemos datos de distintas fechas?        -> fecha real y tamaño de cada archivo
  C2. ¿Podemos seguir el mismo producto en la    -> duplicados por clave y % de claves
      misma sucursal entre archivos?                que siguen apareciendo
  C3. ¿Hay suficiente repetición de precios?     -> % de precios sin cambio entre fechas

Acepta los archivos tal como vienen:
  - del espejo de preciazo:  *.tar.zst  (sepa_<dia>.zip-repackaged.tar.zst)
  - del portal oficial:      *.zip      (zip con un zip por comercio adentro)
  - una carpeta ya descomprimida

Uso (pasá los archivos EN ORDEN DE FECHA; ideal: 2 días seguidos + 1 a 30 días o más):
  pip install pandas zstandard
  python verificar_condiciones.py dia1.tar.zst dia2.tar.zst dia30.tar.zst \
      --provincia AR-B --localidad "La Plata"

Filtros opcionales (recomendados para que entre en memoria):
  --provincia AR-B        código ISO de provincia (columna sucursales_provincia)
  --localidad "La Plata"  texto contenido en sucursales_localidad (sin importar mayúsculas)
  --comercio 10 11        solo esos id_comercio
Sin filtros procesa el país entero (~14 millones de filas por día): necesita mucha RAM.

Salida: un resumen en consola y un JSON (resultado_condiciones.json) para guardar en el repo.
"""
import argparse
import io
import json
import os
import sys
import tarfile
import zipfile
from collections import Counter

import pandas as pd

CLAVE = ["id_comercio", "id_bandera", "id_sucursal", "id_producto"]
PRECIOS = ["productos_precio_lista", "productos_precio_unitario_promo1",
           "productos_precio_unitario_promo2"]
COLS_PROD = CLAVE + ["productos_ean"] + PRECIOS
COLS_SUC = ["id_comercio", "id_bandera", "id_sucursal",
            "sucursales_provincia", "sucursales_localidad"]


# ----------------------------------------------------------------------------- lectura
def _iter_zip(zf, prefijo, interesa):
    """Recorre un zip abierto, entrando en zips anidados. Devuelve (nombre, archivo abierto)."""
    for info in zf.infolist():
        if info.is_dir():
            continue
        nombre = f"{prefijo}/{info.filename}"
        if info.filename.lower().endswith(".zip"):
            # un zip adentro de otro hay que tenerlo en memoria, pero comprimido pesa poco
            with zipfile.ZipFile(io.BytesIO(zf.read(info))) as interno:
                yield from _iter_zip(interno, nombre, interesa)
        elif interesa(nombre):
            with zf.open(info) as f:
                yield nombre, f


def iter_archivos(ruta, interesa):
    """Devuelve (nombre, archivo abierto en binario) de los CSV que interesan.
    Los archivos se leen de a pedazos: nunca se carga un CSV entero en memoria."""
    if os.path.isdir(ruta):
        for raiz, _, archivos in os.walk(ruta):
            for a in archivos:
                p = os.path.join(raiz, a)
                if a.lower().endswith(".zip"):
                    with zipfile.ZipFile(p) as z:
                        yield from _iter_zip(z, p, interesa)
                elif interesa(p):
                    with open(p, "rb") as f:
                        yield p, f
    elif ruta.endswith(".zst"):
        import zstandard
        with open(ruta, "rb") as fh:
            lector = zstandard.ZstdDecompressor().stream_reader(fh)
            with tarfile.open(fileobj=lector, mode="r|") as tar:
                for m in tar:
                    if not m.isfile():
                        continue
                    if m.name.lower().endswith(".zip"):
                        data = tar.extractfile(m).read()
                        with zipfile.ZipFile(io.BytesIO(data)) as z:
                            yield from _iter_zip(z, m.name, interesa)
                        del data
                    elif interesa(m.name):
                        yield m.name, tar.extractfile(m)
    elif ruta.lower().endswith(".zip"):
        with zipfile.ZipFile(ruta) as z:
            yield from _iter_zip(z, ruta, interesa)
    else:
        sys.exit(f"No sé leer {ruta}: esperaba .tar.zst, .zip o una carpeta")


def es(nombre_csv):
    return lambda n: os.path.basename(n).lower() == nombre_csv


class _SoloLectura(io.RawIOBase):
    """Envuelve el archivo comprimido para leerlo de corrido (sin saltar para atrás)."""
    def __init__(self, f):
        self._f = f

    def readable(self):
        return True

    def seekable(self):
        return False

    def readinto(self, b):
        datos = self._f.read(len(b))
        b[:len(datos)] = datos
        return len(datos)

    def close(self):
        # no cerramos el archivo de adentro: lo maneja quien lo abrió
        super().close()


def _abrir_csv(f, columnas, chunksize=None):
    """Lee el encabezado a mano (para detectar el separador) y arma el lector de pandas."""
    encabezado = f.readline().decode("utf-8-sig", errors="replace").strip("\r\n")
    sep = "|" if encabezado.count("|") >= encabezado.count(",") else ","
    nombres = [c.strip() for c in encabezado.split(sep)]
    usar = [c for c in nombres if c in columnas]
    texto = io.TextIOWrapper(_SoloLectura(f), encoding="utf-8", errors="replace", newline="")
    lector = pd.read_csv(texto, sep=sep, header=None, names=nombres, usecols=usar, dtype=str,
                         on_bad_lines="skip", keep_default_na=False, chunksize=chunksize,
                         engine="c", low_memory=True)
    return lector, sep


def _completar(df, columnas):
    for c in columnas:
        if c not in df.columns:
            df[c] = ""
    return df[columnas]


def leer_csv(f, columnas):
    """Para archivos chicos (comercio.csv, sucursales.csv)."""
    df, sep = _abrir_csv(f, columnas)
    return _completar(df, columnas), sep


def a_numero(s):
    s = s.str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


# ----------------------------------------------------------------------------- un día
def cargar_dia(ruta, args):
    info = {"archivo": os.path.basename(ruta),
            "tamano_mb": round(os.path.getsize(ruta) / 1e6, 1) if os.path.isfile(ruta) else None}

    # Pasada 1: comercio.csv (fecha real) y sucursales.csv (filtro geográfico)
    fechas, sucs, seps, fecha_com = Counter(), [], Counter(), {}
    for nombre, b in iter_archivos(ruta, lambda n: es("comercio.csv")(n) or es("sucursales.csv")(n)):
        if es("comercio.csv")(nombre):
            df, sep = leer_csv(b, ["id_comercio", "comercio_ultima_actualizacion"])
            fechas.update(df["comercio_ultima_actualizacion"].str[:10])
            for c, fe in zip(df["id_comercio"].str.strip(), df["comercio_ultima_actualizacion"].str[:10]):
                if c.isdigit() and fe:
                    fecha_com[c] = max(fe, fecha_com.get(c, ""))
        else:
            df, sep = leer_csv(b, COLS_SUC)
            sucs.append(df)
        seps[sep] += 1
    fechas.pop("", None)
    info["fecha_real"] = fechas.most_common(1)[0][0] if fechas else None
    info["fechas_distintas_en_comercio_csv"] = len(fechas)

    suc = pd.concat(sucs, ignore_index=True) if sucs else pd.DataFrame(columns=COLS_SUC)
    if args.provincia:
        suc = suc[suc["sucursales_provincia"].str.upper() == args.provincia.upper()]
    if args.localidad:
        suc = suc[suc["sucursales_localidad"].str.contains(args.localidad, case=False, na=False)]
    if args.comercio:
        suc = suc[suc["id_comercio"].isin(args.comercio)]
    filtrar = bool(args.provincia or args.localidad or args.comercio)
    def clave_suc(df):
        return (df["id_comercio"].str.strip() + "|" + df["id_bandera"].str.strip()
                + "|" + df["id_sucursal"].str.strip())

    claves_suc = set(clave_suc(suc))
    comercios_filtro = set(suc["id_comercio"].str.strip())

    # Pasada 2: productos.csv, de a 500.000 filas, filtrando cada pedazo apenas se lee
    partes, filas_crudas, rotas, saltados = [], 0, 0, 0
    for nombre, f in iter_archivos(ruta, es("productos.csv")):
        lector, sep = _abrir_csv(f, COLS_PROD, chunksize=500_000)
        seps[sep] += 1
        for i, df in enumerate(lector):
            df = _completar(df, COLS_PROD)
            filas_crudas += len(df)
            ok = df["id_producto"].str.strip().ne("") & df["id_comercio"].str.strip().str.isdigit()
            rotas += int((~ok).sum())      # p. ej. la línea final "Última actualización: ..."
            df = df[ok]
            if filtrar:
                # cada productos.csv es de un solo comercio: si no es de los que buscamos, se saltea
                if i == 0 and len(df) and not set(df["id_comercio"].str.strip()) & comercios_filtro:
                    saltados += 1
                    break
                df = df[clave_suc(df).isin(claves_suc)]
            if len(df):
                partes.append(df.copy())
    info["archivos_productos_salteados_por_filtro"] = saltados
    prod = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLS_PROD)
    for c in CLAVE:
        prod[c] = prod[c].str.strip()
    for c in PRECIOS:
        prod[c] = a_numero(prod[c])

    info.update({
        "separadores_vistos": dict(seps),
        "filas_productos_crudas": filas_crudas,
        "filas_descartadas_rotas": rotas,
        "filas_en_recorte": len(prod),
        "comercios_en_recorte": int(prod["id_comercio"].nunique()),
        "sucursales_en_recorte": int(prod[["id_comercio", "id_bandera", "id_sucursal"]]
                                     .drop_duplicates().shape[0]),
        "pct_con_ean": round(100 * (prod["productos_ean"].str.strip() == "1").mean(), 2) if len(prod) else None,
        "pct_precio_lista_invalido": round(100 * (prod["productos_precio_lista"].isna()
                                                  | (prod["productos_precio_lista"] <= 0)).mean(), 3) if len(prod) else None,
    })

    # Detalle por comercio: ¿actualizó ese día? ¿cuántos precios inválidos manda?
    invalido = prod["productos_precio_lista"].isna() | (prod["productos_precio_lista"] <= 0)
    por_com = {}
    for c, g in prod.assign(_inv=invalido).groupby("id_comercio"):
        por_com[c] = {"fecha_ultima_actualizacion": fecha_com.get(c),
                      "filas": int(len(g)),
                      "pct_precio_lista_invalido": round(100 * g["_inv"].mean(), 2)}
    info["por_comercio"] = por_com
    info["comercios_desactualizados"] = sorted(c for c, d in por_com.items()
                                               if d["fecha_ultima_actualizacion"] != info["fecha_real"])

    # C2a: duplicados por clave dentro del mismo día
    dup = prod.duplicated(CLAVE, keep=False)
    info["filas_con_clave_duplicada"] = int(dup.sum())
    info["pct_filas_clave_duplicada"] = round(100 * dup.mean(), 4) if len(prod) else None
    if dup.any():
        conflicto = (prod[dup].groupby(CLAVE)["productos_precio_lista"].nunique() > 1).sum()
        info["claves_duplicadas_con_precios_distintos"] = int(conflicto)
    # Para comparar entre días nos quedamos con una fila por clave (la primera)
    prod = prod.drop_duplicates(CLAVE, keep="first").set_index(CLAVE)
    return info, prod


# ----------------------------------------------------------------------------- comparar
def _pct(serie):
    return round(100 * float(serie.mean()), 2) if len(serie) else None


def comparar(a, b, info_a, info_b):
    nombre_a, nombre_b = info_a["fecha_real"] or info_a["archivo"], info_b["fecha_real"] or info_b["archivo"]
    comunes = a.index.intersection(b.index)
    r = {"de": nombre_a, "a": nombre_b,
         "claves_en_a": len(a), "claves_en_b": len(b), "claves_en_ambos": len(comunes),
         "pct_claves_de_a_que_siguen_en_b": round(100 * len(comunes) / len(a), 2) if len(a) else None}
    # por comercio: qué % de sus claves sigue apareciendo
    com_a = a.index.get_level_values("id_comercio")
    sigue = pd.Series(a.index.isin(comunes), index=com_a)
    r["pct_claves_que_siguen_por_comercio"] = {c: _pct(g) for c, g in sigue.groupby(level=0)}
    r["comercios_que_desaparecen"] = sorted(set(com_a) - set(b.index.get_level_values("id_comercio")))
    if not len(comunes):
        return r
    x, y = a.loc[comunes], b.loc[comunes]
    lx, ly = x["productos_precio_lista"], y["productos_precio_lista"]
    # Un precio vacío o en cero no es un precio: esas claves no cuentan como "cambio" ni como "sin cambio"
    valido = lx.notna() & ly.notna() & (lx > 0) & (ly > 0)
    r["pct_claves_con_precio_invalido_en_alguna_fecha"] = _pct(~valido)
    igual_lista = (lx == ly)
    igual_todo = igual_lista.copy()
    for c in PRECIOS[1:]:
        igual_todo &= (x[c] == y[c]) | (x[c].isna() & y[c].isna())
    r["pct_sin_cambio_precio_lista"] = _pct(igual_lista[valido])
    r["pct_sin_cambio_lista_y_promos"] = _pct(igual_todo[valido])
    # Comercios que no actualizaron en alguna de las dos fechas: su "sin cambio" puede ser falso
    viejos = set(info_a.get("comercios_desactualizados", [])) | set(info_b.get("comercios_desactualizados", []))
    com = pd.Series(x.index.get_level_values("id_comercio"), index=x.index)
    al_dia = valido & ~com.isin(viejos)
    r["comercios_desactualizados_en_alguna_fecha"] = sorted(viejos)
    r["pct_sin_cambio_precio_lista_solo_comercios_al_dia"] = _pct(igual_lista[al_dia])
    r["pct_sin_cambio_precio_lista_por_comercio"] = {
        c: _pct(g) for c, g in igual_lista[valido].groupby(com[valido])}
    cambio = (ly / lx - 1)[valido & ~igual_lista]
    if len(cambio):
        r["cambio_lista_mediana_pct"] = round(100 * float(cambio.median()), 2)
        r["cambios_mayores_al_50pct_o_bajas_mayores_al_33pct"] = int(((cambio > 0.5) | (cambio < -0.33)).sum())
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivos", nargs="+", help="archivos SEPA en orden de fecha")
    ap.add_argument("--provincia")
    ap.add_argument("--localidad")
    ap.add_argument("--comercio", nargs="*")
    ap.add_argument("--salida", default="resultado_condiciones.json")
    args = ap.parse_args()
    if len(args.archivos) < 2:
        sys.exit("Pasá al menos 2 archivos (ideal 3: dos días seguidos y uno a 30 días o más).")

    dias, tablas = [], []
    for ruta in args.archivos:
        print(f"Leyendo {ruta} ...", flush=True)
        info, tabla = cargar_dia(ruta, args)
        dias.append(info)
        tablas.append(tabla)
        print(f"  fecha real {info['fecha_real']} · {info['filas_en_recorte']:,} filas en el recorte · "
              f"{info['pct_filas_clave_duplicada']}% filas con clave duplicada", flush=True)

    pares = [comparar(tablas[i], tablas[i + 1], dias[i], dias[i + 1]) for i in range(len(tablas) - 1)]
    if len(tablas) > 2:
        pares.append(comparar(tablas[0], tablas[-1], dias[0], dias[-1]))

    # ------------------------------------------------------------------ veredicto
    fechas = [d["fecha_real"] for d in dias]
    c1 = bool(len(set(f for f in fechas if f)) == len(fechas) and all(d["filas_en_recorte"] > 0 for d in dias))
    c2 = bool(all((d["pct_filas_clave_duplicada"] or 0) < 0.1 for d in dias)
              and (pares[0]["pct_claves_de_a_que_siguen_en_b"] or 0) >= 90)
    p_sin = pares[0].get("pct_sin_cambio_precio_lista")
    c3 = bool(p_sin is not None and p_sin >= 80)

    def estimar(pct_sin, n=90):
        if pct_sin is None:
            return None
        p = 1 - pct_sin / 100   # proporción de claves que cambian por día (aprox., con días seguidos)
        return {"p_cambio_diario": round(p, 4),
                "filas_diaria_sobre_filas_cambios_en_90_dias": round(n / (1 + p * (n - 1)), 1)}

    estimacion = {"supuesto": "los 2 primeros archivos son días seguidos",
                  "todos_los_comercios": estimar(p_sin),
                  "solo_comercios_al_dia": estimar(pares[0].get("pct_sin_cambio_precio_lista_solo_comercios_al_dia"))}

    resultado = {"dias": dias, "comparaciones": pares, "estimacion_ahorro": estimacion,
                 "veredicto": {"C1_fechas_distintas": c1, "C2_identificacion_estable": c2,
                               "C3_repeticion_suficiente": c3},
                 "umbrales": {"C2": "duplicados < 0,1% y >= 90% de claves siguen al día siguiente",
                              "C3": ">= 80% sin cambio de precio de lista entre días seguidos"},
                 "filtros": {"provincia": args.provincia, "localidad": args.localidad, "comercio": args.comercio}}
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)

    print("\n=== Calidad por día ===")
    for d in dias:
        print(f"{d['fecha_real']}: {d['comercios_en_recorte']} comercios · precio de lista inválido "
              f"{d['pct_precio_lista_invalido']}% · comercios sin actualizar ese día: {d['comercios_desactualizados'] or 'ninguno'}")
    print("\n=== Comparaciones entre fechas ===")
    for r in pares:
        print(f"{r['de']} -> {r['a']}: siguen {r['pct_claves_de_a_que_siguen_en_b']}% de las claves · "
              f"sin cambio lista {r.get('pct_sin_cambio_precio_lista')}% "
              f"(solo comercios al día: {r.get('pct_sin_cambio_precio_lista_solo_comercios_al_dia')}%) · "
              f"lista+promos {r.get('pct_sin_cambio_lista_y_promos')}%")
        if r["comercios_que_desaparecen"]:
            print(f"   comercios que no aparecen en {r['a']}: {r['comercios_que_desaparecen']}")
    for k, v in estimacion.items():
        if isinstance(v, dict):
            print(f"\nEstimación ({k}): en 90 días la tabla diaria tendría ~{v['filas_diaria_sobre_filas_cambios_en_90_dias']}x "
                  f"más filas que la de cambios.")
    print("(Las estimaciones solo valen si los 2 primeros archivos son días seguidos.)")
    print("\n=== Veredicto ===")
    for k, v in resultado["veredicto"].items():
        print(f"{k}: {'PASA' if v else 'NO PASA / revisar'}")
    if len(set(fechas)) < len(fechas):
        print("Ojo: hay archivos con la misma fecha real. Revisá que no hayas bajado el mismo día dos veces.")
    print(f"\nDetalle completo en {args.salida}")


if __name__ == "__main__":
    main()

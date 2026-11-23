#!/usr/bin/env python3
"""
analizar_ventana.py — T13: control de calidad de la ventana de 90 días (recorte de La Plata).

Lee lo que dejó descargar_sepa.py en <carpeta>/recorte y responde, sin cargar nada en PostgreSQL:

  1. Versiones duplicadas: para los días con __v1/__v2, cuál se usa y por qué.
  2. Fecha real de cada comercio: con qué atraso publica cada uno y quiénes están "congelados".
  3. Reglas de exclusión (de la sección 3 del plan):
       - congelado: atraso mediano de más de 7 días
       - precios inválidos: más del 50% de precios de lista vacíos o en cero
       - cobertura: menos del 90% de los días de la ventana con datos propios
  4. Cada día: sucursales, filas y precios inválidos de los comercios incluidos.
  5. Primer número real del experimento: cuántos precios cambian por día (p) y cuántas filas
     tendría cada modelo, aplicando la política de ausencias (un día sin dato corta el tramo).
     Se calcula para 30, 60 y 90 días y se compara con la fórmula K·(1 + p·(N − 1)).

Uso:
  python analizar_ventana.py --carpeta C:\\sepa-crudos --desde 2025-02-01 --hasta 2025-05-01

Escribe en <carpeta>/t13: reporte.md (para pegar en el doc) y varios CSV con el detalle.
Necesita pandas (ya lo tenés instalado).
"""
import argparse
import csv
import datetime as dt
import glob
import os
import re
import sys

import pandas as pd

ATRASO_MAX_DIAS = 7
INVALIDOS_MAX = 0.50
COBERTURA_MIN = 0.90


def fecha_de(texto):
    """Fecha (date) a partir de comercio_ultima_actualizacion, sea ISO o dd/mm/aaaa."""
    t = str(texto).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", t):
        return dt.date.fromisoformat(t[:10])
    try:
        return pd.to_datetime(t, dayfirst=True).date()
    except (ValueError, TypeError):
        return None


def md(df, index=False):
    """Tabla en formato markdown sin depender de librerías extra."""
    if index:
        df = df.reset_index()
    cols = [str(c) for c in df.columns]
    filas = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for r in df.itertuples(index=False):
        filas.append("| " + " | ".join("" if (isinstance(v, float) and v != v) else str(v) for v in r) + " |")
    return "\n".join(filas)


def listar_archivos(carpeta_recorte, desde, hasta):
    archivos = []
    for ruta in glob.glob(os.path.join(carpeta_recorte, "*_productos.csv.gz")):
        base = os.path.basename(ruta).replace("_productos.csv.gz", "")
        m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:__v(\d+))?$", base)
        if not m:
            continue
        f = dt.date.fromisoformat(m.group(1))
        if desde <= f <= hasta:
            archivos.append({"base": base, "fecha_archivo": f, "version": int(m.group(2) or 1)})
    return sorted(archivos, key=lambda a: (a["fecha_archivo"], a["version"]))


def leer_comercios(carpeta_recorte, base):
    ruta = os.path.join(carpeta_recorte, f"{base}_comercios.csv.gz")
    df = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    df["fecha_propia"] = df["comercio_ultima_actualizacion"].map(fecha_de)
    # un comercio puede tener varias banderas: nos quedamos con la fecha más nueva y un nombre
    g = df.groupby("id_comercio").agg(fecha_propia=("fecha_propia", lambda s: max((x for x in s if x), default=None)),
                                      nombre=("comercio_bandera_nombre", "first"))
    return g.reset_index()


def leer_productos(carpeta_recorte, base):
    ruta = os.path.join(carpeta_recorte, f"{base}_productos.csv.gz")
    df = pd.read_csv(ruta, dtype=str, keep_default_na=False,
                     usecols=["id_comercio", "id_bandera", "id_sucursal", "id_producto",
                              "productos_precio_lista"])
    precio = pd.to_numeric(df["productos_precio_lista"].str.replace(",", ".", regex=False), errors="coerce")
    df["precio"] = precio.where(precio > 0)          # vacío, texto o <= 0 -> inválido (NaN)
    df = df.drop(columns="productos_precio_lista")
    for c in ("id_comercio", "id_bandera", "id_sucursal", "id_producto"):
        df[c] = df[c].astype("category")
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carpeta", required=True, help="la misma carpeta de descargar_sepa.py")
    ap.add_argument("--desde", required=True)
    ap.add_argument("--hasta", required=True)
    args = ap.parse_args()
    desde, hasta = dt.date.fromisoformat(args.desde), dt.date.fromisoformat(args.hasta)
    dias = [desde + dt.timedelta(i) for i in range((hasta - desde).days + 1)]
    carpeta_recorte = os.path.join(args.carpeta, "recorte")
    salida = os.path.join(args.carpeta, "t13")
    os.makedirs(salida, exist_ok=True)

    archivos = listar_archivos(carpeta_recorte, desde, hasta)
    if not archivos:
        sys.exit(f"No encontré archivos de recorte en {carpeta_recorte} para esa ventana")
    print(f"{len(archivos)} archivos de recorte en la ventana ({len(dias)} días)")

    # ------------------------------------------------------------ 1) comercios y versiones
    com_por_archivo = []
    for a in archivos:
        c = leer_comercios(carpeta_recorte, a["base"])
        c["base"], c["fecha_archivo"], c["version"] = a["base"], a["fecha_archivo"], a["version"]
        com_por_archivo.append(c)
    com = pd.concat(com_por_archivo, ignore_index=True)
    com["atraso"] = [(fa - fp).days if fp else None for fa, fp in zip(com["fecha_archivo"], com["fecha_propia"])]

    elegidas, filas_versiones = {}, []
    for f, g in com.groupby("fecha_archivo"):
        versiones = sorted(g["version"].unique())
        if len(versiones) == 1:
            elegidas[f] = versiones[0]
            continue
        resumen = []
        for v in versiones:
            gv = g[g["version"] == v]
            al_dia = int((gv["atraso"] == 0).sum())
            resumen.append((v, al_dia, len(gv)))
            filas_versiones.append({"fecha": f, "version": v, "comercios": len(gv), "comercios_al_dia": al_dia,
                                    "fechas_propias": " ".join(sorted({str(x) for x in gv["fecha_propia"]}))})
        # regla: la versión con más comercios al día; si empatan, la primera que vio el espejo
        elegidas[f] = sorted(resumen, key=lambda r: (-r[1], r[0]))[0][0]
    for r in filas_versiones:
        r["elegida"] = "sí" if elegidas[r["fecha"]] == r["version"] else "no"
    archivos = [a for a in archivos if elegidas[a["fecha_archivo"]] == a["version"]]
    com = com[[elegidas[f] == v for f, v in zip(com["fecha_archivo"], com["version"])]]

    # ------------------------------------------------------------ 2) asignar fecha propia
    # Cada paquete (comercio, fecha propia) se usa una sola vez: la primera vez que aparece.
    com = com.sort_values(["fecha_archivo"])
    com["repetido"] = com.duplicated(["id_comercio", "fecha_propia"], keep="first")
    asignacion = com[~com["repetido"] & com["fecha_propia"].notna()]
    asignacion = asignacion[asignacion["fecha_propia"].between(desde, hasta)]
    usar = {(r.base, r.id_comercio): r.fecha_propia for r in asignacion.itertuples()}

    # ------------------------------------------------------------ 3) productos
    obs, por_dia_crudo = [], []
    for i, a in enumerate(archivos, 1):
        print(f"\r  leyendo productos {i}/{len(archivos)}   ", end="", flush=True)
        p = leer_productos(carpeta_recorte, a["base"])
        p["fecha_obs"] = [usar.get((a["base"], c)) for c in p["id_comercio"].astype(str)]
        por_dia_crudo.append(p.groupby("id_comercio", observed=True).agg(
            filas=("precio", "size"), invalidos=("precio", lambda s: int(s.isna().sum())),
            sucursales=("id_sucursal", "nunique")).reset_index().assign(base=a["base"], fecha_archivo=a["fecha_archivo"]))
        p = p[p["fecha_obs"].notna()]
        obs.append(p)
    print()
    obs = pd.concat(obs, ignore_index=True)
    for c in ("id_comercio", "id_bandera", "id_sucursal", "id_producto"):
        obs[c] = obs[c].astype(str).astype("category")
    crudo = pd.concat(por_dia_crudo, ignore_index=True)

    # ------------------------------------------------------------ 4) reglas de exclusión por comercio
    filas_com = []
    nombres = com.groupby("id_comercio")["nombre"].first()
    for c, g in com.groupby("id_comercio"):
        atrasos = g["atraso"].dropna()
        cr = crudo[crudo["id_comercio"].astype(str) == c]
        filas_tot = int(cr["filas"].sum())
        inval = (cr["invalidos"].sum() / filas_tot) if filas_tot else None
        dias_obs = obs.loc[obs["id_comercio"].astype(str) == c, "fecha_obs"].nunique()
        cobertura = dias_obs / len(dias)
        motivos = []
        if len(atrasos) and atrasos.median() > ATRASO_MAX_DIAS:
            motivos.append(f"congelado (atraso mediano {int(atrasos.median())} días)")
        if filas_tot == 0:
            motivos.append("sin productos en La Plata")
        elif inval is not None and inval > INVALIDOS_MAX:
            motivos.append(f"precios inválidos {inval:.0%}")
        if cobertura < COBERTURA_MIN and filas_tot:
            motivos.append(f"cobertura {cobertura:.0%}")
        filas_com.append({
            "id_comercio": c, "nombre": nombres.get(c, ""),
            "atraso_mediano_dias": None if not len(atrasos) else float(atrasos.median()),
            "dias_con_datos_propios": dias_obs, "cobertura": round(cobertura, 3),
            "filas_promedio_por_archivo": round(filas_tot / max(len(cr), 1)),
            "sucursales_max": int(cr["sucursales"].max()) if len(cr) else 0,
            "pct_precios_invalidos": None if inval is None else round(100 * inval, 2),
            "decision": "excluir" if motivos else "incluir", "motivo": "; ".join(motivos)})
    tabla_com = pd.DataFrame(filas_com).sort_values(["decision", "filas_promedio_por_archivo"], ascending=[False, False])
    incluidos = set(tabla_com.loc[tabla_com["decision"] == "incluir", "id_comercio"])

    # ------------------------------------------------------------ 5) observaciones válidas de los incluidos
    o = obs[obs["id_comercio"].astype(str).isin(incluidos)].copy()
    invalidas_incluidos = int(o["precio"].isna().sum())
    o = o[o["precio"].notna()]
    o["clave"] = o.groupby(["id_comercio", "id_bandera", "id_sucursal", "id_producto"], observed=True).ngroup()
    o["sucursal"] = o.groupby(["id_comercio", "id_bandera", "id_sucursal"], observed=True).ngroup()
    o["fecha_obs"] = pd.to_datetime(o["fecha_obs"])
    dup_clave_dia = int(o.duplicated(["clave", "fecha_obs"]).sum())
    o = o.drop_duplicates(["clave", "fecha_obs"]).sort_values(["clave", "fecha_obs"])

    # por día
    tabla_dias = (o.groupby("fecha_obs").agg(filas=("clave", "size"),
                                              sucursales=("sucursal", "nunique"),
                                              comercios=("id_comercio", lambda s: s.nunique()))
                  .reindex(pd.to_datetime(dias), fill_value=0))
    tabla_dias.index.name = "fecha"

    # ------------------------------------------------------------ 6) cambios y filas de cada modelo
    def medir(sub, n_dias):
        sub = sub.sort_values(["clave", "fecha_obs"])
        misma = sub["clave"].eq(sub["clave"].shift())
        seguido = misma & (sub["fecha_obs"] - sub["fecha_obs"].shift()).dt.days.eq(1)
        cambio = seguido & sub["precio"].ne(sub["precio"].shift())
        p = cambio.sum() / seguido.sum() if seguido.sum() else float("nan")
        inicio = ~misma
        corte_hueco = misma & ~seguido
        filas_b = int(inicio.sum() + corte_hueco.sum() + cambio.sum())
        k = int(sub["clave"].nunique())
        teorico = k * (1 + p * (n_dias - 1))
        return {"dias": n_dias, "claves_K": k, "filas_A": len(sub), "filas_B": filas_b,
                "tramos_por_inicio": int(inicio.sum()), "tramos_por_cambio": int(cambio.sum()),
                "tramos_por_hueco": int(corte_hueco.sum()), "p_cambio_diario": round(float(p), 5),
                "razon_A_sobre_B": round(len(sub) / filas_b, 1) if filas_b else None,
                "filas_B_teoricas": round(teorico), "diferencia_vs_formula_pct": round(100 * (filas_b - teorico) / teorico, 1),
                "_seguido": seguido, "_cambio": cambio}

    escalas = []
    for n in (30, 60, len(dias)):
        tope = pd.Timestamp(desde + dt.timedelta(days=n - 1))
        r = medir(o[o["fecha_obs"] <= tope], n)
        escalas.append({k: v for k, v in r.items() if not k.startswith("_")})
        if n == len(dias):
            completo = r
    tabla_escalas = pd.DataFrame(escalas)

    sub = o.sort_values(["clave", "fecha_obs"])
    seg, cam = completo["_seguido"], completo["_cambio"]
    p_por_dia = (pd.DataFrame({"fecha": sub["fecha_obs"], "seguido": seg, "cambio": cam})
                 .groupby("fecha").agg(pares=("seguido", "sum"), cambios=("cambio", "sum")))
    p_por_dia["p"] = (p_por_dia["cambios"] / p_por_dia["pares"]).round(5)
    p_por_comercio = (pd.DataFrame({"id_comercio": sub["id_comercio"].astype(str), "seguido": seg, "cambio": cam})
                      .groupby("id_comercio").agg(pares=("seguido", "sum"), cambios=("cambio", "sum")))
    p_por_comercio["p"] = (p_por_comercio["cambios"] / p_por_comercio["pares"]).round(5)
    p_por_comercio = p_por_comercio.join(nombres).sort_values("p", ascending=False)

    # ------------------------------------------------------------ 7) salida
    tabla_com.to_csv(os.path.join(salida, "comercios.csv"), index=False)
    tabla_dias.to_csv(os.path.join(salida, "dias.csv"))
    tabla_escalas.to_csv(os.path.join(salida, "escalas.csv"), index=False)
    p_por_dia.to_csv(os.path.join(salida, "cambios_por_dia.csv"))
    p_por_comercio.to_csv(os.path.join(salida, "cambios_por_comercio.csv"))
    pd.DataFrame(filas_versiones).to_csv(os.path.join(salida, "versiones_duplicadas.csv"), index=False)
    com[["base", "fecha_archivo", "id_comercio", "fecha_propia", "atraso", "repetido"]].to_csv(
        os.path.join(salida, "asignacion_paquetes.csv"), index=False)

    dias_sin = [str(d.date()) for d, f in tabla_dias["filas"].items() if f == 0]
    suc = tabla_dias["sucursales"]
    bajos = tabla_dias[suc < suc.median() * 0.8]
    ventana_ok = not dias_sin and len(incluidos) > 0

    lineas = [
        f"# T13 · Calidad de la ventana {desde} a {hasta}",
        "",
        f"Generado el {dt.datetime.now():%Y-%m-%d %H:%M} con analizar_ventana.py.",
        "",
        "## Veredicto",
        "",
        f"- Ventana: **{'confirmada' if ventana_ok else 'NO confirmada'}**. "
        f"Días sin ningún dato de los comercios incluidos: {len(dias_sin)} {dias_sin if dias_sin else ''}",
        f"- Comercios incluidos: {len(incluidos)} de {len(tabla_com)}.",
        f"- Observaciones válidas (filas de A, 90 días): {len(o):,}. Precios inválidos descartados en incluidos: "
        f"{invalidas_incluidos:,}. Claves repetidas en un mismo día: {dup_clave_dia:,}.",
        f"- Proporción de precios que cambian por día (p): **{completo['p_cambio_diario']:.2%}**.",
        f"- Filas A / filas B a 90 días: **{completo['razon_A_sobre_B']}** veces.",
        "",
        "## Versiones duplicadas",
        "",
        md(pd.DataFrame(filas_versiones)) if filas_versiones else "No hay.",
        "",
        "## Comercios",
        "",
        md(tabla_com),
        "",
        "## Escalas (30, 60 y 90 días)",
        "",
        md(tabla_escalas),
        "",
        "## p por comercio (incluidos)",
        "",
        md(p_por_comercio.reset_index()),
        "",
        "## Días con pocas sucursales (menos del 80% de la mediana)",
        "",
        md(bajos.reset_index()) if len(bajos) else "Ninguno.",
        "",
        f"Mediana de sucursales por día: {suc.median():.0f} (mín. {suc.min()}, máx. {suc.max()}).",
    ]
    with open(os.path.join(salida, "reporte.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")

    print("\n".join(lineas[4:11]))
    print(f"\nComercios:\n{tabla_com[['id_comercio', 'nombre', 'cobertura', 'pct_precios_invalidos', 'decision', 'motivo']].to_string(index=False)}")
    print(f"\nEscalas:\n{tabla_escalas[['dias', 'claves_K', 'filas_A', 'filas_B', 'p_cambio_diario', 'razon_A_sobre_B', 'diferencia_vs_formula_pct']].to_string(index=False)}")
    print(f"\nReporte completo: {os.path.join(salida, 'reporte.md')}")


if __name__ == "__main__":
    main()

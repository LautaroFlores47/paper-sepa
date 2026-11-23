#!/usr/bin/env python3
"""
descargar_sepa.py — T11: descarga reproducible de los archivos SEPA del espejo de preciazo.

Qué hace:
  1. Baja el índice del espejo (index.json de catdevnull/sepa-precios-metadata) y guarda una copia.
  2. Para cada día de la ventana, baja los archivos .tar.zst que no estén marcados con ❌.
     Si un día tiene más de una versión (pasa: el espejo a veces guardó el mismo día dos veces),
     baja todas y las marca en el manifiesto. Cuál se usa se decide después (T13), mirando la
     fecha propia de cada comercio dentro del archivo.
  3. Si se corta, se puede volver a correr: retoma donde quedó y no vuelve a bajar lo que ya está completo.
  4. Escribe manifest.csv con fecha, archivo, URL, tamaño, SHA-256 y advertencias.
     Ese manifiesto es lo que va al repo: con él cualquiera puede verificar que usó los mismos archivos.

Uso:
  python descargar_sepa.py --desde 2025-02-01 --hasta 2025-05-01 --carpeta C:\\sepa-crudos
  python descargar_sepa.py --desde 2025-02-01 --hasta 2025-05-01 --solo-listar   (no baja nada)

Modo recorte (para compus con poco disco):
  python descargar_sepa.py --desde 2025-02-01 --hasta 2025-05-01 --carpeta C:\\sepa-crudos \
      --provincia AR-B --localidad "La Plata" --borrar-crudos
  Después de bajar cada día guarda SOLO las filas de esa localidad en la subcarpeta "recorte"
  (comercios, sucursales y productos, en CSV comprimido) y borra el archivo grande.
  No se aplica ninguna limpieza: el recorte trae todo lo que vino, tal cual. La limpieza es la T14.
  El manifiesto conserva URL y SHA-256 del archivo original, así que se puede volver a bajar.

Sin --localidad/--provincia no necesita librerías extra. Con recorte necesita: pip install pandas zstandard
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import sys
import tarfile
import time
import urllib.request
import zipfile

INDICE_URL = "https://raw.githubusercontent.com/catdevnull/sepa-precios-metadata/main/index.json"
BLOQUE = 1024 * 1024  # 1 MB


def fechas(desde, hasta):
    d = dt.date.fromisoformat(desde)
    h = dt.date.fromisoformat(hasta)
    if h < d:
        sys.exit("--hasta tiene que ser igual o posterior a --desde")
    while d <= h:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def bajar_texto(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def tamano_remoto(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        largo = r.headers.get("Content-Length")
        return int(largo) if largo else None


def sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(BLOQUE), b""):
            h.update(bloque)
    return h.hexdigest()


def descargar(url, destino, reintentos=5):
    """Baja url a destino. Retoma descargas cortadas (usa un .parcial) y reintenta si falla la red."""
    esperado = tamano_remoto(url)
    if os.path.exists(destino) and (esperado is None or os.path.getsize(destino) == esperado):
        return "ya estaba"
    parcial = destino + ".parcial"
    for intento in range(1, reintentos + 1):
        try:
            ya = os.path.getsize(parcial) if os.path.exists(parcial) else 0
            req = urllib.request.Request(url)
            if ya:
                req.add_header("Range", f"bytes={ya}-")
            with urllib.request.urlopen(req, timeout=120) as r:
                if ya and r.status != 206:      # el servidor no aceptó retomar: empezamos de cero
                    ya = 0
                modo = "ab" if ya else "wb"
                total = esperado or 0
                hecho, t0 = ya, time.time()
                with open(parcial, modo) as f:
                    while True:
                        bloque = r.read(BLOQUE)
                        if not bloque:
                            break
                        f.write(bloque)
                        hecho += len(bloque)
                        if total:
                            vel = (hecho - ya) / max(time.time() - t0, 0.1) / 1e6
                            print(f"\r    {hecho / 1e6:7.1f} / {total / 1e6:.1f} MB  ({vel:.1f} MB/s)",
                                  end="", flush=True)
            print()
            if esperado is not None and os.path.getsize(parcial) != esperado:
                raise IOError(f"tamaño distinto: {os.path.getsize(parcial)} vs {esperado}")
            os.replace(parcial, destino)
            return "bajado"
        except Exception as e:                    # noqa: BLE001 — cualquier falla de red se reintenta
            print(f"\n    intento {intento}/{reintentos} falló: {e}")
            time.sleep(min(60, 5 * intento))
    return "FALLÓ"


# ----------------------------------------------------------------------------- recorte
COLS_COM = ["id_comercio", "id_bandera", "comercio_cuit", "comercio_razon_social",
            "comercio_bandera_nombre", "comercio_ultima_actualizacion", "comercio_version_sepa"]
COLS_SUC = ["id_comercio", "id_bandera", "id_sucursal", "sucursales_nombre", "sucursales_tipo",
            "sucursales_calle", "sucursales_numero", "sucursales_latitud", "sucursales_longitud",
            "sucursales_codigo_postal", "sucursales_localidad", "sucursales_provincia"]
COLS_PROD = ["id_comercio", "id_bandera", "id_sucursal", "id_producto", "productos_ean",
             "productos_descripcion", "productos_cantidad_presentacion",
             "productos_unidad_medida_presentacion", "productos_marca", "productos_precio_lista",
             "productos_precio_referencia", "productos_cantidad_referencia",
             "productos_unidad_medida_referencia", "productos_precio_unitario_promo1",
             "productos_leyenda_promo1", "productos_precio_unitario_promo2", "productos_leyenda_promo2"]


def _iter_zip(zf, prefijo, interesa):
    for info in zf.infolist():
        if info.is_dir():
            continue
        nombre = f"{prefijo}/{info.filename}"
        if info.filename.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(info))) as interno:
                yield from _iter_zip(interno, nombre, interesa)
        elif interesa(nombre):
            with zf.open(info) as f:
                yield nombre, f


def _iter_archivos(ruta, interesa):
    """(nombre, archivo abierto) de los CSV que interesan dentro del .tar.zst, leyendo de corrido."""
    import zstandard
    with open(ruta, "rb") as fh:
        lector = zstandard.ZstdDecompressor().stream_reader(fh)
        with tarfile.open(fileobj=lector, mode="r|") as tar:
            for m in tar:
                if not m.isfile():
                    continue
                if m.name.lower().endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(tar.extractfile(m).read())) as z:
                        yield from _iter_zip(z, m.name, interesa)
                elif interesa(m.name):
                    yield m.name, tar.extractfile(m)


class _SoloLectura(io.RawIOBase):
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


def _es(nombre):
    return lambda n: os.path.basename(n).lower() == nombre


def _filas(f, columnas, stats):
    """Lee un CSV de SEPA fila por fila, sin ser estricto con la cantidad de columnas.
    Devuelve dicts con las columnas pedidas. Filas cortas se completan con vacío; filas largas
    (por ejemplo, una descripción con el separador adentro) se descartan. Todo queda contado en stats."""
    texto = io.TextIOWrapper(_SoloLectura(f), encoding="utf-8-sig", errors="replace", newline="")
    encabezado = texto.readline().strip("\r\n")
    if not encabezado:
        return
    sep = "|" if encabezado.count("|") >= encabezado.count(",") else ","
    nombres = [c.strip().strip('"') for c in encabezado.split(sep)]
    pos = {c: nombres.index(c) for c in columnas if c in nombres}
    faltan = [c for c in columnas if c not in pos]
    if faltan:
        stats["columnas_faltantes"] |= set(faltan)
    n = len(nombres)
    for fila in csv.reader(texto, delimiter=sep):
        if not fila or not fila[0].strip().isdigit():     # vacías y la línea final "Última actualización"
            stats["filas_descartadas"] += 1
            continue
        if len(fila) > n:
            stats["filas_largas_descartadas"] += 1
            continue
        if len(fila) < n:
            stats["filas_cortas_completadas"] += 1
            fila = fila + [""] * (n - len(fila))
        yield {c: (fila[pos[c]].strip() if c in pos else "") for c in columnas}


def _escribir(ruta, columnas, filas):
    import gzip
    cuenta = 0
    with gzip.open(ruta, "wt", encoding="utf-8", newline="") as salida:
        w = csv.DictWriter(salida, fieldnames=columnas)
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
            cuenta += 1
    return cuenta


def recortar(ruta, carpeta_recorte, base, provincia, localidad):
    """Guarda en carpeta_recorte/<base>_{comercios,sucursales,productos}.csv.gz solo la zona pedida."""
    csv.field_size_limit(10_000_000)
    os.makedirs(carpeta_recorte, exist_ok=True)
    stats = {"filas_descartadas": 0, "filas_largas_descartadas": 0, "filas_cortas_completadas": 0,
             "columnas_faltantes": set()}

    # Pasada 1: comercios y sucursales (archivos chicos)
    coms, sucs = [], []
    for nombre, f in _iter_archivos(ruta, lambda n: _es("comercio.csv")(n) or _es("sucursales.csv")(n)):
        if _es("comercio.csv")(nombre):
            coms += list(_filas(f, COLS_COM, stats))
        else:
            sucs += list(_filas(f, COLS_SUC, stats))
    if provincia:
        sucs = [s for s in sucs if s["sucursales_provincia"].upper() == provincia.upper()]
    if localidad:
        sucs = [s for s in sucs if localidad.lower() in s["sucursales_localidad"].lower()]
    clave = lambda d: f"{d['id_comercio']}|{d['id_bandera']}|{d['id_sucursal']}"   # noqa: E731
    claves = {clave(s) for s in sucs}
    comercios_zona = {s["id_comercio"] for s in sucs}
    coms = [c for c in coms if c["id_comercio"] in comercios_zona]

    destino = {k: os.path.join(carpeta_recorte, f"{base}_{k}.csv.gz")
               for k in ("comercios", "sucursales", "productos")}
    tmp = {k: v + ".tmp" for k, v in destino.items()}
    _escribir(tmp["comercios"], COLS_COM, coms)
    _escribir(tmp["sucursales"], COLS_SUC, sucs)

    # Pasada 2: productos, fila por fila, filtrando apenas se lee
    def productos_de_la_zona():
        for _, f in _iter_archivos(ruta, _es("productos.csv")):
            for j, fila in enumerate(_filas(f, COLS_PROD, stats)):
                # cada productos.csv es de un solo comercio: si no tiene sucursales en la zona, se saltea
                if j == 0 and fila["id_comercio"] not in comercios_zona:
                    break
                if clave(fila) in claves:
                    yield fila

    filas = _escribir(tmp["productos"], COLS_PROD, productos_de_la_zona())
    for k in destino:
        os.replace(tmp[k], destino[k])   # recién al final: un recorte a medias nunca queda con el nombre bueno
    stats["columnas_faltantes"] = sorted(stats["columnas_faltantes"])
    return {"comercios": len(coms), "sucursales": len(sucs), "filas_productos": filas, **stats}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", required=True, help="primer día, AAAA-MM-DD")
    ap.add_argument("--hasta", required=True, help="último día, AAAA-MM-DD (incluido)")
    ap.add_argument("--carpeta", default="sepa-crudos", help="dónde guardar (fuera del repo)")
    ap.add_argument("--solo-listar", action="store_true", help="muestra qué bajaría, sin bajar")
    ap.add_argument("--provincia", help="recorte: código de provincia, p. ej. AR-B")
    ap.add_argument("--localidad", help='recorte: texto de la localidad, p. ej. "La Plata"')
    ap.add_argument("--borrar-crudos", action="store_true",
                    help="con recorte: borra cada archivo grande después de recortarlo")
    ap.add_argument("--indice-url", default=INDICE_URL, help=argparse.SUPPRESS)
    args = ap.parse_args()
    recorte = bool(args.provincia or args.localidad)
    if args.borrar_crudos and not recorte:
        sys.exit("--borrar-crudos solo se puede usar junto con --provincia y/o --localidad")
    if recorte:
        try:
            import zstandard  # noqa: F401
        except ImportError:
            sys.exit("El modo recorte necesita: python -m pip install zstandard")
    carpeta_recorte = os.path.join(args.carpeta, "recorte")

    os.makedirs(args.carpeta, exist_ok=True)
    print("Bajando el índice del espejo...")
    crudo = bajar_texto(args.indice_url)
    indice = json.loads(crudo)
    ruta_indice = os.path.join(args.carpeta, "index.json")
    with open(ruta_indice, "wb") as f:
        f.write(crudo)
    sha_indice = hashlib.sha256(crudo).hexdigest()
    print(f"  índice guardado en {ruta_indice} (SHA-256 {sha_indice[:12]}...)")

    # 1) Plan: qué archivos corresponden a cada día
    plan, faltan, descartados = [], [], []
    for fecha in fechas(args.desde, args.hasta):
        entradas = [e for e in indice.get(fecha, []) if e.get("link")]
        validas = [e for e in entradas if "❌" not in (e.get("warnings") or "")]
        descartados += [(fecha, e["name"], e["warnings"]) for e in entradas if e not in validas]
        if not validas:
            faltan.append(fecha)
            continue
        validas.sort(key=lambda e: e.get("firstSeenAt", ""))
        for n, e in enumerate(validas, 1):
            sufijo = "" if len(validas) == 1 else f"__v{n}"
            plan.append({"fecha": fecha, "version": f"{n}/{len(validas)}",
                         "archivo": f"{fecha}{sufijo}.tar.zst", "url": e["link"],
                         "firstSeenAt": e.get("firstSeenAt", ""), "advertencia": e.get("warnings", "")})

    dias = len(list(fechas(args.desde, args.hasta)))
    dobles = sorted({p["fecha"] for p in plan if p["version"] != "1/1"})
    print(f"\nVentana: {args.desde} a {args.hasta} ({dias} días)")
    print(f"  archivos a bajar: {len(plan)}")
    print(f"  días SIN archivo válido: {len(faltan)} {faltan if faltan else ''}")
    print(f"  días con más de una versión: {len(dobles)} {dobles if dobles else ''}")
    if descartados:
        print(f"  archivos descartados por ❌: {len(descartados)}")
    avisos = [p for p in plan if p["advertencia"]]
    for p in avisos:
        print(f"  ⚠ {p['fecha']}: {p['advertencia']}")
    if args.solo_listar:
        return

    # 2) Descarga
    manifiesto = os.path.join(args.carpeta, "manifest.csv")
    fallidos = []
    # Si ya hay un manifiesto de una corrida anterior, se reusan tamaño y hash de lo ya recortado y borrado
    previo = {}
    if os.path.exists(manifiesto):
        with open(manifiesto, encoding="utf-8") as f:
            previo = {r["archivo"]: r for r in csv.DictReader(l for l in f if not l.startswith("#"))}

    campos = ["fecha", "version", "archivo", "bytes", "sha256", "url", "firstSeenAt", "advertencia",
              "estado", "filas_recorte", "filas_cortas_completadas", "filas_largas_descartadas",
              "columnas_faltantes"]

    def guardar_manifiesto():
        tmp = manifiesto + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore", restval="")
            w.writeheader()
            w.writerows(plan)
            f.write(f"# indice: {args.indice_url} sha256={sha_indice} "
                    f"bajado={dt.datetime.now().isoformat(timespec='seconds')}\n")
            if recorte:
                f.write(f"# recorte: provincia={args.provincia} localidad={args.localidad}\n")
            for fecha in faltan:
                f.write(f"# sin archivo valido: {fecha}\n")
        os.replace(tmp, manifiesto)

    for i, p in enumerate(plan, 1):
        destino = os.path.join(args.carpeta, p["archivo"])
        base = p["archivo"].replace(".tar.zst", "")
        listo_recorte = os.path.join(carpeta_recorte, f"{base}_productos.csv.gz")
        print(f"[{i}/{len(plan)}] {p['archivo']}")
        if recorte and os.path.exists(listo_recorte) and not os.path.exists(destino) \
                and previo.get(p["archivo"], {}).get("sha256"):
            ant = previo[p["archivo"]]
            p.update({k: ant.get(k, "") for k in ("bytes", "sha256", "filas_recorte",
                      "filas_cortas_completadas", "filas_largas_descartadas", "columnas_faltantes")})
            p["estado"] = "ya recortado"
            print("    ya recortado")
            continue
        estado = descargar(p["url"], destino)
        print(f"    {estado}")
        p["estado"] = estado
        if estado == "FALLÓ":
            fallidos.append(p["archivo"])
            p["bytes"], p["sha256"] = "", ""
            continue
        p["bytes"], p["sha256"] = os.path.getsize(destino), sha256(destino)
        if recorte:
            try:
                r = recortar(destino, carpeta_recorte, base, args.provincia, args.localidad)
                p["filas_recorte"] = r["filas_productos"]
                p["filas_cortas_completadas"] = r["filas_cortas_completadas"]
                p["filas_largas_descartadas"] = r["filas_largas_descartadas"]
                p["columnas_faltantes"] = " ".join(r["columnas_faltantes"])
                print(f"    recorte: {r['comercios']} comercios, {r['sucursales']} sucursales, "
                      f"{r['filas_productos']:,} filas de productos")
                if r["filas_cortas_completadas"] or r["filas_largas_descartadas"]:
                    print(f"    filas raras en el archivo completo: {r['filas_cortas_completadas']:,} cortas "
                          f"(completadas), {r['filas_largas_descartadas']:,} largas (descartadas)")
                if args.borrar_crudos:
                    os.remove(destino)
                    p["estado"] = "recortado y borrado"
            except Exception as e:                # noqa: BLE001
                print(f"    el recorte falló ({e}); el archivo grande queda guardado")
                p["estado"] = "bajado, recorte FALLÓ"
                fallidos.append(p["archivo"])

        guardar_manifiesto()   # después de cada archivo: si se corta, la próxima corrida sabe qué ya está

    guardar_manifiesto()
    total_gb = sum(int(p["bytes"]) for p in plan if p["bytes"]) / 1e9
    print(f"\nListo: {len(plan) - len(fallidos)} de {len(plan)} archivos, {total_gb:.1f} GB. Manifiesto: {manifiesto}")
    if fallidos:
        print(f"Fallaron {len(fallidos)}: {fallidos}. Volvé a correr el mismo comando: retoma solo esos.")


if __name__ == "__main__":
    main()

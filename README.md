# Historial de precios SEPA en PostgreSQL 18: una fila por día vs. rangos de vigencia

Código y resultados del trabajo de cátedra de **Administración de Bases de Datos** (UTN FRLP, 2026), preparado para CoNaIISI.

Se compara cómo guardar el historial diario de precios de supermercados (datos abiertos SEPA / Precios Claros) en PostgreSQL 18:

- **A**: una fila por producto, sucursal y día.
- **B-GiST**: una fila por tramo de precio sin cambios (`daterange`), con índice GiST y sin restricción.
- **B-WO**: igual que B-GiST pero con `PRIMARY KEY (... vigencia WITHOUT OVERLAPS)` (novedad de PostgreSQL 18).

Recorte: sucursales de La Plata, del 01/02/2025 al 01/05/2025 (escalas de 30, 60 y 90 días).

## Requisitos

- Python 3.12 o superior y las dependencias de `requirements.txt` (`python -m pip install -r requirements.txt`).
- PostgreSQL 18 con la extensión `btree_gist`.
- Unos 30 GB libres durante la descarga (después se borran los crudos).

La contraseña de PostgreSQL **no** está en el código: se pasa por variable de entorno en cada sesión (`$env:PGPASSWORD = "..."` en PowerShell).

## Cómo reproducir, en orden

| Paso | Script | Qué hace |
| --- | --- | --- |
| 1 | `verificar_condiciones.py` | Chequea las tres condiciones previas (datos de varias fechas, misma clave entre archivos, repetición de precios). |
| 2 | `descargar_sepa.py` | Descarga los paquetes diarios del espejo histórico y guarda solo el recorte de La Plata (`--provincia AR-B --localidad "La Plata" --borrar-crudos`). |
| 3 | `analizar_ventana.py` | Elige la versión de cada día, asigna fechas reales y aplica las reglas de exclusión de comercios. |
| 4 | `revisar_duplicados.py` | Revisa las claves duplicadas. |
| 5 | `preparar_dataset.py` | Arma el dataset limpio (observaciones, sucursales, productos, ausencias). |
| 6 | `cargar.py --limpio <carpeta> --escala 30` (y 60, 90) | Crea los esquemas y carga día por día los tres modelos midiendo tiempos y tamaños. |
| 7 | `verificar_equivalencia.py` | Comprueba que A, B-GiST y B-WO guardan exactamente la misma información. |
| 8 | `analizar_carga.py` | Análisis de espacio y carga. |
| 9 | `medir_consultas.py` (y `--precalentar` con `shared_buffers=1GB`) | Mide las consultas Q1 a Q4. |
| 10 | `graficos.py --resultados resultados --t13 <carpeta t13> --salida figuras` | Genera las figuras y la tabla de H5. |

`demo_without_overlaps.sql` es un ejemplo chico de cómo funciona `WITHOUT OVERLAPS`.

## Carpetas

- `resultados/`: corrida oficial con la configuración por defecto (`shared_buffers` = 128 MB).
- `resultados_1gb_final/`: corrida de sensibilidad con todo en memoria (1 GB + `pg_prewarm`).
- `resultados_1gb/`: corrida de prueba anterior con 1 GB, hecha con la notebook en ahorro de energía. Se descartó y se conserva solo como registro.
- `resultado_condiciones*.json`: salida de `verificar_condiciones.py` (paso 1).
- `figuras/`: figuras del paper en PNG (300 dpi) y PDF.

Los datos crudos y el dataset limpio no se suben (son pesados y se regeneran con los pasos 2 a 5).

## Estadística

Comparaciones pareadas: mediana de las razones y su intervalo de confianza del 95% por bootstrap (10.000 remuestreos, semilla 20261122). Una diferencia cuenta si el intervalo no incluye 1 y la mediana cae fuera de 0,9–1,1.

## Fuente de los datos

SEPA – Sistema Electrónico de Publicidad de Precios Argentinos (Secretaría de Comercio, datos.produccion.gob.ar). Histórico obtenido del espejo https://github.com/catdevnull/sepa-precios-metadata.

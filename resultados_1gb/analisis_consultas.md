# Consultas Q1 a Q4 (H2a y H2b)

PostgreSQL 18.7 on x86_64-windows, compiled by msvc-19.44.35230, 64-bit. Configuración: {'shared_buffers': '1GB', 'work_mem': '4MB', 'jit': 'on', 'max_parallel_workers_per_gather': '2', 'effective_cache_size': '4GB'}. Solo caché caliente (cambio al protocolo aprobado el 22/11). Tablas e índices precalentados con pg_prewarm antes de cada escala.
Casos en que A y B-WO devolvieron respuestas distintas: **0** (tiene que ser 0).

| Escala | Consulta | Hipótesis | Mediana A (ms) | Mediana B-WO (ms) | P95 A (ms) | P95 B-WO (ms) | Mediana razón B-WO/A | IC 95% | Veredicto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | Q1 | H2a | 0.37 | 0.39 | 1.31 | 1.27 | 1.16 | 1.01 – 1.34 | B-WO más lenta |
| 30 | Q2 | H2a | 12.42 | 10.07 | 23.13 | 14.52 | 0.87 | 0.82 – 0.94 | B-WO más rápida |
| 30 | Q3 | H2b | 0.52 | 0.46 | 1.51 | 1.71 | 1.06 | 0.97 – 1.19 | sin diferencia detectable |
| 30 | Q4 | H2b | 8016.95 | 828.02 | 9037.79 | 1151.64 | 0.10 | 0.10 – 0.11 | B-WO más rápida |
| 60 | Q1 | H2a | 0.69 | 0.71 | 1.72 | 1.30 | 0.96 | 0.84 – 1.08 | sin diferencia detectable |
| 60 | Q2 | H2a | 22.49 | 17.78 | 60.17 | 44.40 | 0.80 | 0.69 – 0.94 | B-WO más rápida |
| 60 | Q3 | H2b | 1.09 | 1.06 | 2.15 | 2.36 | 0.95 | 0.88 – 1.16 | sin diferencia detectable |
| 60 | Q4 | H2b | 16184.75 | 1253.50 | 20031.33 | 1601.98 | 0.08 | 0.08 – 0.08 | B-WO más rápida |
| 90 | Q1 | H2a | 0.55 | 0.61 | 1.63 | 1.54 | 1.11 | 0.89 – 1.31 | sin diferencia detectable |
| 90 | Q2 | H2a | 30.63 | 19.03 | 122.37 | 61.29 | 0.66 | 0.61 – 0.70 | B-WO más rápida |
| 90 | Q3 | H2b | 1.69 | 1.01 | 4.96 | 2.15 | 0.60 | 0.50 – 0.76 | B-WO más rápida |
| 90 | Q4 | H2b | 24762.53 | 1615.23 | 28201.34 | 1843.42 | 0.06 | 0.06 – 0.07 | B-WO más rápida |

H2a (Q1, Q2): se refuta si B-WO es más rápida que A. H2b (Q3, Q4): se refuta si B-WO no es más rápida que A.
Razón 0,50 = B-WO tarda la mitad; 2,00 = el doble. Hay diferencia si el IC 95% no incluye 1 y la mediana está fuera de 0,9–1,1.

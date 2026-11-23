# Consultas Q1 a Q4 (H2a y H2b)

PostgreSQL 18.7 on x86_64-windows, compiled by msvc-19.44.35230, 64-bit. Configuración: {'shared_buffers': '1GB', 'work_mem': '4MB', 'jit': 'on', 'max_parallel_workers_per_gather': '2', 'effective_cache_size': '4GB'}. Solo caché caliente (cambio al protocolo aprobado el 22/11). Tablas e índices precalentados con pg_prewarm antes de cada escala.
Casos en que A y B-WO devolvieron respuestas distintas: **0** (tiene que ser 0).

| Escala | Consulta | Hipótesis | Mediana A (ms) | Mediana B-WO (ms) | P95 A (ms) | P95 B-WO (ms) | Mediana razón B-WO/A | IC 95% | Veredicto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | Q1 | H2a | 0.34 | 0.34 | 1.08 | 0.96 | 1.05 | 0.90 – 1.16 | sin diferencia detectable |
| 30 | Q2 | H2a | 9.07 | 8.09 | 21.93 | 16.42 | 0.88 | 0.81 – 0.94 | B-WO más rápida |
| 30 | Q3 | H2b | 0.30 | 0.34 | 0.62 | 0.69 | 1.00 | 0.93 – 1.16 | sin diferencia detectable |
| 30 | Q4 | H2b | 2116.43 | 250.67 | 2390.73 | 322.73 | 0.12 | 0.12 – 0.12 | B-WO más rápida |
| 60 | Q1 | H2a | 0.35 | 0.36 | 0.85 | 1.92 | 1.06 | 0.92 – 1.18 | sin diferencia detectable |
| 60 | Q2 | H2a | 10.74 | 6.69 | 21.48 | 12.92 | 0.62 | 0.60 – 0.71 | B-WO más rápida |
| 60 | Q3 | H2b | 0.55 | 0.53 | 1.64 | 2.28 | 0.97 | 0.82 – 1.07 | sin diferencia detectable |
| 60 | Q4 | H2b | 4321.49 | 328.82 | 4845.89 | 400.38 | 0.08 | 0.08 – 0.08 | B-WO más rápida |
| 90 | Q1 | H2a | 0.24 | 0.28 | 1.22 | 0.85 | 1.12 | 0.98 – 1.27 | sin diferencia detectable |
| 90 | Q2 | H2a | 15.91 | 7.70 | 33.91 | 18.54 | 0.54 | 0.47 – 0.58 | B-WO más rápida |
| 90 | Q3 | H2b | 0.94 | 0.48 | 1.79 | 1.93 | 0.60 | 0.53 – 0.62 | B-WO más rápida |
| 90 | Q4 | H2b | 6549.20 | 428.75 | 7333.85 | 521.69 | 0.07 | 0.06 – 0.07 | B-WO más rápida |

H2a (Q1, Q2): se refuta si B-WO es más rápida que A. H2b (Q3, Q4): se refuta si B-WO no es más rápida que A.
Razón 0,50 = B-WO tarda la mitad; 2,00 = el doble. Hay diferencia si el IC 95% no incluye 1 y la mediana está fuera de 0,9–1,1.

# Consultas Q1 a Q4 (H2a y H2b)

PostgreSQL 18.7 on x86_64-windows, compiled by msvc-19.44.35230, 64-bit. Configuración: {'shared_buffers': '128MB', 'work_mem': '4MB', 'jit': 'on', 'max_parallel_workers_per_gather': '2', 'effective_cache_size': '4GB'}. Solo caché caliente (cambio al protocolo aprobado el 22/11).
Casos en que A y B-WO devolvieron respuestas distintas: **0** (tiene que ser 0).

| Escala | Consulta | Hipótesis | Mediana A (ms) | Mediana B-WO (ms) | P95 A (ms) | P95 B-WO (ms) | Mediana razón B-WO/A | IC 95% | Veredicto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | Q1 | H2a | 0.86 | 0.48 | 1.98 | 1.03 | 0.57 | 0.51 – 0.65 | B-WO más rápida |
| 30 | Q2 | H2a | 10.86 | 7.33 | 40.22 | 23.41 | 0.64 | 0.58 – 0.73 | B-WO más rápida |
| 30 | Q3 | H2b | 5.95 | 0.40 | 20.91 | 1.39 | 0.07 | 0.06 – 0.11 | B-WO más rápida |
| 30 | Q4 | H2b | 2311.05 | 249.59 | 2569.09 | 318.78 | 0.11 | 0.11 – 0.11 | B-WO más rápida |
| 60 | Q1 | H2a | 1.22 | 0.66 | 2.93 | 2.54 | 0.57 | 0.43 – 0.69 | B-WO más rápida |
| 60 | Q2 | H2a | 12.97 | 7.59 | 74.04 | 47.61 | 0.56 | 0.51 – 0.65 | B-WO más rápida |
| 60 | Q3 | H2b | 10.74 | 0.58 | 38.41 | 1.43 | 0.05 | 0.04 – 0.08 | B-WO más rápida |
| 60 | Q4 | H2b | 4654.98 | 332.06 | 5227.77 | 410.93 | 0.07 | 0.07 – 0.07 | B-WO más rápida |
| 90 | Q1 | H2a | 0.90 | 0.30 | 1.65 | 0.77 | 0.46 | 0.31 – 0.62 | B-WO más rápida |
| 90 | Q2 | H2a | 16.09 | 8.33 | 65.85 | 36.93 | 0.51 | 0.43 – 0.57 | B-WO más rápida |
| 90 | Q3 | H2b | 1.32 | 0.45 | 3.13 | 1.30 | 0.36 | 0.28 – 0.45 | B-WO más rápida |
| 90 | Q4 | H2b | 6998.80 | 428.73 | 9189.10 | 566.03 | 0.06 | 0.06 – 0.06 | B-WO más rápida |

H2a (Q1, Q2): se refuta si B-WO es más rápida que A. H2b (Q3, Q4): se refuta si B-WO no es más rápida que A.
Razón 0,50 = B-WO tarda la mitad; 2,00 = el doble. Hay diferencia si el IC 95% no incluye 1 y la mediana está fuera de 0,9–1,1.

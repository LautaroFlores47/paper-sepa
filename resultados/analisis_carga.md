# Espacio y carga diaria

## Espacio (H1b)

| Escala | Momento | Filas A | Filas B | A/B filas | MB A | MB B-WO | MB B-GiST | A/B-WO bytes | ¿H1b se cumple? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | tras_vacuum | 2,161,232 | 122,689 | 17.6 | 198.2 | 17.1 | 18.6 | 11.6 | sí |
| 30 | compacto | 2,161,232 | 122,689 | 17.6 | 181.0 | 12.7 | 12.7 | 14.2 | sí |
| 60 | tras_vacuum | 4,319,337 | 174,763 | 24.7 | 408.7 | 24.7 | 27.9 | 16.5 | sí |
| 60 | compacto | 4,319,337 | 174,763 | 24.7 | 361.6 | 19.2 | 19.2 | 18.8 | sí |
| 90 | tras_vacuum | 6,456,579 | 237,636 | 27.2 | 620.3 | 36.2 | 39.6 | 17.1 | sí |
| 90 | compacto | 6,456,579 | 237,636 | 27.2 | 540.6 | 27.3 | 27.3 | 19.8 | sí |

## Carga diaria: tiempos por modelo (segundos)

| Escala | Modelo | Mediana | Percentil 95 | Rango intercuartílico | Máximo | Día del máximo |
| --- | --- | --- | --- | --- | --- | --- |
| 30 | a | 0.320 | 0.670 | 0.292 – 0.391 | 0.788 | 19 |
| 30 | b_gist | 0.110 | 0.529 | 0.096 – 0.139 | 0.940 | 1 |
| 30 | b_wo | 0.175 | 0.972 | 0.137 – 0.240 | 1.766 | 1 |
| 60 | a | 0.409 | 1.361 | 0.293 – 0.800 | 1.490 | 37 |
| 60 | b_gist | 0.136 | 0.296 | 0.108 – 0.172 | 0.723 | 1 |
| 60 | b_wo | 0.199 | 0.408 | 0.161 – 0.259 | 1.675 | 1 |
| 90 | a | 0.699 | 3.564 | 0.300 – 1.399 | 5.938 | 74 |
| 90 | b_gist | 0.158 | 0.644 | 0.113 – 0.207 | 1.327 | 79 |
| 90 | b_wo | 0.243 | 0.816 | 0.174 – 0.317 | 1.812 | 1 |

## Comparaciones emparejadas (bootstrap, 10.000 remuestreos, semilla fija)

| Análisis | Comparación | Pares | Mediana de la razón | IC 95% | Veredicto |
| --- | --- | --- | --- | --- | --- |
| Principal: escala 30, días 1–30 | H3a: b_wo / a | 30 | 0.58 | 0.43 – 0.68 | b_wo es MÁS RÁPIDO que a |
| Principal: escala 30, días 1–30 | H3b: b_wo / b_gist | 30 | 1.53 | 1.41 – 1.74 | b_wo es MÁS LENTO que b_gist |
| Sensibilidad: escala 90, días 2–90 | H3a: b_wo / a | 89 | 0.39 | 0.31 – 0.46 | b_wo es MÁS RÁPIDO que a |
| Sensibilidad: escala 90, días 2–90 | H3b: b_wo / b_gist | 89 | 1.56 | 1.46 – 1.67 | b_wo es MÁS LENTO que b_gist |

Lectura de la razón: 0,50 = tarda la mitad; 2,00 = tarda el doble. Regla: hay diferencia si el IC 95% no incluye 1 y la mediana está fuera de 0,9–1,1.

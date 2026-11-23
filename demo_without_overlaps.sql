-- demo_without_overlaps.sql
-- Ejemplo chico para ver WITHOUT OVERLAPS funcionando antes de armar las tablas del experimento.
-- Correr con:
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d sepa -f demo_without_overlaps.sql

-- 1) Extensión que permite mezclar columnas comunes (producto) con rangos de fechas en un índice GiST
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- 2) Tabla de precios con vigencia: "este precio valió desde tal día hasta tal día"
DROP TABLE IF EXISTS demo_precios;
CREATE TABLE demo_precios (
    producto  text          NOT NULL,
    precio    numeric(12,2) NOT NULL,
    vigencia  daterange     NOT NULL,
    PRIMARY KEY (producto, vigencia WITHOUT OVERLAPS)
);

-- 3) La leche: $1.000 del 1 al 20 de marzo y $1.200 desde el 21.
--    daterange('2025-03-01', '2025-03-21') incluye el 1 y NO incluye el 21: es [1/3, 21/3)
--    daterange('2025-03-21', NULL) no tiene fin: es el precio vigente hoy
INSERT INTO demo_precios VALUES
    ('leche', 1000, daterange('2025-03-01', '2025-03-21')),
    ('leche', 1200, daterange('2025-03-21', NULL)),
    ('pan',    800, daterange('2025-03-01', NULL));

SELECT * FROM demo_precios ORDER BY producto, vigencia;

-- 4) ¿Cuánto valía la leche el 10 de marzo? (@> significa "el rango contiene a esta fecha")
SELECT producto, precio FROM demo_precios
WHERE producto = 'leche' AND vigencia @> DATE '2025-03-10';

-- 5) Error a propósito: otro precio para la leche que se superpone con los que ya están.
--    Tiene que FALLAR. Ese error es justamente lo que garantiza WITHOUT OVERLAPS.
INSERT INTO demo_precios VALUES ('leche', 999, daterange('2025-03-15', '2025-03-25'));

-- 6) El pan sí puede tener ese rango: es otro producto, no se superpone con nada suyo
INSERT INTO demo_precios VALUES ('pan', 850, daterange('2024-12-01', '2025-03-01'));

-- 7) Ver la tabla y el índice que creó PostgreSQL (tiene que decir "gist")
\d demo_precios

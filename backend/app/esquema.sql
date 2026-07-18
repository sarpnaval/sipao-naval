-- =====================================================================
-- SARP-Naval · Esquema de base de datos SQLite (dossier técnico §4)
-- Sistema de Abastecimiento y Reposición Predictiva — Armada del Ecuador
-- Base LOCAL propia del aplicativo. NUNCA escribe en SISLOG:
-- los datos entran solo por importación/lectura.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- Catálogo maestro de ítems (repuestos y consumibles)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
    codigo          TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    categoria       TEXT NOT NULL,
    unidad          TEXT NOT NULL,
    costo_unitario  REAL NOT NULL,
    criticidad_ved  TEXT NOT NULL CHECK (criticidad_ved IN ('V', 'E', 'D')),
    lead_time_dias  INTEGER NOT NULL,
    importado       INTEGER NOT NULL CHECK (importado IN (0, 1)),
    proveedor       TEXT
);

-- ---------------------------------------------------------------------
-- Movimientos de inventario (consumos, ingresos, ajustes)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS movimientos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_item  TEXT NOT NULL REFERENCES items(codigo),
    fecha        TEXT NOT NULL,                -- ISO yyyy-mm-dd
    tipo         TEXT NOT NULL CHECK (tipo IN ('consumo', 'ingreso', 'ajuste')),
    cantidad     REAL NOT NULL,
    reparto      TEXT NOT NULL,
    orden_ref    TEXT
);

CREATE INDEX IF NOT EXISTS idx_movimientos_item_fecha
    ON movimientos (codigo_item, fecha);

-- ---------------------------------------------------------------------
-- Existencias por reparto (foto al corte)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock (
    codigo_item  TEXT NOT NULL REFERENCES items(codigo),
    reparto      TEXT NOT NULL,
    existencia   REAL NOT NULL,
    fecha_corte  TEXT NOT NULL,                -- ISO yyyy-mm-dd
    ubicacion    TEXT,
    PRIMARY KEY (codigo_item, reparto)
);

-- ---------------------------------------------------------------------
-- Parámetros de inventario calculados por el motor SARP
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parametros (
    codigo_item    TEXT PRIMARY KEY REFERENCES items(codigo),
    z_servicio     REAL NOT NULL,              -- z por criticidad V/E/D
    ss             INTEGER NOT NULL,           -- stock de seguridad
    rop            INTEGER NOT NULL,           -- punto de reorden
    eoq            INTEGER NOT NULL,           -- lote económico
    nivel_max      INTEGER NOT NULL,           -- nivel máximo (ROP + EOQ)
    fecha_calculo  TEXT NOT NULL,
    version_modelo TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- Pronósticos de demanda (Holt / Croston) a 6 meses
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pronosticos (
    codigo_item      TEXT NOT NULL REFERENCES items(codigo),
    mes              TEXT NOT NULL,            -- etiqueta, ej. "jul-26"
    demanda_prevista REAL NOT NULL,
    sigma            REAL NOT NULL,
    mape             REAL,                     -- NULL para modelos intermitentes
    modelo           TEXT NOT NULL CHECK (modelo IN ('holt', 'croston')),
    PRIMARY KEY (codigo_item, mes)
);

-- ---------------------------------------------------------------------
-- Cola de alertas priorizadas (una por ítem con estado distinto de OK)
-- Prioridad = orden secuencial 1..N según dossier §5.4:
--   1) estado QUIEBRE > REPONER > EXCESO
--   2) criticidad V > E > D
--   3) margen = dias_a_quiebre - lead_time_dias, ascendente
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alertas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    -- UNIQUE: a lo sumo una alerta por ítem (invariante que asumen los
    -- endpoints: LEFT JOIN sin deduplicar y fetchone() en el detalle)
    codigo_item       TEXT NOT NULL UNIQUE REFERENCES items(codigo),
    estado            TEXT NOT NULL CHECK (estado IN ('QUIEBRE', 'REPONER', 'EXCESO')),
    dias_a_quiebre    INTEGER NOT NULL,
    cantidad_sugerida INTEGER NOT NULL,
    prioridad         INTEGER NOT NULL,
    fecha             TEXT NOT NULL,
    atendida          INTEGER NOT NULL DEFAULT 0 CHECK (atendida IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_alertas_prioridad ON alertas (prioridad);

-- ---------------------------------------------------------------------
-- TABLA CALCULADA (auxiliar, coherente con el espíritu del §4):
-- resultados de clasificación y valorización que produce el motor SARP
-- por ítem. No es dato fuente: se regenera en cada recálculo/siembra.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clasificacion (
    codigo_item     TEXT PRIMARY KEY REFERENCES items(codigo),
    abc             TEXT NOT NULL CHECK (abc IN ('A', 'B', 'C')),
    xyz             TEXT NOT NULL CHECK (xyz IN ('X', 'Y', 'Z')),
    cv              REAL NOT NULL,             -- coeficiente de variación
    valor_anual     INTEGER NOT NULL,          -- demanda anual valorizada (USD)
    valor_stock     INTEGER NOT NULL,          -- existencia valorizada (USD)
    dias_quiebre    INTEGER NOT NULL,          -- días hasta quiebre estimados (999 = sin consumo)
    demanda_mensual REAL NOT NULL              -- demanda media mensual (últimos 12 meses)
);

-- ---------------------------------------------------------------------
-- TABLA CALCULADA (auxiliar): metadatos del último conjunto de datos
-- cargado (fecha de generación, reparto, corte). Clave/valor.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metadatos (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- BITÁCORA DE AUDITORÍA (tarea C1.2 · registro directo)
-- Pista de auditoría de toda escritura en la base PROPIA de SARP:
-- altas de ítem, movimientos, ajustes, importaciones y recálculos.
-- NUNCA se escribe en SISLOG; esta bitácora audita el modo "sistema
-- primario" de SARP. En producción se enlaza a la autenticación
-- institucional (usuario firmante); en esta versión de demostración
-- la columna `rol` registra el rol de demostración activo.
-- No se borra en las importaciones: la pista de auditoría persiste.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bitacora (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora    TEXT NOT NULL,               -- ISO yyyy-mm-ddThh:mm:ss
    rol           TEXT NOT NULL,               -- rol de demostración activo
    accion        TEXT NOT NULL CHECK (accion IN
                      ('alta_item', 'registro_movimiento', 'ajuste_stock',
                       'importacion', 'recalculo')),
    codigo_item   TEXT,                        -- NULL en acciones globales
    detalle       TEXT NOT NULL,
    datos_previos TEXT                         -- JSON del estado anterior (ajustes)
);

CREATE INDEX IF NOT EXISTS idx_bitacora_fecha ON bitacora (fecha_hora);

-- Bitácora del PANEL DE CONFIGURACIÓN (v3, 18-jul-2026).
-- Tabla propia: cambiar un parámetro de costeo es un acto de gobierno del
-- modelo, distinto de un movimiento de inventario. Registra valor previo,
-- valor nuevo, procedencia, responsable y motivo — de modo que toda cifra
-- del sistema sea trazable hasta quién la cargó y con qué respaldo.
CREATE TABLE IF NOT EXISTS configuracion_bitacora (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_hora    TEXT NOT NULL,               -- ISO yyyy-mm-ddThh:mm:ss
    seccion       TEXT NOT NULL,               -- parametros|modelos|operaciones|tipos
    clave         TEXT NOT NULL,               -- parámetro/modelo/operación afectado
    campo         TEXT NOT NULL,
    valor_previo  TEXT,
    valor_nuevo   TEXT,
    origen        TEXT,                        -- procedencia declarada del dato
    fuente        TEXT,                        -- documento/oficio que lo respalda
    motivo        TEXT NOT NULL,
    responsable   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_config_bitacora_fecha
    ON configuracion_bitacora (fecha_hora);

-- Valores de configuración APLICADOS (v3.1, 18-jul-2026).
-- Defecto corregido: antes el panel de configuración mutaba diccionarios en
-- memoria y solo guardaba la bitácora; al reiniciar, los parámetros volvían a
-- fábrica mientras la bitácora seguía afirmando que se habían cambiado — una
-- auditoría que no concuerda con el estado real. Esta tabla guarda el valor
-- efectivo y se reaplica al arrancar, de modo que bitácora y estado coincidan.
CREATE TABLE IF NOT EXISTS configuracion_valores (
    seccion     TEXT NOT NULL,             -- parametros|modelos|operaciones|tipos
    clave       TEXT NOT NULL,             -- parámetro/modelo/operación/tipo
    campo       TEXT NOT NULL,
    valor       TEXT NOT NULL,             -- serializado como texto
    origen      TEXT,                      -- procedencia declarada del dato
    fuente      TEXT,                      -- documento que lo respalda
    actualizado TEXT NOT NULL,             -- ISO yyyy-mm-ddThh:mm:ss
    PRIMARY KEY (seccion, clave, campo)
);

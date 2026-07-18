"""Acceso a la base de datos SQLite de SARP-Naval.

Base LOCAL propia del aplicativo (nunca escribe en SISLOG). La ruta se
resuelve, en orden de precedencia:
  1. parámetro explícito `ruta` de cada función (usado por las pruebas),
  2. variable de entorno SARP_BD,
  3. ruta por defecto `backend/sarp.db` junto al paquete.
"""

import os
import sqlite3
from pathlib import Path

_DIR_APP = Path(__file__).resolve().parent

# Ruta por defecto: <raíz v1>/backend/sarp.db
RUTA_BD = _DIR_APP.parent / "sarp.db"

# DDL fuente del esquema (dossier técnico §4)
RUTA_ESQUEMA = _DIR_APP / "esquema.sql"


def ruta_bd_activa(ruta=None):
    """Resuelve la ruta de la base: parámetro > SARP_BD > por defecto."""
    if ruta:
        return Path(ruta)
    ruta_entorno = os.environ.get("SARP_BD")
    return Path(ruta_entorno) if ruta_entorno else RUTA_BD


def obtener_conexion(ruta=None):
    """Abre una conexión con claves foráneas activas y filas tipo dict.

    Las filas se devuelven como sqlite3.Row: acceso por nombre de columna
    (fila["campo"]) y convertibles con dict(fila).
    """
    # check_same_thread=False: FastAPI puede ejecutar la dependencia y el
    # endpoint en hilos distintos de su threadpool. Cada petición usa su
    # propia conexión (nunca compartida entre peticiones), así que es seguro.
    conexion = sqlite3.connect(str(ruta_bd_activa(ruta)),
                               check_same_thread=False)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def inicializar_bd(ruta=None):
    """Crea la base (si no existe) y ejecuta el DDL de esquema.sql.

    El DDL usa CREATE TABLE IF NOT EXISTS, por lo que es seguro
    ejecutarla sobre una base ya inicializada. Devuelve la ruta usada.
    """
    ruta_final = ruta_bd_activa(ruta)
    ruta_final.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(str(ruta_final))
    try:
        conexion.executescript(RUTA_ESQUEMA.read_text(encoding="utf-8"))
        conexion.commit()
    finally:
        conexion.close()
    return ruta_final


def obtener_bd():
    """Dependencia FastAPI: entrega una conexión y la cierra al terminar."""
    conexion = obtener_conexion()
    try:
        yield conexion
    finally:
        conexion.close()

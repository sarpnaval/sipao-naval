"""SIPAO-Naval · Preparación de la instancia publicada.

Se ejecuta UNA vez antes de levantar el servidor (ver Dockerfile):

1. Crea la base si no existe y aplica el esquema.
2. La siembra con el catálogo referencial SOLO si está vacía. Así el primer
   despliegue queda utilizable de inmediato, y los redespliegues posteriores
   NO pisan lo que el usuario haya cargado o configurado.
3. Restaura la última instantánea si la hay y la base está vacía (ver
   `respaldo.py`): en plataformas gratuitas el disco del contenedor es
   efímero, y esto es lo que convierte «se borra al reiniciar» en «se
   recupera al reiniciar».

Es idempotente: ejecutarlo mil veces deja el mismo resultado.
"""

import sys

from backend.app import db


def _esta_vacia(conexion):
    try:
        fila = conexion.execute("SELECT COUNT(*) AS n FROM items").fetchone()
        return (fila["n"] if hasattr(fila, "keys") else fila[0]) == 0
    except Exception:
        return True


def preparar():
    ruta = db.inicializar_bd(db.ruta_bd_activa())
    print(f"  Base de datos: {ruta}")

    # --- 1) intentar restaurar una instantánea previa
    try:
        from backend.app import respaldo
        if respaldo.restaurar_si_procede(ruta):
            print("  Instantánea restaurada: se conservan los datos previos.")
    except Exception as e:                       # nunca impedir el arranque
        print(f"  (sin restauración de instantánea: {e})")

    # --- 2) sembrar solo si sigue vacía
    conexion = db.obtener_conexion()
    try:
        vacia = _esta_vacia(conexion)
    finally:
        conexion.close()

    if vacia:
        print("  Base vacía: sembrando el catálogo referencial…")
        from backend.app import seed
        seed.sembrar(ruta=str(ruta))
        print("  Catálogo referencial sembrado.")
    else:
        print("  Base con datos: no se siembra (se respeta lo cargado).")

    # --- 3) reaplicar la configuración guardada
    conexion = db.obtener_conexion()
    try:
        from backend.app import config_persistente
        aplicados, ignorados = config_persistente.cargar_configuracion(conexion)
        if aplicados:
            print(f"  Configuración reaplicada: {aplicados} valor(es).")
    finally:
        conexion.close()

    return 0


if __name__ == "__main__":
    sys.exit(preparar())

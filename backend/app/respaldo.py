"""SIPAO-Naval · Respaldo y restauración de la base publicada.

EL PROBLEMA QUE RESUELVE
------------------------
Las plataformas gratuitas dan un disco EFÍMERO: lo que el contenedor
escribe se pierde cuando la instancia se reinicia. Sin esto, una
importación de datos o un cambio de configuración duraría hasta el
siguiente reinicio — justo lo que no puede pasar en un sistema con
bitácora de auditoría.

CÓMO FUNCIONA
-------------
La base entera pesa menos de 1 MB, así que no hace falta un motor de base
de datos remoto: basta con guardar el archivo completo en un repositorio
PRIVADO de Hugging Face (un «Dataset») después de cada escritura, y
restaurarlo al arrancar. Es simple, auditable y no cambia una sola línea
de SQL.

DEGRADACIÓN ELEGANTE (importante)
---------------------------------
Si no hay credencial configurada, el módulo NO falla: simplemente no
respalda, y lo dice. El aplicativo sigue funcionando igual —en local y en
las pruebas nunca se activa—. Ninguna falla de respaldo puede tumbar el
servicio: todas las excepciones se capturan y se registran.

CREDENCIAL
----------
Se lee de la variable de entorno `HF_TOKEN`, que se carga como «secreto»
en la plataforma. Nunca se escribe en el código ni en el repositorio.
"""

import os
import shutil
import threading
import time
from pathlib import Path

VARIABLE_TOKEN = "HF_TOKEN"
VARIABLE_REPO = "SIPAO_REPO_RESPALDO"      # p. ej. "usuario/sipao-datos"
ARCHIVO_REMOTO = "sipao.db"

_lock = threading.Lock()
_ultimo_respaldo = 0.0
_subiendo = False            # hay una subida en curso
_pendiente = False           # llegaron cambios mientras subía

# Freno de emergencia. Si al encender NO se pudo bajar la instantánea por un
# problema pasajero (Hugging Face lento, DNS, red), el arranque siembra el
# catálogo referencial para que el servicio funcione igual. Pero entonces la
# base viva contiene datos de fábrica, NO los del usuario: si dejáramos que
# la primera escritura subiera esa base, PISARÍAMOS el respaldo bueno con
# uno vacío y los datos del usuario se perderían para siempre.
# Ante la duda se prefiere no respaldar antes que destruir el respaldo.
_subidas_bloqueadas = None      # None = permitido; texto = motivo del bloqueo


def _configurado():
    return bool(os.environ.get(VARIABLE_TOKEN, "").strip()
                and os.environ.get(VARIABLE_REPO, "").strip())


def bloquear_subidas(motivo):
    """Impide subir instantáneas hasta el próximo arranque limpio."""
    global _subidas_bloqueadas
    _subidas_bloqueadas = motivo
    print(f"  ⚠ RESPALDO EN PAUSA: {motivo}")


def permitir_subidas():
    global _subidas_bloqueadas
    _subidas_bloqueadas = None


def estado():
    """Para mostrar en la pantalla si el respaldo está activo."""
    if not _configurado():
        return {"activo": False,
                "motivo": ("Sin credencial de respaldo: los cambios viven "
                           "mientras la instancia siga encendida.")}
    if _subidas_bloqueadas:
        return {"activo": False,
                "repositorio": os.environ.get(VARIABLE_REPO),
                "motivo": _subidas_bloqueadas}
    return {"activo": True, "repositorio": os.environ.get(VARIABLE_REPO),
            "ultimo": _ultimo_respaldo}


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=os.environ[VARIABLE_TOKEN].strip())


def _tiene_datos(ruta_bd):
    """¿La base ya contiene un catálogo real?

    Se pregunta a la BASE, no al archivo. El criterio anterior miraba el
    TAMAÑO (>40 kB = "tiene datos") y era falso: el arranque crea la base
    y aplica el esquema ANTES de intentar restaurar, y una base recién
    creada, con cero filas, ya pesa 110 kB. Resultado: la restauración se
    saltaba siempre, en silencio, y cada reinicio del servidor empezaba
    de cero mientras el respaldo parecía estar funcionando (18-jul-2026).
    """
    ruta_bd = Path(ruta_bd)
    if not ruta_bd.exists():
        return False
    import sqlite3
    try:
        conexion = sqlite3.connect(str(ruta_bd))
        try:
            fila = conexion.execute("SELECT COUNT(*) FROM items").fetchone()
            return bool(fila and fila[0] > 0)
        finally:
            conexion.close()
    except Exception:
        # Sin tabla `items` o archivo ilegible: no hay nada que proteger.
        return False


def restaurar_si_procede(ruta_bd):
    """Descarga la última instantánea si la base local está vacía o no existe.

    Devuelve True si restauró algo. Nunca lanza: si falla, el arranque
    continúa y se sembrará el catálogo referencial.
    """
    if not _configurado():
        return False
    ruta_bd = Path(ruta_bd)
    if _tiene_datos(ruta_bd):
        print("  La base ya tiene datos: no se restaura (se respeta lo cargado).")
        return False
    try:
        from huggingface_hub import hf_hub_download
        descargado = hf_hub_download(
            repo_id=os.environ[VARIABLE_REPO].strip(),
            filename=ARCHIVO_REMOTO,
            repo_type="dataset",
            token=os.environ[VARIABLE_TOKEN].strip())
        ruta_bd.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(descargado, ruta_bd)
        print(f"  Instantánea descargada de {os.environ[VARIABLE_REPO].strip()}.")
        return True
    except Exception as e:
        # Se distingue "todavía no hay instantánea" (primer arranque, normal)
        # de "no se pudo bajar" (credencial mala, repositorio equivocado, red):
        # confundirlos fue lo que escondió el defecto del criterio por tamaño.
        nombre = type(e).__name__
        if "EntryNotFound" in nombre or "RepositoryNotFound" in nombre:
            # No hay nada guardado todavía: es el primer arranque y lo correcto
            # es sembrar y empezar a respaldar con normalidad.
            print("  Todavía no hay instantánea que restaurar (primer arranque).")
        else:
            # Sí hay (o puede haber) una instantánea buena y no la alcanzamos.
            # Se siembra para que el servicio opere, pero NO se le permite
            # subir esa base de fábrica encima del respaldo del usuario.
            print(f"  ⚠ NO SE PUDO restaurar la instantánea: {nombre}: {e}")
            bloquear_subidas(
                "No se pudo leer el respaldo al encender, así que no se sobrescribe "
                "para no destruir los datos guardados. Reinicie el servicio cuando "
                "haya conexión; si el problema sigue, revise la credencial de respaldo.")
        return False


def _subir_una_vez(ruta_bd):
    try:
        _api().upload_file(
            path_or_fileobj=str(ruta_bd),
            path_in_repo=ARCHIVO_REMOTO,
            repo_id=os.environ[VARIABLE_REPO].strip(),
            repo_type="dataset",
            commit_message="Instantánea automática de SIPAO-Naval")
        return True
    except Exception as e:
        print(f"  ⚠ No se pudo respaldar la base: {type(e).__name__}: {e}")
        return False


def _subir(ruta_bd):
    """Sube y, si llegaron más cambios mientras subía, vuelve a subir.

    Antes se AGRUPABA descartando: la primera escritura de una ráfaga se
    subía y las siguientes se ignoraban por venir dentro de la ventana de
    20 s. Eso dejaba el respaldo con un estado INTERMEDIO, no con el final:
    si el usuario guardaba dos veces seguidas, la segunda no llegaba nunca.
    Ahora se agrupa por el otro extremo — al terminar se comprueba si quedó
    algo pendiente y se repite— que es lo que el usuario espera: lo último
    que hizo es lo que queda guardado.
    """
    global _pendiente
    while True:
        _subir_una_vez(ruta_bd)
        with _lock:
            if not _pendiente:
                globals()["_subiendo"] = False
                return
            _pendiente = False


def respaldar(ruta_bd=None):
    """Sube la base en segundo plano, sin bloquear la respuesta al usuario.

    Ya no hay parámetro `forzar`: existía para saltarse la ventana de 20 s
    que agrupaba ráfagas descartando escrituras. Esa ventana desapareció —
    ahora se encola una subida final— así que ninguna escritura se pierde y
    forzar no significaba nada.
    """
    global _ultimo_respaldo, _pendiente, _subiendo
    if not _configurado():
        return False
    if _subidas_bloqueadas:
        return False
    from backend.app import db
    ruta = Path(ruta_bd) if ruta_bd else db.ruta_bd_activa()
    if not ruta.exists():
        return False

    with _lock:
        _ultimo_respaldo = time.time()
        if _subiendo:
            # Ya hay una subida en curso: se anota para que, al terminar,
            # suba también este estado más reciente.
            _pendiente = True
            return True
        _subiendo = True

    threading.Thread(target=_subir, args=(ruta,), daemon=True).start()
    return True

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
_INTERVALO_MIN = 20.0        # segundos: agrupa ráfagas de escrituras


def _configurado():
    return bool(os.environ.get(VARIABLE_TOKEN, "").strip()
                and os.environ.get(VARIABLE_REPO, "").strip())


def estado():
    """Para mostrar en la pantalla si el respaldo está activo."""
    if not _configurado():
        return {"activo": False,
                "motivo": ("Sin credencial de respaldo: los cambios viven "
                           "mientras la instancia siga encendida.")}
    return {"activo": True, "repositorio": os.environ.get(VARIABLE_REPO),
            "ultimo": _ultimo_respaldo}


def _api():
    from huggingface_hub import HfApi
    return HfApi(token=os.environ[VARIABLE_TOKEN].strip())


def restaurar_si_procede(ruta_bd):
    """Descarga la última instantánea si la base local está vacía o no existe.

    Devuelve True si restauró algo. Nunca lanza: si falla, el arranque
    continúa y se sembrará el catálogo referencial.
    """
    if not _configurado():
        return False
    ruta_bd = Path(ruta_bd)
    # si ya hay una base con contenido real, no la pisamos
    if ruta_bd.exists() and ruta_bd.stat().st_size > 40_000:
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
        return True
    except Exception as e:
        print(f"  (no había instantánea previa que restaurar: {type(e).__name__})")
        return False


def _subir(ruta_bd):
    try:
        _api().upload_file(
            path_or_fileobj=str(ruta_bd),
            path_in_repo=ARCHIVO_REMOTO,
            repo_id=os.environ[VARIABLE_REPO].strip(),
            repo_type="dataset",
            commit_message="Instantánea automática de SIPAO-Naval")
    except Exception as e:
        print(f"  ⚠ No se pudo respaldar la base: {type(e).__name__}: {e}")


def respaldar(ruta_bd=None, forzar=False):
    """Sube la base en segundo plano, sin bloquear la respuesta al usuario.

    Agrupa ráfagas: si acaba de respaldar hace menos de 20 s, no repite
    (una importación hace muchas escrituras seguidas).
    """
    global _ultimo_respaldo
    if not _configurado():
        return False
    from backend.app import db
    ruta = Path(ruta_bd) if ruta_bd else db.ruta_bd_activa()
    if not ruta.exists():
        return False

    with _lock:
        ahora = time.time()
        if not forzar and (ahora - _ultimo_respaldo) < _INTERVALO_MIN:
            return False
        _ultimo_respaldo = ahora

    threading.Thread(target=_subir, args=(ruta,), daemon=True).start()
    return True

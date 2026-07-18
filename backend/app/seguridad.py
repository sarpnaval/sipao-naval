"""SIPAO-Naval · Control de escritura para la instancia publicada.

DEFECTO QUE ESTE MÓDULO CORRIGE (detectado el 18-jul-2026)
----------------------------------------------------------
Al publicar el aplicativo en internet, los endpoints de escritura
(importación de datos, registro directo de movimientos y panel de
configuración) quedarían ABIERTOS: cualquiera podría alterar los
parámetros de costeo o dejar texto arbitrario en la bitácora de
auditoría de un sistema presentado ante un jurado militar.

Cómo funciona
-------------
- Si la variable de entorno `SIPAO_TOKEN_ESCRITURA` NO está definida
  (caso del uso local y de las pruebas), la escritura queda abierta y el
  comportamiento es idéntico al de siempre: las 220 pruebas no cambian.
- Si está definida (caso de la instancia publicada), toda escritura exige
  la cabecera `X-Sipao-Token` con ese valor.

Esto NO es un sistema de autenticación de usuarios: es una llave de
operación para la demostración. La autenticación por rol con credenciales
institucionales es un hito de la fase 1 del piloto, cuando el sistema
opere sobre datos reales dentro del perímetro de la Armada.
"""

import os

from fastapi import Header, HTTPException, Request

CABECERA = "X-Sipao-Token"
VARIABLE = "SIPAO_TOKEN_ESCRITURA"

# Métodos que NO modifican estado: siempre libres.
METODOS_LECTURA = frozenset({"GET", "HEAD", "OPTIONS"})


def escritura_protegida():
    """True si esta instancia exige llave para escribir."""
    return bool(os.environ.get(VARIABLE, "").strip())


def exigir_token(request: Request, x_sipao_token: str = Header(default="")):
    """Dependencia FastAPI para los routers que contienen escritura.

    Se aplica a nivel de router y decide por MÉTODO, no por endpoint: la
    consulta (GET) queda siempre libre y toda escritura queda protegida,
    incluidos los endpoints que se añadan en el futuro sin que nadie tenga
    que acordarse de protegerlos. Es la opción a prueba de olvidos.
    """
    if request.method in METODOS_LECTURA:
        return
    esperado = os.environ.get(VARIABLE, "").strip()
    if not esperado:
        return                      # modo local: sin restricción
    if x_sipao_token != esperado:
        raise HTTPException(
            status_code=401,
            detail=("Escritura no autorizada. Esta instancia publicada exige "
                    "la clave de operación; la consulta es libre. Para operar "
                    "sin restricción, use la versión local del aplicativo."))

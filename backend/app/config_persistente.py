"""SIPAO-Naval · Persistencia de la configuración del sistema.

DEFECTO QUE ESTE MÓDULO CORRIGE (detectado el 18-jul-2026)
----------------------------------------------------------
El panel de configuración mutaba los diccionarios en memoria de
`backend/motor/costeo.py` y solo guardaba en la base la BITÁCORA del
cambio. Al reiniciar el proceso, los parámetros volvían a los valores de
fábrica mientras la bitácora seguía afirmando que se habían cambiado: el
registro de auditoría dejaba de concordar con el estado real del sistema.
En un sistema que se presenta ante un jurado militar —y que aspira a
gobernar decisiones de presupuesto— eso es inaceptable.

Aquí se guarda el valor EFECTIVO de cada parámetro y se reaplica al
arrancar, de modo que bitácora y estado siempre coincidan.

Los valores se serializan como texto y se reconstruyen con el tipo que
tenga el valor de fábrica (float, int o texto), para no depender de un
esquema de tipos aparte.
"""

import copy
from datetime import datetime

from backend.motor import costeo

SECCIONES = ("parametros", "modelos", "operaciones", "tipos")


def _contenedor(seccion):
    return {
        "parametros": costeo.PARAMETROS,
        "modelos": costeo.MODELOS,
        "operaciones": costeo.OPERACIONES,
        "tipos": costeo.TIPOS,
    }[seccion]


def _leer_actual(seccion, clave, campo):
    """Valor vigente de un campo, siguiendo la notación con punto
    (`consumo_gal_h.economico`, `fijos.remuneraciones`)."""
    cont = _contenedor(seccion)
    if clave not in cont:
        return None
    destino = cont[clave]
    if "." in campo:
        raiz, sub = campo.split(".", 1)
        return (destino.get(raiz) or {}).get(sub)
    if seccion == "parametros" and campo == "valor":
        return destino.get("valor")
    return destino.get(campo)


def _escribir(seccion, clave, campo, valor):
    """Aplica un valor sobre los diccionarios del motor, convirtiéndolo al
    tipo del valor vigente. Devuelve True si se aplicó."""
    cont = _contenedor(seccion)
    if clave not in cont:
        return False
    destino = cont[clave]
    actual = _leer_actual(seccion, clave, campo)

    convertido = valor
    if isinstance(actual, bool):
        convertido = str(valor).lower() in ("1", "true", "sí", "si")
    elif isinstance(actual, int) and not isinstance(actual, bool):
        try:
            convertido = int(float(valor))
        except (TypeError, ValueError):
            return False
    elif isinstance(actual, float):
        try:
            convertido = float(valor)
        except (TypeError, ValueError):
            return False

    if "." in campo:
        raiz, sub = campo.split(".", 1)
        if raiz not in destino or not isinstance(destino[raiz], dict):
            return False
        destino[raiz][sub] = convertido
    else:
        destino[campo] = convertido
    return True


def guardar_valor(conexion, seccion, clave, campo, valor,
                  origen=None, fuente=None):
    """Persiste un valor de configuración (INSERT OR REPLACE)."""
    conexion.execute(
        """INSERT OR REPLACE INTO configuracion_valores
           (seccion, clave, campo, valor, origen, fuente, actualizado)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (seccion, clave, campo, str(valor), origen, fuente,
         datetime.now().isoformat(timespec="seconds")))


def olvidar_todo(conexion):
    """Borra los valores aplicados: el sistema vuelve a los referenciales.
    NO toca la bitácora — la restauración se registra como un evento más."""
    conexion.execute("DELETE FROM configuracion_valores")


def cargar_configuracion(conexion):
    """Reaplica sobre el motor los valores guardados. Se llama al arrancar.

    Devuelve (aplicados, ignorados). Un valor se ignora si su clave ya no
    existe en el motor (p. ej. un modelo retirado del catálogo): así una
    configuración vieja nunca impide que el sistema arranque.
    """
    try:
        filas = conexion.execute(
            """SELECT seccion, clave, campo, valor, origen, fuente
               FROM configuracion_valores"""
        ).fetchall()
    except Exception:
        return 0, 0                       # base sin la tabla todavía

    # Fotografía de los valores DE FÁBRICA. Se toma aquí porque esta función
    # corre al arrancar, antes de que nada haya tocado los diccionarios del
    # motor: si más abajo la configuración guardada resulta inaplicable, este
    # es el estado sano al que se puede volver para que el servicio encienda.
    fabrica = {s: copy.deepcopy(_contenedor(s)) for s in SECCIONES}

    aplicados, ignorados = 0, 0
    for f in filas:
        seccion = f["seccion"] if hasattr(f, "keys") else f[0]
        clave = f["clave"] if hasattr(f, "keys") else f[1]
        campo = f["campo"] if hasattr(f, "keys") else f[2]
        valor = f["valor"] if hasattr(f, "keys") else f[3]
        origen = f["origen"] if hasattr(f, "keys") else f[4]
        fuente = f["fuente"] if hasattr(f, "keys") else f[5]

        if seccion not in SECCIONES:
            ignorados += 1
            continue
        try:
            escrito = _escribir(seccion, clave, campo, valor)
        except Exception as e:
            # Un valor guardado jamás puede impedir que el sistema encienda.
            print(f"  (configuración ignorada, {seccion}.{clave}.{campo}: "
                  f"{type(e).__name__})")
            escrito = False
        if escrito:
            cont = _contenedor(seccion)
            if origen:
                cont[clave]["origen"] = origen
            if fuente is not None and seccion == "parametros":
                cont[clave]["fuente"] = fuente
            aplicados += 1
        else:
            ignorados += 1

    if aplicados:
        try:
            costeo._refrescar_clases()
        except Exception as e:
            # EL SEGURO QUE IMPORTA (18-jul-2026)
            # -----------------------------------
            # Un valor guardado con un subcampo inexistente (p. ej. un typo
            # como `fijos.remuneracion`) se persiste como TEXTO y aquí hace
            # reventar el recálculo. Sin este seguro, el arranque de FastAPI
            # aborta y el servicio NO VUELVE A LEVANTAR NUNCA: el valor
            # venenoso viaja dentro de la instantánea restaurada, así que
            # reiniciar y redesplegar tampoco lo arreglan, y la única salida
            # es editar la base a mano.
            #
            # Ante eso se prefiere arrancar con los valores de fábrica y
            # decirlo, que es justo lo que promete el docstring de arriba:
            # una configuración vieja nunca impide que el sistema arranque.
            print(f"  ⚠ La configuración guardada no se pudo aplicar "
                  f"({type(e).__name__}: {e}).")
            print("    Se arranca con los valores referenciales de fábrica. "
                  "Revise el panel de configuración y vuelva a guardar.")
            for nombre, valores in fabrica.items():
                _contenedor(nombre).clear()
                _contenedor(nombre).update(valores)
            costeo._refrescar_clases()
            return 0, aplicados + ignorados
    return aplicados, ignorados

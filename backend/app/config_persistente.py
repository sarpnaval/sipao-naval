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
        if _escribir(seccion, clave, campo, valor):
            cont = _contenedor(seccion)
            if origen:
                cont[clave]["origen"] = origen
            if fuente is not None and seccion == "parametros":
                cont[clave]["fuente"] = fuente
            aplicados += 1
        else:
            ignorados += 1

    if aplicados:
        costeo._refrescar_clases()
    return aplicados, ignorados

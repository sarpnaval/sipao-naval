# SIPAO-Naval

**Sistema Integral de Planificación y Alistamiento Operativo** — plataforma de apoyo a la
decisión de mando para las unidades guardacostas de la Armada del Ecuador.

Propuesta al Concurso de Innovación Naval 2026 (DINDES).

## Qué responde

Con el presupuesto asignado: **qué unidades pueden operar**, **cuántos días de mar se sostienen**
y **qué operaciones quedan cubiertas** — priorizando por la doctrina de empleo, con la salvaguarda
de la vida humana en el mar atendida primero.

## Módulos

| Módulo | Qué hace |
|---|---|
| **Alistamiento operativo** | Optimiza el alistamiento bajo restricción presupuestaria (*Readiness-Based Sparing*): maximiza las unidades listas para operar y muestra cuánto alistamiento cuesta cada recorte. |
| **Costeo de operación** | Traduce el presupuesto en días de mar y cobertura del plan. Costo del día de mar desglosado por rubros (combustible por régimen de velocidad, lubricantes, mantenimiento preventivo por hora de navegación, repuestos, racionamiento) con dos tarifas: plena para justificar, marginal para decidir. |
| **Abastecimiento predictivo (SARP)** | Qué pedir, cuánto y con qué urgencia. Clasificación ABC/XYZ/VED, pronóstico Holt/Croston, stock de seguridad, punto de reorden y alertas explicadas. |
| **Configuración** | Todo parámetro es configurable por el reparto, con su procedencia declarada y bitácora de auditoría. |

## Datos

Los datos son **simulados y referenciales**. Los coeficientes de costo, los días del plan y los
parámetros vienen con valores de arranque para que el sistema opere desde el primer día; al
implementarse, cada reparto carga sus cifras reales.

## Ejecución local

```bash
pip install -r requirements.txt
python -m backend.app.arranque      # crea y siembra la base
uvicorn backend.app.main:app --port 8000
```

## Variables de entorno

| Variable | Para qué |
|---|---|
| `SARP_BD` | Ruta del archivo de base de datos |
| `SIPAO_TOKEN_ESCRITURA` | Si está definida, la escritura exige la cabecera `X-Sipao-Token`. Sin ella, la escritura queda abierta (uso local). |
| `HF_TOKEN`, `SIPAO_REPO_RESPALDO` | Respaldo automático de la base en un repositorio privado (opcional). |

Software libre. Desarrollado por talento naval.

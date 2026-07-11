# TASK: Implementar Sistema de Contexto Obligatorio Permanente

**Rol:** Senior Python Engineer y Tech Lead del proyecto Retirement Advisor.

## Objetivo Final

Crear un mecanismo para que **tú (Claude Code) y cualquier otro AI coding assistant (Grok Build, etc.)** siempre lean y tengan en cuenta el contexto completo y actualizado del proyecto **antes de generar cualquier plan o código**.

Esto evita que el AI trabaje con información desactualizada y mantiene la coherencia a largo plazo.

## Requerimientos

Implementa todo lo necesario para lograr lo siguiente:

1. **Archivo de Contexto Centralizado**
   - Crear un nuevo archivo: `docs/CONTEXT.md` (o `PROJECT_CONTEXT.md`)
   - Este archivo debe contener una versión consolidada y actualizada de:
     - Descripción del proyecto y filosofía
     - Arquitectura actual (capas, módulos clave)
     - Estructura de archivos importante
     - Reglas de estilo y estándares del proyecto
     - Estado actual de features clave (Scoring, Moat, Optimizer, Multi-Goal, AI, etc.)
     - Limitaciones conocidas
     - Últimos cambios importantes

2. **Sistema de Recordatorio Obligatorio**
   - Crear un archivo `docs/PROMPT_INSTRUCTIONS.md` con el siguiente contenido:

# INSTRUCCIONES OBLIGATORIAS PARA CUALQUIER AI CODING (Claude Code / Grok Build)

Antes de generar CUALQUIER plan, fix o nueva feature, HAZ SIEMPRE lo siguiente:

1. Lee completamente el archivo `docs/CONTEXT.md`
2. Lee el archivo `config.py` (es la fuente de verdad de thresholds y perfiles)
3. Revisa `analysis/prompts.py` si vas a tocar IA
4. Revisa `docs/ROADMAP.md` y `docs/CHANGELOG.md`

Incluye al inicio de tu respuesta:
"✅ He leído CONTEXT.md actualizado"

Nunca propongas cambios sin haber cargado primero este contexto.

Integración en el Flujo
Actualizar docs/MAINTENANCE.md explicando que todo prompt futuro debe comenzar incluyendo la instrucción de leer CONTEXT.md
Crear un script simple scripts/refresh_context.py que ayude a mantener actualizado docs/CONTEXT.md

Actualización Inicial
Generar la primera versión completa de docs/CONTEXT.md basada en el estado actual del proyecto (usando el resumen ejecutivo original + estado actual).


Entregables

Archivo docs/CONTEXT.md (completo y bien estructurado)
Archivo docs/PROMPT_INSTRUCTIONS.md
Actualización de docs/MAINTENANCE.md
Script scripts/refresh_context.py
Cualquier otro archivo o modificación necesaria

El objetivo final es que a partir de ahora, tanto tú como Grok, siempre lean este contexto antes de planificar o codificar cualquier cosa.
Por favor, implementa todo de forma profesional y limpia.
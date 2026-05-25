# Contribuir a Retirement Advisor

Gracias por tu interés en mejorar el proyecto. Toda contribución — desde un reporte de bug hasta una nueva funcionalidad — es bienvenida y apreciada.

---

## Antes de empezar

Retirement Advisor es una herramienta personal de análisis de inversiones. Antes de abrir un PR grande, abrí primero un **Issue** para discutir el cambio. Así evitamos trabajo duplicado y nos aseguramos de que la idea encaje con la dirección del proyecto.

---

## Reportar bugs

1. Buscá en los [Issues existentes](https://github.com/fcalvino/retirement-advisor/issues) para ver si ya fue reportado.
2. Si no existe, abrí un nuevo Issue con:
   - **Descripción clara** del problema (¿qué esperabas? ¿qué pasó?)
   - **Pasos para reproducirlo** (ticker, perfil, configuración, etc.)
   - **Mensajes de error** del log (`logs/retirement_advisor.log`) si aplica
   - **Versión de Python** y sistema operativo

No hay un formato estricto — con que sea claro y reproducible, es suficiente.

---

## Proponer nuevas ideas

Abrí un Issue con el tag `enhancement` y describí:
- **Qué problema resuelve** la idea
- **Cómo lo implementarías** (si tenés una propuesta concreta)
- **Impacto en el análisis** (¿cambia la metodología de scoring, optimizer, etc.?)

Las ideas más fáciles de aceptar son las que no rompen la metodología existente y tienen tests.

---

## Setup de desarrollo

```bash
git clone https://github.com/fcalvino/retirement-advisor.git
cd retirement-advisor

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Editá .env con tu configuración (AI key es opcional para desarrollo)
```

Para correr el dashboard localmente:

```bash
streamlit run dashboard/app.py
```

---

## Tests

Todos los PRs deben incluir tests para el código nuevo. El proyecto usa `pytest`:

```bash
# Correr todos los tests
pytest tests/ -v

# Correr tests de un módulo específico
pytest tests/test_scoring.py -v

# Correr con output detallado en caso de falla
pytest tests/ -v --tb=short
```

Los tests de Monte Carlo y Optimizer mockean `get_history` para no hacer llamadas de red. Seguí ese patrón si tu cambio toca código que llama a Yahoo Finance.

```python
# Ejemplo de mock en tests
from unittest.mock import patch

with patch("data.fetcher.get_history", return_value=mock_df):
    result = optimizer.optimize(symbols)
```

**Cobertura actual**: 133 tests. Un PR que reduce la cobertura sin justificación será pedido a reescribir.

---

## Estilo de código

El proyecto usa **Ruff** para linting y formato:

```bash
# Verificar
ruff check .

# Auto-corregir imports y problemas simples
ruff check . --fix
```

La configuración está en `ruff.toml`. Los puntos principales:
- Líneas de hasta 100 caracteres
- Imports ordenados automáticamente (isort via Ruff)
- Sin comentarios que expliquen qué hace el código — solo el porqué cuando no es obvio

Para módulos de análisis (`analysis/`, `portfolio/`), preferí funciones puras y tipado explícito. Para código de dashboard (`dashboard/`), la legibilidad sobre la elegancia.

---

## Proceso para abrir un PR

1. Creá un branch desde `main`:
   ```bash
   git checkout -b feat/mi-nueva-funcionalidad
   ```

2. Hacé tus cambios, con tests.

3. Verificá que el linter pase y los tests corran:
   ```bash
   ruff check . && pytest tests/ -v
   ```

4. Abrí el PR contra `main` con una descripción que incluya:
   - **¿Qué cambia?** (breve)
   - **¿Por qué?** (motivación o Issue relacionado)
   - **¿Cómo probarlo?** (pasos manuales si aplica)

5. Respondé a los comentarios de revisión. Los PRs se mergean con squash para mantener un historial limpio.

---

## Convenciones de commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(optimizer): add sector concentration constraint
fix(screener): handle missing dividend data gracefully
docs(moat): clarify Wide threshold rationale
perf(dashboard): cache Monte Carlo results in session state
test(scoring): add edge cases for zero-revenue companies
```

Tipos comunes: `feat`, `fix`, `perf`, `docs`, `test`, `refactor`, `chore`.

---

## Áreas donde las contribuciones son especialmente bienvenidas

- **Nuevos proveedores AI**: integrar modelos adicionales en `analysis/ai_analyzer.py`
- **Nuevas dimensiones de Moat**: ampliar el análisis cuantitativo en `analysis/moat.py`
- **Escenarios de stress test**: agregar nuevas crisis históricas en `portfolio/stress_test.py`
- **Cobertura de tests**: especialmente para `analysis/fundamental.py` y `data/fetcher.py`
- **Documentación**: traducciones, ejemplos, aclaraciones en `docs/`
- **Mejoras de UX**: el dashboard siempre puede ser más claro para el usuario final

---

## Código de conducta

Tratá a las demás personas con respeto. Los desacuerdos técnicos son normales — las discusiones deben ser sobre el código, no sobre las personas.

---

## Preguntas

Abrí un Issue con el tag `question`. Es la forma más rápida de obtener una respuesta y deja registro para otros con la misma duda.

# 📈 Optimizer — Brainstorming

> **Qué es hoy:** la pantalla más grande del producto (60 KB). Construye una cartera
> óptima (Mean-Variance) según 3 perfiles de riesgo + presets de retiro, con
> glide path automático, núcleo determinístico, consejo de IA y tabla de
> asignación con score/viento. Captura: `_screenshots/06_optimizer.png`

Es el motor más sofisticado y el más intimidante. La portada de la pantalla está
muy bien (tarjetas de perfil + presets), pero después llega una catarata de tabs y
tablas. Oportunidad: hacerlo igual de potente pero **más conversado**.

## Ideas

### Idea 1 — Resultado en una frase antes de las tablas
- **Qué:** "Esta cartera busca crecer al máximo; rinde ~X%, con riesgo ~Y%, y cumple
  todos tus límites." arriba de todo.
- **Por qué:** las 4 tabs (Cartera/Frontera/Métricas/Rebalanceo) son para validar;
  la conclusión tiene que estar primero.
- **Tipo:** UX / UI · **Esfuerzo:** Bajo

### Idea 2 — "Por qué entró / por qué quedó afuera"
- **Qué:** para cada ticker incluido y para los principales excluidos, una razón
  corta.
- **Por qué:** el optimizador es una caja negra para el usuario; explicarlo genera
  confianza y enseña.
- **Tipo:** UX / IA · **Esfuerzo:** Medio

### Idea 3 — Editar la cartera y ver el impacto al toque
- **Qué:** permitir subir/bajar un peso manualmente y mostrar cómo cambian retorno,
  riesgo y cumplimiento de límites.
- **Por qué:** la gente quiere "tocar". Un optimizador que no deja ajustar se siente
  impuesto. (El libro personal ya valida esta necesidad de control.)
- **Tipo:** UX / Técnica · **Esfuerzo:** Alto

### Idea 4 — Restricciones personalizadas simples
- **Qué:** "máximo 5% en crypto", "nada de tabaco", "mínimo 30% en dividendos", con
  switches.
- **Por qué:** cada inversor tiene reglas propias (éticas, de exposición). Hoy solo
  se eligen perfiles cerrados.
- **Tipo:** Técnica / UX · **Esfuerzo:** Alto

### Idea 5 — Comparar la cartera óptima vs la actual
- **Qué:** mostrar lado a lado tu cartera real y la propuesta, con los trades para
  pasar de una a la otra.
- **Por qué:** el optimizador produce un ideal; el valor está en el camino desde lo
  que tenés (ya existe la lógica de trades de alineación — traerla acá).
- **Tipo:** Flujo · **Esfuerzo:** Medio

### Idea 6 — "Guardar como plan" directo desde el resultado
- **Qué:** un botón que consolide la cartera optimizada en Mi Plan sin pasos extra.
- **Por qué:** es el paso natural siguiente; hoy el journey lo sugiere pero podría
  ser de un clic.
- **Tipo:** Flujo · **Esfuerzo:** Bajo

### Idea 7 — Frontera eficiente explicada
- **Qué:** en vez de un scatter de 300 puntos, marcar "tu cartera", "máximo retorno"
  y "mínimo riesgo" con etiquetas claras.
- **Por qué:** la frontera eficiente es preciosa para un experto e incomprensible
  para el resto; etiquetarla la hace útil para todos.
- **Tipo:** UI / UX · **Esfuerzo:** Bajo

### Idea 8 — Sensibilidad de la cartera ("¿qué tan frágil es?")
- **Qué:** mostrar cuánto cambia la cartera si movés un poco los supuestos de retorno.
- **Por qué:** las carteras Mean-Variance son famosas por ser inestables; mostrarlo
  evita falsa precisión.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 9 — Optimización orientada a la meta, no solo al perfil
- **Qué:** "quiero $X en 20 años aportando $Y/mes" → la cartera que maximiza la
  probabilidad de lograrlo.
- **Por qué:** el inversor piensa en metas, no en "vol ≤ 18%". Une optimizer con
  Monte Carlo y metas (ya hay piezas; falta el flujo único).
- **Tipo:** Flujo / Técnica · **Esfuerzo:** Alto

### Idea 10 — Métodos alternativos además de Mean-Variance
- **Qué:** ofrecer "paridad de riesgo" o Black-Litterman (ya existe el archivo) como
  opciones, explicando cuándo conviene cada uno.
- **Por qué:** Mean-Variance puro concentra mucho; alternativas dan carteras más
  robustas y diversas.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 11 — Advertencia de costos al rebalancear seguido
- **Qué:** si el rebalanceo propone muchos trades chicos, avisar el costo/impuesto
  acumulado.
- **Por qué:** rebalancear de más erosiona el retorno; el producto es conservador y
  debería desalentarlo.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

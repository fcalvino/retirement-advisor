# 📐 Capa de Portfolio y Riesgo — Brainstorming (transversal)

> **Qué es hoy:** optimizador Mean-Variance (3 perfiles + glide path), Monte Carlo
> block-bootstrap con sesgo conservador y escenario realista, decumulación,
> sensibilidad, metas, stress test, Black-Litterman (existe el archivo) y el sizer
> del libro personal. Es el cerebro cuantitativo.

El motor es de nivel profesional. Las ideas apuntan a **robustez** (que los números
no engañen) y a **conectar las piezas** (hoy viven algo sueltas).

## Ideas

### Idea 1 — Un único flujo "de la meta a la cartera al plan"
- **Qué:** encadenar meta → optimización → simulación → plan en un solo recorrido en
  vez de pantallas separadas.
- **Por qué:** hoy el usuario debe orquestar a mano lo que el producto podría hilar
  solo; es el mayor salto de usabilidad posible con piezas ya existentes.
- **Tipo:** Flujo / Técnica · **Esfuerzo:** Alto

### Idea 2 — Carteras más robustas (no solo Mean-Variance)
- **Qué:** ofrecer paridad de riesgo o Black-Litterman como alternativas claras.
- **Por qué:** Mean-Variance puro tiende a concentrar y a ser inestable; alternativas
  dan carteras que el usuario sostiene mejor en el tiempo.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 3 — Mostrar la incertidumbre, no esconderla
- **Qué:** acompañar cada proyección con su rango y recordar que es un escenario, no
  una promesa (la transparencia realista vs conservador ya va en esa dirección).
- **Por qué:** la falsa precisión ("vas a tener $1.234.567") es peligrosa; el rango
  honesto educa.
- **Tipo:** UX / Técnica · **Esfuerzo:** Bajo

### Idea 4 — Modelar correlaciones que cambian en las crisis
- **Qué:** reflejar que en las crisis "todo cae junto" (las correlaciones suben).
- **Por qué:** los modelos que asumen correlaciones fijas subestiman el riesgo justo
  cuando más importa.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 5 — Renta fija y efectivo de verdad
- **Qué:** tratar bonos y liquidez como clases propias con su lógica, no como una
  acción más.
- **Por qué:** un plan de retiro serio necesita el amortiguador de la renta fija bien
  modelado.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 6 — Impuestos y costos integrados al motor
- **Qué:** que optimización y rebalanceo consideren el costo fiscal (no solo el
  retorno bruto).
- **Por qué:** lo que importa es el resultado después de impuestos; ignorarlos lleva a
  decisiones que pierden plata.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 7 — Rebalanceo inteligente (por bandas, no por calendario)
- **Qué:** rebalancear cuando algo se desvía mucho, no en fechas fijas, y avisar el
  costo.
- **Por qué:** rebalancear por bandas suele rendir más y operar menos; encaja con la
  filosofía conservadora.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 8 — Aportes y retiros irregulares
- **Qué:** soportar aportes que cambian y gastos puntuales (casa, universidad) en las
  proyecciones.
- **Por qué:** la vida real no es un flujo parejo; los grandes eventos dominan el
  resultado.
- **Tipo:** Técnica · **Esfuerzo:** Alto

### Idea 9 — Comparabilidad total entre escenarios
- **Qué:** asegurar que dos simulaciones/planes se comparen con las mismas reglas
  (mismas tiradas, mismos supuestos).
- **Por qué:** comparar peras con manzanas lleva a conclusiones falsas; la
  comparación apples-to-apples ya empezó (Fase J) y conviene extenderla.
- **Tipo:** Técnica · **Esfuerzo:** Medio

### Idea 10 — Explicar cada decisión del motor
- **Qué:** que el optimizador y el Monte Carlo siempre puedan responder "¿por qué
  este número?".
- **Por qué:** un motor explicable se confía y se aprende; uno opaco se desconfía o se
  obedece a ciegas (ambas malas).
- **Tipo:** UX / Técnica · **Esfuerzo:** Medio

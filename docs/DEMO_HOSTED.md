# Demo hosteada (Docker) — distribución sin multi-usuario

> Decisión de producto (auditoría backlog #13): **demo empaquetada**, no SaaS
> multiusuario con cuentas. Motivo: privacidad local-first, menor riesgo de
> compliance (“asesor regulado”), y valor inmediato para mostrar el producto.

## Qué es

Un contenedor que levanta Retirement Advisor en el puerto **8501**, con
persistencia de `data/` (planes, cache SQLite) y `reports/`. Es **un usuario por
instancia** (como la app local). Para varios usuarios, corré **una instancia por
persona** o un reverse-proxy con aislamiento — no hay login compartido.

## Requisitos

- Docker + Docker Compose v2
- ~2 GB de RAM recomendados en la primera corrida (deps + Streamlit)

## Arranque en 2 minutos

```bash
git clone https://github.com/fcalvino/retirement-advisor.git
cd retirement-advisor
cp .env.example .env   # opcional: API keys de IA / Telegram
docker compose up --build
```

Abrí `http://localhost:8501` (o la IP del host si lo publicás).

### Primera hora en la demo

1. En **Inicio**, tocá **🎁 Cargar y activar plan de ejemplo**.
2. Revisá **¿cómo viene tu plan?**, **qué hacer este año** y el PDF.
3. En **Simulaciones**, mirá realista vs conservador y las palancas si no llegás.
4. Opcional: **💬 Hablá con tu plan** (requiere `AI_*` en `.env`).

## Publicar detrás de un dominio (ejemplo)

```nginx
# reverse-proxy esbozo — TLS con tu certificado habitual
location / {
    proxy_pass http://127.0.0.1:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;
}
```

**No** expongas la demo a Internet sin HTTPS y sin asumir que es multi-tenant:
cualquiera con la URL ve/edita los mismos planes del volumen montado.

## Qué no incluye (a propósito)

- Cuentas de usuario, billing, roles de asesor
- Aislamiento multi-tenant de datos
- Certificación de asesoramiento financiero regulado

## Parar / limpiar

```bash
docker compose down
# los planes quedan en ./data — borrá el directorio solo si querés reset total
```

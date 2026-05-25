"""
Startup configuration validator.

Checks that required and optional settings are sane before the app
runs. Returns a list of (level, message) tuples — never raises.

Levels: "error" (app cannot work), "warning" (degraded), "info" (OK).

Usage:
    from config_validator import validate_config
    issues = validate_config()
"""

from __future__ import annotations

import os
import sys
from typing import List, Tuple

from loguru import logger

Issue = Tuple[str, str]   # (level, message)


def _hermes_oauth_available(provider: str) -> bool:
    """
    Mirror the credential-resolution logic in ai_analyzer._call_xai / _call_nous.
    Returns True only if ~/.hermes/hermes-agent exists AND the provider-specific
    resolver can produce credentials without raising.
    """
    hermes_path = os.path.expanduser("~/.hermes/hermes-agent")
    if not os.path.isdir(hermes_path):
        return False
    if hermes_path not in sys.path:
        sys.path.insert(0, hermes_path)
    try:
        if provider == "xai":
            from hermes_cli.auth import resolve_xai_oauth_runtime_credentials
            resolve_xai_oauth_runtime_credentials()
        else:  # nous
            from hermes_cli.auth import resolve_nous_runtime_credentials
            resolve_nous_runtime_credentials()
        return True
    except Exception:
        return False


def validate_config() -> List[Issue]:
    issues: List[Issue] = []

    # ------------------------------------------------------------------ #
    #  AI Configuration                                                    #
    # ------------------------------------------------------------------ #
    ai_enabled = os.getenv("AI_ENABLED", "").lower() in ("true", "1", "yes")
    provider = os.getenv("AI_PROVIDER", "claude").lower()

    # Providers that can authenticate via Hermes OAuth (no static API key required)
    _OAUTH_PROVIDERS = {"xai", "nous"}

    if ai_enabled:
        key_map = {
            "claude": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "xai":    "XAI_API_KEY",
            "nous":   "NOUS_API_KEY",
        }
        key_var = key_map.get(provider, "ANTHROPIC_API_KEY")
        api_key = os.getenv(key_var, "") or os.getenv("AI_API_KEY", "")

        if provider in _OAUTH_PROVIDERS and not api_key:
            hermes_oauth = _hermes_oauth_available(provider)
        else:
            hermes_oauth = False

        if provider in _OAUTH_PROVIDERS and hermes_oauth:
            issues.append(("info", f"AI habilitado — proveedor: {provider} (Hermes OAuth)"))
        elif not api_key:
            issues.append((
                "warning",
                f"AI_ENABLED=true pero {key_var} no está configurada. "
                "El sistema usará el motor de decisión rule-based.",
            ))
        elif len(api_key) < 20:
            issues.append((
                "warning",
                f"{key_var} parece inválida (muy corta). Verificá tu API key.",
            ))
        else:
            issues.append(("info", f"AI habilitado — proveedor: {provider} (API Key)"))
    else:
        issues.append(("info", "AI deshabilitado — usando motor rule-based."))

    # ------------------------------------------------------------------ #
    #  Cache TTL                                                           #
    # ------------------------------------------------------------------ #
    try:
        ttl = int(os.getenv("CACHE_TTL_HOURS", "24"))
        if ttl < 1:
            issues.append(("warning", f"CACHE_TTL_HOURS={ttl} es muy bajo. Recomendado: 24."))
        elif ttl > 168:
            issues.append(("warning", f"CACHE_TTL_HOURS={ttl} (>7 días) puede causar datos muy desactualizados."))
    except ValueError:
        issues.append(("error", "CACHE_TTL_HOURS no es un número entero válido."))

    # ------------------------------------------------------------------ #
    #  Email alerts                                                        #
    # ------------------------------------------------------------------ #
    email_from = os.getenv("EMAIL_FROM", "")
    email_to   = os.getenv("EMAIL_TO", "")
    smtp_pass  = os.getenv("SMTP_PASSWORD", "")

    if email_from or email_to:
        missing = []
        if not email_from:
            missing.append("EMAIL_FROM")
        if not email_to:
            missing.append("EMAIL_TO")
        if not smtp_pass:
            missing.append("SMTP_PASSWORD")
        if missing:
            issues.append((
                "warning",
                f"Configuración de email incompleta — faltan: {', '.join(missing)}. "
                "Las alertas por email no funcionarán.",
            ))
        else:
            issues.append(("info", f"Email configurado: {email_from} → {email_to}"))

    # ------------------------------------------------------------------ #
    #  Telegram alerts                                                     #
    # ------------------------------------------------------------------ #
    tg_token   = os.getenv("TELEGRAM_TOKEN", "")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if tg_token or tg_chat_id:
        if not tg_token:
            issues.append(("warning", "TELEGRAM_CHAT_ID configurado pero falta TELEGRAM_TOKEN."))
        elif not tg_chat_id:
            issues.append(("warning", "TELEGRAM_TOKEN configurado pero falta TELEGRAM_CHAT_ID."))
        else:
            issues.append(("info", "Telegram configurado."))

    # ------------------------------------------------------------------ #
    #  Report config                                                       #
    # ------------------------------------------------------------------ #
    try:
        report_day = int(os.getenv("REPORT_DAY", "1"))
        if not (1 <= report_day <= 28):
            issues.append(("warning", f"REPORT_DAY={report_day} fuera de rango [1-28]. Usando 1."))
    except ValueError:
        issues.append(("error", "REPORT_DAY no es un número entero válido."))

    return issues


def log_config_issues(issues: List[Issue]) -> None:
    """Write config issues to the Loguru logger at startup."""
    for level, msg in issues:
        if level == "error":
            logger.error(f"[Config] {msg}")
        elif level == "warning":
            logger.warning(f"[Config] {msg}")
        else:
            logger.info(f"[Config] {msg}")

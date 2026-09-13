"""
AI Provider Manager: Módulo unificado para la gestión de motores de IA,
verificación de credenciales, control de estado y conmutación por error (Failover)
entre OpenAI Realtime API y Google Gemini Live API.
"""

import os
import logging
import threading
from typing import Callable, Optional, Dict, Any
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración de logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AIProviderManager")


class AIProvider:
    """Constantes para los nombres de proveedores de IA."""
    OPENAI = "OPENAI"
    GEMINI = "GEMINI"
    AUTO = "AUTO"


class AIProviderManager:
    """
    Gestiona el ciclo de vida del proveedor de IA activo, coordina la verificación
    de claves de acceso y ejecuta la conmutación en caliente (hot-failover)
    sin reiniciar el estado de la aplicación.
    """

    def __init__(self, on_provider_changed: Optional[Callable[[str, str], None]] = None):
        """
        Inicializa el administrador de proveedores.
        
        :param on_provider_changed: Callback invocado cuando el proveedor cambia.
                                     Firma: callback(nuevo_proveedor, motivo)
        """
        self._lock = threading.Lock()
        self.on_provider_changed = on_provider_changed
        
        # Leer variables de entorno
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        # Aceptar tanto GOOGLE_API_KEY como GEMINI_API_KEY
        self.gemini_key = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
        
        self.preferred_provider = os.getenv("PREFERRED_PROVIDER", AIProvider.OPENAI).upper().strip()
        self.auto_fallback_enabled = os.getenv("AUTO_FALLBACK", "true").lower() in ("true", "1", "yes")
        
        # Determinar proveedor inicial válido
        self.active_provider = self._resolve_initial_provider()
        self.last_error_reason: Optional[str] = None

        logger.info(
            f"AIProviderManager inicializado. Proveedor activo: {self.active_provider} "
            f"(Preferido: {self.preferred_provider}, Auto-Fallback: {self.auto_fallback_enabled})"
        )

    def _resolve_initial_provider(self) -> str:
        """Determina el proveedor inicial según la preferencia y la disponibilidad de credenciales."""
        openai_ready = bool(self.openai_key and not self.openai_key.startswith("sk-proj-your-openai"))
        gemini_ready = bool(self.gemini_key and not self.gemini_key.startswith("your_google"))

        if self.preferred_provider == AIProvider.OPENAI and openai_ready:
            return AIProvider.OPENAI
        elif self.preferred_provider == AIProvider.GEMINI and gemini_ready:
            return AIProvider.GEMINI
        elif openai_ready:
            return AIProvider.OPENAI
        elif gemini_ready:
            return AIProvider.GEMINI
        else:
            # Si ninguna está configurada adecuadamente, por defecto OpenAI para guiar al usuario
            return AIProvider.OPENAI

    def check_credentials(self) -> Dict[str, bool]:
        """
        Comprueba si las claves de API necesarias están presentes en el entorno.
        
        :return: Diccionario con el estado de credenciales para cada proveedor.
        """
        openai_valid = bool(self.openai_key and len(self.openai_key) > 10 and not self.openai_key.startswith("sk-proj-your"))
        gemini_valid = bool(self.gemini_key and len(self.gemini_key) > 10 and not self.gemini_key.startswith("your_google"))
        
        return {
            AIProvider.OPENAI: openai_valid,
            AIProvider.GEMINI: gemini_valid
        }

    def get_active_provider(self) -> str:
        """Retorna el nombre del proveedor actualmente activo."""
        with self._lock:
            return self.active_provider

    def set_active_provider(self, provider: str, reason: str = "Selección manual del usuario") -> bool:
        """
        Cambia manualmente el proveedor de IA activo si las credenciales existen.
        
        :param provider: 'OPENAI' o 'GEMINI'.
        :param reason: Motivo del cambio.
        :return: True si se cambió con éxito, False en caso contrario.
        """
        provider = provider.upper().strip()
        creds = self.check_credentials()

        with self._lock:
            if provider not in (AIProvider.OPENAI, AIProvider.GEMINI):
                logger.warning(f"Proveedor desconocido solicitado: {provider}")
                return False

            if not creds.get(provider, False):
                logger.warning(f"No se puede cambiar a {provider}: Clave de API no configurada o inválida.")
                return False

            if self.active_provider == provider:
                return True

            prev_provider = self.active_provider
            self.active_provider = provider
            logger.info(f"Proveedor cambiado de {prev_provider} a {self.active_provider}. Motivo: {reason}")

        if self.on_provider_changed:
            self.on_provider_changed(self.active_provider, reason)

        return True

    def trigger_fallback(self, error_reason: str) -> Optional[str]:
        """
        Ejecuta la conmutación en caliente (Hot-Failover) hacia el motor secundario.
        
        :param error_reason: Descripción técnica del fallo que originó la conmutación.
        :return: El nuevo proveedor activo o None si no hay respaldo disponible.
        """
        if not self.auto_fallback_enabled:
            logger.warning(f"Fallo detectado en {self.active_provider}: '{error_reason}', pero Auto-Fallback está desactivado.")
            return None

        creds = self.check_credentials()

        with self._lock:
            self.last_error_reason = error_reason
            current = self.active_provider
            
            # Determinar el proveedor alternativo
            target_provider = AIProvider.GEMINI if current == AIProvider.OPENAI else AIProvider.OPENAI

            logger.error(
                f"[FALLBACK TRIGGERED] Fallo en motor principal '{current}'. "
                f"Razón: {error_reason}. Conmutando hacia '{target_provider}'..."
            )

            # Verificar si el destino cuenta con credenciales
            if not creds.get(target_provider, False):
                logger.critical(
                    f"No se puede realizar Failover a '{target_provider}': "
                    f"Faltan credenciales válidas en .env para este motor."
                )
                return None

            self.active_provider = target_provider
            new_active = self.active_provider

        # Notificar al callback registrado (ej. GUI y Orquestador)
        if self.on_provider_changed:
            self.on_provider_changed(new_active, f"Failover automático por error: {error_reason}")

        return new_active

    def get_provider_badge_info(self) -> Dict[str, str]:
        """
        Retorna los textos y colores estilizados para la interfaz gráfica.
        
        :return: Diccionario con texto de insignia, color de fondo y descripción.
        """
        with self._lock:
            current = self.active_provider

        if current == AIProvider.OPENAI:
            return {
                "name": "OPENAI",
                "label": "OpenAI GPT-4o Realtime",
                "badge_text": "🟢 OPENAI REALTIME (GPT-4o)",
                "color": "#10a37f",       # Verde OpenAI
                "hover_color": "#0d8a6a",
                "accent_color": "#10a37f"
            }
        else:
            return {
                "name": "GEMINI",
                "label": "Google Gemini Live (3.1 Flash)",
                "badge_text": "🔵 GOOGLE GEMINI (LIVE API)",
                "color": "#1a73e8",       # Azul Google
                "hover_color": "#1558b0",
                "accent_color": "#4285f4"
            }

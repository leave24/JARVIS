"""
Wake Word Detector: Módulo para la detección de frases de activación ("Hola JARVIS", "Hey JARVIS"),
control del temporizador de seguimiento conversacional (Follow-up Window) y gestión
de estados de reposo/espera.
"""

import os
import re
import time
import unicodedata
import logging
from typing import Callable, Optional, Tuple, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("WakeWordDetector")


class WakeState:
    """Estados del ciclo de activación por voz."""
    DISABLED = "DISABLED"                # Modo escucha continua activa
    STANDBY = "STANDBY"                  # En espera de la palabra de activación
    ACTIVATED = "ACTIVATED"              # Palabra de activación recién detectada
    ACTIVE_LISTENING = "ACTIVE_LISTENING" # Escuchando comando del usuario
    SPEAKING = "SPEAKING"                # JARVIS respondiendo por voz


class WakeWordDetector:
    """
    Gestiona la máquina de estados de activación por voz de JARVIS.
    Permite activar al asistente por frases como 'Hola JARVIS' o 'Hey JARVIS',
    mantener una ventana de atención para preguntas de seguimiento (Follow-up window),
    y retornar a reposo por inactividad o despedidas explícitas.
    """

    def __init__(self, on_state_changed: Optional[Callable[[str, str], None]] = None):
        self.on_state_changed = on_state_changed

        # Leer configuración de entorno
        enabled_str = os.getenv("WAKE_WORD_ENABLED", "true").lower()
        self.is_enabled = enabled_str in ("true", "1", "yes")

        # Palabras de activación (separadas por comas)
        raw_wake = os.getenv("WAKE_WORDS", "hola jarvis,hey jarvis,jarvis,oye jarvis,ok jarvis")
        self.wake_words = [self._normalize_text(w) for w in raw_wake.split(",") if w.strip()]

        # Palabras de reposo / despedida
        raw_sleep = os.getenv("SLEEP_WORDS", "gracias jarvis,descansa,adios jarvis,duermete,silencio jarvis,hasta luego")
        self.sleep_words = [self._normalize_text(w) for w in raw_sleep.split(",") if w.strip()]

        # Tiempo límite de espera tras una respuesta antes de volver a Standby
        self.timeout_seconds = float(os.getenv("STANDBY_TIMEOUT_SECONDS", "15"))

        # Variables internas
        self.current_state = WakeState.STANDBY if self.is_enabled else WakeState.DISABLED
        self.last_activity_time = time.time()
        self.consecutive_active_turns = 0

        logger.info(
            f"WakeWordDetector inicializado. Modo Wake Word: {'ACTIVADO' if self.is_enabled else 'DESACTIVADO'}. "
            f"Frases: {self.wake_words}. Timeout: {self.timeout_seconds}s"
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normaliza el texto eliminando acentos, puntuación y convirtiendo a minúsculas."""
        if not text:
            return ""
        # Quitar diacríticos / tildes
        text_normalized = unicodedata.normalize('NFD', text)
        text_clean = "".join(c for c in text_normalized if unicodedata.category(c) != 'Mn')
        # Quitar signos de puntuación y dejar solo letras, números y espacios
        text_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', text_clean).lower()
        # Normalizar espacios repetidos
        return re.sub(r'\s+', ' ', text_clean).strip()

    def set_enabled(self, enabled: bool):
        """Activa o desactiva el modo Wake Word en caliente."""
        self.is_enabled = enabled
        prev_state = self.current_state
        if self.is_enabled:
            self.current_state = WakeState.STANDBY
        else:
            self.current_state = WakeState.DISABLED

        logger.info(f"Modo Wake Word cambiado a: {self.is_enabled} (Estado: {self.current_state})")
        if self.on_state_changed:
            self.on_state_changed(self.current_state, "Modo cambiado manualmente")

    def toggle_mode(self) -> bool:
        """Alterna el modo Wake Word y retorna el nuevo estado booleano."""
        self.set_enabled(not self.is_enabled)
        return self.is_enabled

    def check_wake_trigger(self, transcript: str) -> Tuple[bool, str]:
        """
        Analiza una transcripción de voz para determinar si contiene una frase de activación.
        
        :param transcript: Texto reconocido de la voz del usuario.
        :return: (is_wake_detected, cleaned_command_text)
        """
        if not transcript or not transcript.strip():
            return False, ""

        norm = self._normalize_text(transcript)

        # Si el modo Wake Word está desactivado, siempre se considera activo
        if not self.is_enabled:
            self.touch()
            return True, transcript

        # 1. Comprobar si ya estamos en ventana de atención activa (Follow-up activo)
        if self.current_state in (WakeState.ACTIVATED, WakeState.ACTIVE_LISTENING):
            if not self.is_follow_up_expired():
                self.touch()
                # Verificar si el usuario dijo una frase de despedida para forzar reposo
                if self.check_sleep_trigger(norm):
                    self.set_state(WakeState.STANDBY, "Despedida del usuario detectada")
                    return False, ""
                return True, transcript

        # 2. Si estamos en STANDBY, buscar la palabra de activación
        for wake_phrase in self.wake_words:
            # Coincidencia al inicio o como palabra completa
            pattern = r'\b' + re.escape(wake_phrase) + r'\b'
            match = re.search(pattern, norm)
            if match:
                logger.info(f"[WAKE WORD DETECTADO]: '{wake_phrase}' en transcripción '{transcript}'")
                self.set_state(WakeState.ACTIVATED, f"Activado por '{wake_phrase}'")
                self.touch()

                # Extraer el comando que sigue a la palabra de activación
                # Ej: "Hola JARVIS qué hora es" -> "qué hora es"
                end_pos = match.end()
                remainder = norm[end_pos:].strip()
                return True, remainder if remainder else transcript

        return False, ""

    def check_sleep_trigger(self, normalized_text: str) -> bool:
        """Comprueba si el texto contiene una orden de reposo o despedida."""
        for sleep_phrase in self.sleep_words:
            if sleep_phrase in normalized_text:
                logger.info(f"[SLEEP TRIGGER DETECTADO]: '{sleep_phrase}'")
                return True
        return False

    def touch(self):
        """Actualiza la marca de tiempo de última actividad y resetea el temporizador."""
        self.last_activity_time = time.time()

    def is_follow_up_expired(self) -> bool:
        """Verifica si la ventana de seguimiento conversacional ha expirado por inactividad."""
        if not self.is_enabled:
            return False
        elapsed = time.time() - self.last_activity_time
        return elapsed > self.timeout_seconds

    def check_and_update_timeout(self) -> bool:
        """
        Comprueba el temporizador. Si expiró y estaba activo, conmuta a STANDBY.
        
        :return: True si hubo transición a STANDBY por timeout.
        """
        if not self.is_enabled or self.current_state == WakeState.STANDBY:
            return False

        if self.is_follow_up_expired():
            logger.info(f"Ventana de seguimiento expirada tras {self.timeout_seconds}s de inactividad. Volviendo a STANDBY.")
            self.set_state(WakeState.STANDBY, "Timeout de inactividad")
            return True
        return False

    def set_state(self, new_state: str, detail: str = ""):
        """Actualiza el estado y notifica al callback registrado."""
        if self.current_state != new_state:
            prev = self.current_state
            self.current_state = new_state
            logger.info(f"Estado de WakeWord cambiado: {prev} -> {new_state} ({detail})")
            if self.on_state_changed:
                self.on_state_changed(new_state, detail)

    def get_display_badge_info(self) -> Tuple[str, str]:
        """
        Retorna el texto y color del badge según el estado de activación.
        
        :return: (badge_text, color_hex)
        """
        if not self.is_enabled:
            return "🟢 MODO CONTINUO", "#059669"
        
        if self.current_state == WakeState.STANDBY:
            return "💤 EN ESPERA ('Hola JARVIS')", "#64748b"
        elif self.current_state == WakeState.ACTIVATED:
            return "⚡ JARVIS ACTIVADO", "#f59e0b"
        elif self.current_state == WakeState.ACTIVE_LISTENING:
            return "🟢 ESCUCHANDO COMANDO", "#10b981"
        elif self.current_state == WakeState.SPEAKING:
            return "🔵 JARVIS HABLANDO", "#3b82f6"
        else:
            return "💤 EN ESPERA", "#64748b"

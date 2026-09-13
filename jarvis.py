"""
JARVIS: Orquestador Principal Asíncrono con Activación por Voz (Wake Word "Hola JARVIS"),
Memoria Dual (Corto Plazo + RAG Persistente ChromaDB), Supresión Avanzada de Auto-Eco (AEC),
VAD Dinámico, Bootstrapping Asíncrono con Warm-Up y Arquitectura Híbrida de Fallback (OpenAI + Gemini Live).
"""

import os
import sys
import json
import base64
import asyncio
import logging
import threading
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Normalizar credenciales de Google para evitar advertencia de API keys duplicadas en google_genai SDK
if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" in os.environ:
    if not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    del os.environ["GEMINI_API_KEY"]

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("JarvisOrchestrator")

# Importaciones locales de subsistemas
from bootstrap import SystemBootstrapper
from ai_provider_manager import AIProviderManager, AIProvider
from wake_word_detector import WakeWordDetector, WakeState
from gui import JarvisGUI
from audio_handler import AudioHandler
from memory_manager import MemoryManager
from system_control import SystemControl
from tools_config import OPENAI_REALTIME_TOOLS, GEMINI_TOOLS, execute_tool_call


class JarvisOrchestrator:
    """
    Orquestador maestro de JARVIS.
    Coordina el ciclo de vida completo:
    - Arranque asíncrono con verificación de hardware y Warm-Up de modelos (bootstrap.py).
    - Captura de audio de 30 ms a 24 kHz con supresión activa de auto-eco y VAD adaptativo.
    - Máquina de estados de Wake Word ("Hola JARVIS") con ventana de seguimiento.
    - Memoria dual: corto plazo de diálogo + RAG en RAM acelerado con ChromaDB.
    - Fallback en caliente entre OpenAI Realtime API y Google Gemini Live API.
    - Cierre seguro y ordenado (Graceful Shutdown) libre de fugas de tareas.
    """

    def __init__(self):
        logger.info("Inicializando subsistemas de JARVIS...")

        # 1. Administrador de Proveedores de IA y Failover
        self.provider_mgr = AIProviderManager(on_provider_changed=self._on_provider_changed_callback)

        # 2. Detector de Wake Word y Control de Estados
        self.wake_detector = WakeWordDetector(on_state_changed=self._on_wake_state_changed)

        # 3. Controladores de Audio, Memoria Dual y Sistema
        # Framing optimizado a 24 kHz / 30 ms (720 muestras)
        self.audio = AudioHandler(sample_rate=24000, chunk_size=720, preroll_seconds=1.5)
        self.memory = MemoryManager()
        self.system = SystemControl()

        # 4. Estados de ejecución y bucles asíncronos
        self.is_running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_current_engine_event: Optional[asyncio.Event] = None
        self._is_model_responding = False

        # 5. Construir Interfaz Gráfica (CustomTkinter con Grid Layout y Vúmetro Canvas)
        self.gui = JarvisGUI(
            on_toggle_connect=self.toggle_connection,
            on_toggle_mute=self.toggle_mute,
            on_toggle_wakeword=self.toggle_wakeword_mode,
            on_change_provider=self.change_provider_manual,
            on_reconnect=self.force_reconnect,
            on_close_requested=self.safe_shutdown,
            on_toggle_autostart=self.toggle_autostart
        )

        # Conectar callbacks de volumen al vúmetro dinámico de la GUI
        self.audio.set_volume_callback(self.gui.set_volume)

        # Configurar badges y controles iniciales en la GUI
        badge_info = self.provider_mgr.get_provider_badge_info()
        self.gui.update_provider_badge(
            text=badge_info["badge_text"],
            color=badge_info["color"],
            provider_name=badge_info["name"]
        )
        self.gui.update_wakeword_button(self.wake_detector.is_enabled)
        self.gui.set_autostart_switch_state(self.system.is_autostart_enabled())
        self._update_status_by_wake_state(self.wake_detector.current_state)

        # 6. Gestor de Arranque y Warm-Up Asíncrono (Bootstrap)
        self.bootstrapper = SystemBootstrapper(
            on_progress=self._on_bootstrap_progress,
            on_complete=self._on_bootstrap_complete
        )
        self.bootstrapper.register_shutdown_hook(self.safe_shutdown)
        self.bootstrapper.attach_signal_handlers()

        # Ejecutar verificación de hardware y Warm-Up de ChromaDB/embeddings en segundo plano
        self.bootstrapper.run_bootstrap_async(
            memory_manager=self.memory,
            audio_handler=self.audio
        )

        logger.info("JARVIS completamente estructurado. Esperando finalización del Warm-up...")

    # =========================================================================
    # CALLBACKS DE BOOTSTRAP Y WARM-UP
    # =========================================================================

    def _on_bootstrap_progress(self, message: str, progress: float):
        """Notificación de progreso de arranque hacia la consola de la GUI."""
        self.gui.add_log("SISTEMA", f"[WARM-UP {int(progress*100)}%] {message}")
        if not self.is_running:
            self.gui.update_status(f"WARM-UP: {int(progress*100)}%", "#d97706")

    def _on_bootstrap_complete(self, diag: Dict[str, Any]):
        """Notificación cuando el sistema está pre-calentado y listo."""
        t = diag.get("bootstrap_time_seconds", 0.0)
        self.gui.add_log("SISTEMA", f"Warm-up de memoria y audio completado con éxito en {t}s. Sistema 100% listo.")
        if not self.is_running:
            self._update_status_by_wake_state(self.wake_detector.current_state)

    # =========================================================================
    # CALLBACKS Y CONTROL DE ESTADO
    # =========================================================================

    def _on_provider_changed_callback(self, new_provider: str, reason: str):
        """Notificación de cambio de proveedor (manual o por failover)."""
        badge_info = self.provider_mgr.get_provider_badge_info()
        self.gui.update_provider_badge(
            text=badge_info["badge_text"],
            color=badge_info["color"],
            provider_name=badge_info["name"]
        )
        self.gui.add_log(
            "FALLBACK" if "Failover" in reason else "SISTEMA",
            f"Motor activo: {badge_info['label']}. {reason}"
        )

    def _on_wake_state_changed(self, new_state: str, detail: str):
        """Callback cuando cambia el estado de activación de Wake Word."""
        if self.is_running:
            self._update_status_by_wake_state(new_state)
            if new_state == WakeState.ACTIVATED:
                self.gui.add_log("WAKE", "¡Palabra de activación detectada! JARVIS en atención activa.")
            elif new_state == WakeState.STANDBY and detail:
                self.gui.add_log("SISTEMA", f"JARVIS en reposo. Di 'Hola JARVIS' para activar. ({detail})")

    def _update_status_by_wake_state(self, state: str):
        """Actualiza el badge de estado de la GUI según la máquina de estados."""
        if not self.is_running:
            self.gui.update_status("DESCONECTADO", "#475569")
            return

        if not self.wake_detector.is_enabled:
            self.gui.update_status("🟢 MODO CONTINUO", "#059669")
        elif state == WakeState.STANDBY:
            self.gui.update_status("💤 EN ESPERA ('Hola JARVIS')", "#64748b")
        elif state == WakeState.ACTIVATED:
            self.gui.update_status("⚡ JARVIS ACTIVADO", "#f59e0b")
        elif state == WakeState.ACTIVE_LISTENING:
            self.gui.update_status("🟢 ESCUCHANDO COMANDO", "#10b981")
        elif state == WakeState.SPEAKING:
            self.gui.update_status("🔵 JARVIS HABLANDO", "#3b82f6")

    def toggle_wakeword_mode(self):
        """Alterna entre el modo Wake Word ('Hola JARVIS') y Modo Continuo."""
        is_active = self.wake_detector.toggle_mode()
        self.gui.update_wakeword_button(is_active)
        mode_text = "Modo Wake Word ('Hola JARVIS') ACTIVADO." if is_active else "Modo Continuo (Siempre Escuchando) ACTIVADO."
        self.gui.add_log("SISTEMA", mode_text)
        self._update_status_by_wake_state(self.wake_detector.current_state)

    def toggle_mute(self):
        """Alterna el micrófono en silencio o activo."""
        is_muted = self.audio.toggle_mute()
        self.gui.update_mute_button(is_muted)
        self.gui.add_log("SISTEMA", "Micrófono silenciado." if is_muted else "Micrófono activado.")

    def toggle_autostart(self, enable: bool):
        """Alterna la configuración de inicio automático con el sistema."""
        msg = self.system.enable_autostart(enable)
        self.gui.add_log("SISTEMA", msg)

    def change_provider_manual(self, provider_name: str):
        """Cambio manual solicitado desde la interfaz."""
        success = self.provider_mgr.set_active_provider(provider_name, reason="Selección manual del usuario")
        if not success:
            self.gui.add_log("ERROR", f"No se pudo seleccionar {provider_name}. Verifique la API Key en .env.")
            badge_info = self.provider_mgr.get_provider_badge_info()
            self.gui.update_provider_badge(badge_info["badge_text"], badge_info["color"], badge_info["name"])
            return

        if self.is_running and self.loop and self._stop_current_engine_event:
            self.gui.add_log("SISTEMA", f"Conmutando en caliente hacia {provider_name}...")
            self.loop.call_soon_threadsafe(self._stop_current_engine_event.set)

    def force_reconnect(self):
        """Fuerza la reconexión inmediata del agente."""
        if self.is_running and self.loop and self._stop_current_engine_event:
            self.gui.add_log("SISTEMA", "Reconexión manual solicitada...")
            self.loop.call_soon_threadsafe(self._stop_current_engine_event.set)
        elif not self.is_running:
            self.toggle_connection()

    def toggle_connection(self):
        """Inicia o detiene la sesión de voz del agente."""
        if not self.is_running:
            self.is_running = True
            self.gui.update_connect_button(is_connected=True)
            self.gui.update_status("CONECTANDO...", "#d97706")
            self._loop_thread = threading.Thread(target=self._start_async_worker, daemon=True)
            self._loop_thread.start()
        else:
            self.is_running = False
            self.gui.update_connect_button(is_connected=False)
            self.gui.update_status("DESCONECTADO", "#475569")
            self.gui.add_log("SISTEMA", "Sesión de voz detenida por el usuario.")
            if self.loop and self._stop_current_engine_event:
                self.loop.call_soon_threadsafe(self._stop_current_engine_event.set)

    def safe_shutdown(self):
        """Apagado ordenado (Graceful Shutdown) de todos los subsistemas."""
        logger.info("Iniciando apagado seguro de JARVIS...")
        self.is_running = False
        if self.loop and self._stop_current_engine_event:
            try:
                self.loop.call_soon_threadsafe(self._stop_current_engine_event.set)
            except Exception:
                pass

        self.audio.close()
        logger.info("Recursos de JARVIS liberados correctamente.")

    def _start_async_worker(self):
        """Punto de entrada para el hilo de ejecución asíncrono."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._orchestrator_loop())
        except Exception as e:
            logger.error(f"Error en el loop asíncrono: {e}")
        finally:
            self.audio.close()
            try:
                # Cancelar y recolectar tareas pendientes
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self.loop.close()
            self.is_running = False
            self.gui.update_connect_button(is_connected=False)
            self.gui.update_status("DESCONECTADO", "#475569")

    # =========================================================================
    # BUCLE SUPERVISOR Y WATCHDOG DE INACTIVIDAD
    # =========================================================================

    async def _wake_word_watchdog_loop(self):
        """Tarea periódica en segundo plano que supervisa el timeout de la ventana de atención."""
        while self.is_running and not self._stop_current_engine_event.is_set():
            await asyncio.sleep(1.0)
            if not self._is_model_responding and not self.audio.is_playing():
                self.wake_detector.check_and_update_timeout()

    async def _orchestrator_loop(self):
        """Bucle supervisor que ejecuta el motor activo y gestiona el Failover en caliente."""
        while self.is_running:
            self._stop_current_engine_event = asyncio.Event()
            active_provider = self.provider_mgr.get_active_provider()
            logger.info(f"Iniciando sesión con motor: {active_provider}")

            watchdog_task = asyncio.create_task(self._wake_word_watchdog_loop())

            try:
                if active_provider == AIProvider.OPENAI:
                    await self._run_openai_realtime_engine()
                else:
                    await self._run_gemini_live_engine()

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Excepción en motor {active_provider}: {error_msg}")
                self.gui.add_log("ERROR", f"Fallo en {active_provider}: {error_msg}")

                if not self.is_running:
                    break

                new_provider = self.provider_mgr.trigger_fallback(error_msg)
                if new_provider:
                    self.gui.update_status("CONMUTANDO FAILOVER...", "#7c3aed")
                    self.gui.add_log("FALLBACK", f"Conmutando en caliente a {new_provider} en 2 segundos...")
                    await asyncio.sleep(2.0)
                    continue
                else:
                    self.gui.add_log("ERROR", "No hay más proveedores de contingencia disponibles con API Keys válidas.")
                    self.is_running = False
                    break
            finally:
                watchdog_task.cancel()

            if self.is_running and not self._stop_current_engine_event.is_set():
                await asyncio.sleep(1.0)

    # =========================================================================
    # MOTOR 1: OPENAI REALTIME API (FRAMING 30MS, VAD ADAPTATIVO)
    # =========================================================================

    async def _run_openai_realtime_engine(self):
        """Controlador de comunicación en tiempo real con OpenAI Realtime API."""
        import websockets

        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not openai_key or openai_key.startswith("sk-proj-your"):
            raise ValueError("OPENAI_API_KEY no configurada en .env.")

        model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
        voice = os.getenv("OPENAI_VOICE", "alloy")
        ws_url = f"wss://api.openai.com/v1/realtime?model={model}"

        headers = {
            "Authorization": f"Bearer {openai_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        self.audio.set_sample_rate(24000)
        self.audio.start_streams()
        self.gui.update_status("CONECTANDO A OPENAI...", "#d97706")

        async with websockets.connect(ws_url, extra_headers=headers) as ws:
            self._update_status_by_wake_state(self.wake_detector.current_state)
            self.gui.add_log("SISTEMA", f"Conexión WebSocket establecida con OpenAI Realtime ({model}).")

            full_context = self.memory.get_combined_context_for_prompt(recent_limit=6)
            system_prompt = (
                "Eres JARVIS, un asistente de voz inteligente de ultra-baja latencia, conciso, rápido y proactivo. "
                "Responde siempre en español de forma natural y directa. "
                "Tienes memoria permanente de todas las sesiones de conversación pasadas y recuerdas cada detalle. "
                "Tienes acceso a gestión completa de proyectos de programación y archivos, cálculos matemáticos, control de aplicaciones del sistema, consola y volumen.\n\n"
                f"{full_context}"
            )

            session_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],
                    "instructions": system_prompt,
                    "voice": voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500
                    },
                    "tools": OPENAI_REALTIME_TOOLS,
                    "tool_choice": "auto"
                }
            }
            await ws.send(json.dumps(session_config))

            # Pipelines desacoplados de transmisión y recepción
            sender_task = asyncio.create_task(self._openai_audio_sender(ws))
            receiver_task = asyncio.create_task(self._openai_event_receiver(ws))

            stop_task = asyncio.create_task(self._stop_current_engine_event.wait())
            # Esperar exclusivamente a la terminación de la conexión del receptor o señal de parada
            done, pending = await asyncio.wait(
                [receiver_task, stop_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            sender_task.cancel()
            for task in pending:
                task.cancel()

            for task in done:
                if task != stop_task and task.exception():
                    raise task.exception()

    async def _openai_audio_sender(self, ws):
        """Lee bloques de micrófono de 30 ms y los transmite a OpenAI con supresión de auto-eco."""
        while self.is_running and not self._stop_current_engine_event.is_set():
            is_ai_speaking = self._is_model_responding or self.audio.is_playing()
            if is_ai_speaking:
                # Pausar streaming de audio mientras la IA habla para evitar auto-eco y falsas interrupciones
                await asyncio.sleep(0.04)
                continue

            pcm_chunk = self.audio.read_input_chunk(is_ai_speaking=is_ai_speaking)

            if pcm_chunk and not self.audio.is_muted:
                base64_audio = base64.b64encode(pcm_chunk).decode("utf-8")
                event = {
                    "type": "input_audio_buffer.append",
                    "audio": base64_audio
                }
                try:
                    await ws.send(json.dumps(event))
                except Exception as e:
                    logger.debug(f"Error transitorio enviando frame a OpenAI: {e}")
                    await asyncio.sleep(0.05)
                    continue
            # 30 ms por frame
            await asyncio.sleep(0.015)

    async def _openai_event_receiver(self, ws):
        """Procesa todos los eventos entrantes de OpenAI Realtime."""
        current_response_text = []

        async for raw_message in ws:
            if not self.is_running or self._stop_current_engine_event.is_set():
                break

            event = json.loads(raw_message)
            event_type = event.get("type", "")

            # Interrupción genuina por voz del usuario
            if event_type == "input_audio_buffer.speech_started":
                logger.info("OpenAI VAD: Usuario comenzó a hablar (Barge-in).")
                self.audio.clear_output_buffer()
                self._is_model_responding = False
                self.wake_detector.touch()
                self._update_status_by_wake_state(WakeState.ACTIVE_LISTENING)

            elif event_type == "input_audio_buffer.speech_stopped":
                if self.wake_detector.current_state != WakeState.STANDBY or not self.wake_detector.is_enabled:
                    self.gui.update_status("PROCESANDO...", "#ea580c")

            # Transcripción del usuario por Whisper
            elif event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "").strip()
                if transcript:
                    is_active, clean_cmd = self.wake_detector.check_wake_trigger(transcript)

                    if not is_active and self.wake_detector.is_enabled:
                        logger.info(f"Audio ignorado en Standby (No Wake Word): '{transcript}'")
                        await ws.send(json.dumps({"type": "response.cancel"}))
                        continue

                    self.gui.add_log("USER", transcript)
                    self.memory.record_turn("USER", transcript)
                    self.gui.update_context_turns(self.memory.short_term.get_turn_count())

            # Audio de respuesta de la IA
            elif event_type == "response.audio.delta":
                if not self.wake_detector.is_enabled or self.wake_detector.current_state != WakeState.STANDBY:
                    self._is_model_responding = True
                    self.wake_detector.set_state(WakeState.SPEAKING)
                    self._update_status_by_wake_state(WakeState.SPEAKING)
                    delta_b64 = event.get("delta", "")
                    if delta_b64:
                        raw_pcm = base64.b64decode(delta_b64)
                        self.audio.write_output_chunk(raw_pcm)

            elif event_type == "response.audio_transcript.delta":
                delta_text = event.get("delta", "")
                current_response_text.append(delta_text)

            elif event_type == "response.audio_transcript.done":
                full_text = "".join(current_response_text).strip()
                if full_text and (not self.wake_detector.is_enabled or self.wake_detector.current_state != WakeState.STANDBY):
                    self.gui.add_log("JARVIS", full_text)
                    self.memory.record_turn("JARVIS", full_text)
                    self.gui.update_context_turns(self.memory.short_term.get_turn_count())
                current_response_text = []

            elif event_type == "response.done":
                self._is_model_responding = False
                self.wake_detector.touch()
                if self.wake_detector.is_enabled and self.wake_detector.current_state != WakeState.STANDBY:
                    self.wake_detector.set_state(WakeState.ACTIVE_LISTENING)
                    self.gui.update_status("🟢 ESCUCHANDO (Seguimiento activo)", "#10b981")
                else:
                    self._update_status_by_wake_state(self.wake_detector.current_state)

            # Function Calling
            elif event_type == "response.function_call_arguments.done":
                call_id = event.get("call_id")
                tool_name = event.get("name")
                args_str = event.get("arguments", "{}")

                self.gui.update_status("EJECUTANDO HERRAMIENTA...", "#ea580c")
                self.gui.add_log("HERRAMIENTA", f"Ejecutando '{tool_name}' con parámetros: {args_str}")

                try:
                    args_dict = json.loads(args_str)
                except Exception:
                    args_dict = {}

                result = await execute_tool_call(tool_name, args_dict, self.memory, self.system)
                self.gui.add_log("HERRAMIENTA", f"Resultado de '{tool_name}': {result}")
                self.memory.record_turn("TOOL", str(result), tool_info=tool_name)

                tool_output_event = {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": str(result)
                    }
                }
                await ws.send(json.dumps(tool_output_event))
                await ws.send(json.dumps({"type": "response.create"}))

            elif event_type == "error":
                error_info = event.get("error", {})
                err_message = error_info.get("message", "Error en OpenAI Realtime.")
                raise RuntimeError(f"OpenAI Realtime Error: {err_message}")

    # =========================================================================
    # MOTOR 2: GOOGLE GEMINI LIVE API (FRAMING 30MS, VAD ADAPTATIVO)
    # =========================================================================

    async def _run_gemini_live_engine(self):
        """Controlador de comunicación en tiempo real con Google Gemini Live API."""
        from google import genai
        from google.genai import types

        gemini_key = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key or gemini_key.startswith("your_google"):
            raise ValueError("GOOGLE_API_KEY / GEMINI_API_KEY no configurada en .env.")

        raw_model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview").strip()
        model_id = raw_model.replace("models/", "").strip()
        voice_name = os.getenv("GEMINI_VOICE", "Puck")

        incompatible_models = ["gemini-2.0-flash", "gemini-2.0-flash-exp", "gemini-2.0-flash-live-001", "gemini-1.5-flash", "gemini-1.5-pro"]
        if model_id in incompatible_models or not model_id:
            logger.info(f"Modelo '{model_id}' mapeado automáticamente a 'gemini-3.1-flash-live-preview'.")
            model_id = "gemini-3.1-flash-live-preview"

        self.audio.set_sample_rate(24000)
        self.audio.start_streams()
        self.gui.update_status("CONECTANDO A GEMINI...", "#d97706")

        client = genai.Client(
            api_key=gemini_key,
            http_options={'api_version': 'v1alpha'}
        )

        try:
            full_context = self.memory.get_combined_context_for_prompt(recent_limit=6)
            system_instruction_text = (
                "Eres JARVIS, un asistente inteligente de voz rápido, conciso, profesional y totalmente integrado al sistema operativo del usuario. "
                "Tienes memoria permanente de todas las sesiones de conversación pasadas y recuerdas cada detalle. "
                "Responde en español de forma directa y fluida. Tienes acceso a herramientas completas de creación y gestión de proyectos de código, "
                "archivos de texto, cálculos matemáticos, control de aplicaciones y automatización total del sistema.\n\n"
                f"{full_context}"
            )

            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                    )
                ),
                system_instruction=types.Content(
                    parts=[types.Part.from_text(text=system_instruction_text)]
                ),
                tools=[{"function_declarations": GEMINI_TOOLS}]
            )

            async with client.aio.live.connect(model=model_id, config=config) as session:
                self._update_status_by_wake_state(self.wake_detector.current_state)
                self.gui.add_log("SISTEMA", f"Conectado exitosamente con Gemini Live API ({model_id}).")

                # Tareas paralelas de envío y recepción desacopladas
                sender_task = asyncio.create_task(self._gemini_audio_sender(session))
                receiver_task = asyncio.create_task(self._gemini_event_receiver(session))

                stop_task = asyncio.create_task(self._stop_current_engine_event.wait())
                # Esperar exclusivamente a que finalice el receptor (desconexión remota) o el evento de parada
                done, pending = await asyncio.wait(
                    [receiver_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                sender_task.cancel()
                for task in pending:
                    task.cancel()

                for task in done:
                    if task != stop_task and task.exception():
                        raise task.exception()

        finally:
            try:
                if hasattr(client, "aio") and hasattr(client.aio, "aclose"):
                    await client.aio.aclose()
            except Exception:
                pass

    async def _gemini_audio_sender(self, session):
        """Lee bloques de micrófono de 30 ms y los envía a Gemini Live con supresión de auto-eco."""
        from google.genai import types

        while self.is_running and not self._stop_current_engine_event.is_set():
            is_ai_speaking = self._is_model_responding or self.audio.is_playing()
            if is_ai_speaking:
                # Silenciar streaming mientras la IA habla para que no escuche sus propias palabras
                # a través de los altavoces (prevención absoluta de falsos Barge-in)
                await asyncio.sleep(0.04)
                continue

            pcm_chunk = self.audio.read_input_chunk(is_ai_speaking=is_ai_speaking)

            if pcm_chunk and not self.audio.is_muted:
                audio_blob = types.Blob(data=pcm_chunk, mime_type="audio/pcm;rate=24000")
                try:
                    if hasattr(session, "send_realtime_input"):
                        await session.send_realtime_input(audio=audio_blob)
                    else:
                        await session.send(input=types.LiveClientRealtimeInput(audio=audio_blob))
                except Exception as e:
                    logger.debug(f"Error transitorio enviando frame a Gemini: {e}")
                    await asyncio.sleep(0.05)
                    continue
            # 30 ms de ritmo
            await asyncio.sleep(0.015)

    async def _gemini_event_receiver(self, session):
        """Procesa las respuestas de audio, texto y Function Calling de Gemini Live."""
        from google.genai import types

        try:
            async for response in session.receive():
                if not self.is_running or self._stop_current_engine_event.is_set():
                    break

                server_content = response.server_content
                if server_content:
                    # Detección de interrupción genuina por voz del usuario
                    if server_content.interrupted:
                        logger.info("Gemini Live: Interrupción detectada (Barge-in).")
                        self.audio.clear_output_buffer()
                        self._is_model_responding = False
                        self.wake_detector.touch()
                        self._update_status_by_wake_state(WakeState.ACTIVE_LISTENING)

                    model_turn = server_content.model_turn
                    if model_turn:
                        for part in model_turn.parts:
                            # Reproducción de audio recibido en streaming
                            if part.inline_data and part.inline_data.data:
                                if not self.wake_detector.is_enabled or self.wake_detector.current_state != WakeState.STANDBY:
                                    self._is_model_responding = True
                                    self.wake_detector.set_state(WakeState.SPEAKING)
                                    self._update_status_by_wake_state(WakeState.SPEAKING)
                                    self.audio.write_output_chunk(part.inline_data.data)

                            if part.text:
                                if not self.wake_detector.is_enabled or self.wake_detector.current_state != WakeState.STANDBY:
                                    self.gui.add_log("JARVIS", part.text)
                                    self.memory.record_turn("JARVIS", part.text)
                                    self.gui.update_context_turns(self.memory.short_term.get_turn_count())

                    if server_content.turn_complete:
                        self._is_model_responding = False
                        self.wake_detector.touch()
                        if self.wake_detector.is_enabled and self.wake_detector.current_state != WakeState.STANDBY:
                            self.wake_detector.set_state(WakeState.ACTIVE_LISTENING)
                            self.gui.update_status("🟢 ESCUCHANDO (Seguimiento activo)", "#10b981")
                        else:
                            self._update_status_by_wake_state(self.wake_detector.current_state)

                # Manejo de llamadas a herramientas (Function Calling)
                tool_call = response.tool_call
                if tool_call:
                    self.gui.update_status("EJECUTANDO HERRAMIENTA...", "#ea580c")
                    for fn_call in tool_call.function_calls:
                        name = fn_call.name
                        args = fn_call.args or {}
                        call_id = fn_call.id

                        self.gui.add_log("HERRAMIENTA", f"Ejecutando '{name}' con parámetros: {args}")
                        result = await execute_tool_call(name, args, self.memory, self.system)
                        self.gui.add_log("HERRAMIENTA", f"Resultado de '{name}': {result}")
                        self.memory.record_turn("TOOL", str(result), tool_info=name)

                        fn_response = types.FunctionResponse(
                            name=name,
                            id=call_id,
                            response={"result": str(result)}
                        )
                        if hasattr(session, "send_tool_response"):
                            await session.send_tool_response(function_responses=[fn_response])
                        else:
                            tool_response = types.LiveClientToolResponse(function_responses=[fn_response])
                            await session.send(input=tool_response)

        except Exception as e:
            logger.error(f"Error en recepción de Gemini Live: {e}")
            raise e

    # =========================================================================
    # ARRANQUE DE LA APLICACIÓN
    # =========================================================================

    def run(self):
        """Inicia el bucle de eventos de la GUI en el hilo principal."""
        try:
            self.gui.mainloop()
        except KeyboardInterrupt:
            logger.info("Cerrando JARVIS por teclado...")
        finally:
            self.safe_shutdown()


if __name__ == "__main__":
    app = JarvisOrchestrator()
    app.run()
"""
Bootstrap Module: Gestor de arranque y ciclo de vida para JARVIS.
Realiza verificaciones previas al inicio de la interfaz (pre-flight checks),
instancia y pre-calienta (warm-up) dependencias pesadas (PortAudio, embeddings, ChromaDB)
en segundo plano para evitar bloqueos en el hilo de la GUI (GUI Freeze),
y registra manejadores para apagado ordenado (Graceful Shutdown).
"""

import os
import sys
import time
import signal
import asyncio
import logging
import threading
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("Bootstrap")

# Normalizar variables de entorno para evitar advertencias de API keys duplicadas de google_genai
if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" in os.environ:
    if not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    del os.environ["GEMINI_API_KEY"]


class SystemBootstrapper:
    """
    Coordina la inicialización asíncrona de dependencias del sistema y el warm-up
    de componentes pesados antes o durante la apertura de la interfaz gráfica.
    """

    def __init__(
        self,
        on_progress: Optional[Callable[[str, float], None]] = None,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        :param on_progress: Callback de progreso: callback(mensaje, porcentaje)
        :param on_complete: Callback de finalización con resultados diagnósticos
        """
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.is_ready = False
        self.diagnostic_results: Dict[str, Any] = {}
        self._shutdown_hooks: list[Callable[[], None]] = []

    def register_shutdown_hook(self, hook: Callable[[], None]):
        """Registra una función a ejecutar durante el apagado seguro del sistema."""
        self._shutdown_hooks.append(hook)

    def attach_signal_handlers(self):
        """Enlaza señales del sistema operativo (SIGINT, SIGTERM) para apagado seguro."""
        def _handle_signal(sig, frame):
            logger.info(f"Señal recibida ({sig}). Iniciando apagado seguro...")
            self.execute_shutdown()
            sys.exit(0)

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, _handle_signal)
        except Exception as e:
            logger.debug(f"Aviso al enlazar manejadores de señales: {e}")

    def execute_shutdown(self):
        """Ejecuta todos los hooks de apagado registrados en orden inverso."""
        logger.info("Ejecutando proceso de Graceful Shutdown...")
        for hook in reversed(self._shutdown_hooks):
            try:
                hook()
            except Exception as e:
                logger.error(f"Error ejecutando hook de apagado: {e}")
        logger.info("Graceful Shutdown completado con éxito.")

    def run_bootstrap_async(self, memory_manager=None, audio_handler=None):
        """Inicia el proceso de verificación y warm-up en un hilo de fondo."""
        worker = threading.Thread(
            target=self._bootstrap_worker,
            args=(memory_manager, audio_handler),
            daemon=True
        )
        worker.start()
        return worker

    def _bootstrap_worker(self, memory_manager=None, audio_handler=None):
        """Hilo de trabajo que ejecuta secuencialmente las pruebas y el warm-up."""
        t0 = time.time()

        # 1. Comprobación de Entorno y Variables
        self._report("Comprobando variables de entorno y claves de API...", 0.15)
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        gemini_key = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
        
        has_openai = bool(openai_key and len(openai_key) > 10 and not openai_key.startswith("sk-proj-your"))
        has_gemini = bool(gemini_key and len(gemini_key) > 10 and not gemini_key.startswith("your_google"))
        
        self.diagnostic_results["api_keys"] = {
            "openai_ready": has_openai,
            "gemini_ready": has_gemini
        }

        # 2. Comprobación de Hardware de Audio (PortAudio)
        self._report("Verificando subsistema de audio PortAudio...", 0.35)
        audio_ok = False
        input_dev_name = "Desconocido"
        output_dev_name = "Desconocido"

        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            try:
                default_in = pa.get_default_input_device_info()
                input_dev_name = default_in.get("name", "Micrófono Predeterminado")
                default_out = pa.get_default_output_device_info()
                output_dev_name = default_out.get("name", "Altavoces Predeterminados")
                audio_ok = True
            finally:
                pa.terminate()
        except Exception as e:
            logger.warning(f"Aviso al consultar dispositivos PortAudio: {e}")

        self.diagnostic_results["audio_hardware"] = {
            "available": audio_ok,
            "input_device": input_dev_name,
            "output_device": output_dev_name
        }

        # 3. Warm-Up de Memoria Vectorial ChromaDB y Embeddings
        self._report("Pre-calentando motor vectorial y caché de embeddings...", 0.65)
        memory_ok = False
        if memory_manager:
            try:
                if hasattr(memory_manager, "warmup"):
                    memory_manager.warmup()
                else:
                    # Warmup de fallback
                    _ = memory_manager.search_memory("warmup_test", k=1)
                memory_ok = True
            except Exception as e:
                logger.warning(f"Aviso durante el Warm-up de memoria: {e}")

        self.diagnostic_results["memory_subsystem"] = {
            "warmup_complete": memory_ok
        }

        # 4. Verificación de Sensores de Hardware (psutil)
        self._report("Comprobando sensores del sistema...", 0.80)
        try:
            import psutil
            cpu_test = psutil.cpu_percent(interval=0.05)
            self.diagnostic_results["psutil_available"] = True
        except Exception:
            self.diagnostic_results["psutil_available"] = False

        # 5. Indexación Dinámica de Programas y Archivos del Sistema
        self._report("Indexando software instalado y accesos directos...", 0.90)
        try:
            from system_control import SystemControl
            total_apps = SystemControl.index_installed_applications()
            self.diagnostic_results["indexed_apps_count"] = total_apps
        except Exception as e:
            logger.warning(f"Aviso durante la indexación de programas: {e}")
            self.diagnostic_results["indexed_apps_count"] = 0

        # 6. Finalización
        elapsed = time.time() - t0
        self.diagnostic_results["bootstrap_time_seconds"] = round(elapsed, 2)
        self.is_ready = True

        self._report(f"Sistema listo para operar ({elapsed:.2f}s).", 1.0)
        logger.info(f"Bootstrap finalizado en {elapsed:.2f}s. Diagnóstico: {self.diagnostic_results}")

        if self.on_complete:
            self.on_complete(self.diagnostic_results)

    def _report(self, message: str, progress: float):
        """Notifica progreso al callback."""
        logger.debug(f"[BOOTSTRAP {int(progress*100)}%] {message}")
        if self.on_progress:
            try:
                self.on_progress(message, progress)
            except Exception:
                pass

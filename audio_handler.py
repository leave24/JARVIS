"""
Audio Handler: Manejador de audio bidireccional continuo PCM de 16-bit con PyAudio.
Optimizaciones de ultra-baja latencia:
- Framing óptimo a 24 kHz / 16-bit Mono con tramas de 30 ms (720 muestras) para minimizar RTT.
- VAD dinámico con seguimiento continuo del piso de ruido ambiental (Noise Floor Tracking).
- Supresión de auto-eco acústico adaptativo (AEC por software) para evitar falsos Barge-Ins por altavoces.
- Buffer circular pre-roll de 1.5s y colas desacopladas de captura y reproducción de alta velocidad.
"""

import time
import queue
import collections
import threading
import logging
import pyaudio
import numpy as np
from typing import Callable, Optional

logger = logging.getLogger("AudioHandler")


class AudioHandler:
    """
    Controlador de captura y reproducción de audio de baja latencia con PyAudio.
    Diseñado para operar en streaming continuo a 24 kHz con paquetes de 30 ms,
    eliminando retardos y evitando que JARVIS se auto-interrumpa al emitir voz.
    """

    def __init__(
        self,
        sample_rate: int = 24000,
        chunk_size: int = 720,  # 30 ms a 24000 Hz (720 / 24000 = 0.030s)
        channels: int = 1,
        preroll_seconds: float = 1.5
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.format = pyaudio.paInt16

        self._pyaudio_instance: Optional[pyaudio.PyAudio] = None
        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None

        self.is_muted = False
        self.volume_callback: Optional[Callable[[float], None]] = None

        # Buffer circular para almacenar los últimos N segundos de audio del micrófono
        # 1.5s * 24000 muestras / 720 muestras_por_chunk = 50 chunks
        max_chunks = max(10, int((self.sample_rate * preroll_seconds) / self.chunk_size))
        self._preroll_buffer: collections.deque = collections.deque(maxlen=max_chunks)

        # Cola de reproducción desacoplada para salida de altavoz
        self.output_queue: queue.Queue = queue.Queue()
        self._playback_thread: Optional[threading.Thread] = None
        self._is_playing_loop_running = False
        self._last_playback_time = 0.0
        self._smoothed_volume = 0.0

        # Seguimiento adaptativo del piso de ruido ambiental (Noise Floor)
        self._noise_floor = 0.010
        self._lock = threading.Lock()

    def set_volume_callback(self, callback: Callable[[float], None]):
        """Registra el callback para reportar niveles de volumen a la interfaz gráfica."""
        self.volume_callback = callback

    def set_sample_rate(self, new_rate: int):
        """Ajusta la frecuencia de muestreo y recalcula el tamaño de trama (30 ms)."""
        if self.sample_rate != new_rate:
            logger.info(f"Cambiando frecuencia de muestreo de {self.sample_rate}Hz a {new_rate}Hz")
            was_running = bool(self.input_stream or self.output_stream)
            if was_running:
                self.close()
            self.sample_rate = new_rate
            # 30 ms para la nueva frecuencia
            self.chunk_size = int(self.sample_rate * 0.030)
            max_chunks = max(10, int((self.sample_rate * 1.5) / self.chunk_size))
            with self._lock:
                self._preroll_buffer = collections.deque(maxlen=max_chunks)
            if was_running:
                self.start_streams()

    def is_playing(self) -> bool:
        """Indica si el altavoz está emitiendo voz o quedan datos en la cola de salida."""
        with self._lock:
            has_queue = not self.output_queue.empty()
        is_recent = (time.time() - self._last_playback_time) < 0.35
        return has_queue or is_recent

    def get_noise_floor(self) -> float:
        """Devuelve el nivel estimado actual de ruido de fondo."""
        return self._noise_floor

    def start_streams(self):
        """Inicializa los flujos de hardware de captura y reproducción."""
        with self._lock:
            if not self._pyaudio_instance:
                self._pyaudio_instance = pyaudio.PyAudio()

            try:
                # Stream de micrófono
                if not self.input_stream or not self.input_stream.is_active():
                    self.input_stream = self._pyaudio_instance.open(
                        format=self.format,
                        channels=self.channels,
                        rate=self.sample_rate,
                        input=True,
                        frames_per_buffer=self.chunk_size
                    )
                    logger.info(f"Stream de micrófono abierto a {self.sample_rate}Hz (Trama {self.chunk_size} = 30ms).")

                # Stream de altavoces
                if not self.output_stream or not self.output_stream.is_active():
                    self.output_stream = self._pyaudio_instance.open(
                        format=self.format,
                        channels=self.channels,
                        rate=self.sample_rate,
                        output=True,
                        frames_per_buffer=self.chunk_size
                    )
                    logger.info(f"Stream de altavoces abierto a {self.sample_rate}Hz.")

                # Iniciar hilo de reproducción en segundo plano
                if not self._is_playing_loop_running:
                    self._is_playing_loop_running = True
                    self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
                    self._playback_thread.start()

            except Exception as e:
                logger.error(f"Error al inicializar dispositivos de audio PyAudio: {e}")
                raise e

    def _playback_worker(self):
        """Hilo en segundo plano para procesar la cola de salida de audio de la IA."""
        while self._is_playing_loop_running:
            try:
                data = self.output_queue.get(timeout=0.08)
                if data and self.output_stream and self.output_stream.is_active():
                    self.output_stream.write(data, exception_on_underflow=False)
                    self._last_playback_time = time.time()

                    # Calcular y reportar nivel de volumen de la IA
                    if self.volume_callback:
                        audio_data = np.frombuffer(data, dtype=np.int16)
                        if len(audio_data) > 0:
                            rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                            raw_vol = min(1.0, (rms / 32768.0) * 4.5)
                            self._smoothed_volume = 0.5 * self._smoothed_volume + 0.5 * raw_vol
                            self.volume_callback(self._smoothed_volume)

                self.output_queue.task_done()
            except queue.Empty:
                if self._smoothed_volume > 0.01:
                    self._smoothed_volume *= 0.75
                    if self.volume_callback:
                        self.volume_callback(self._smoothed_volume)
                continue
            except Exception as e:
                logger.debug(f"Aviso en hilo de reproducción: {e}")

    def read_input_chunk(self, is_ai_speaking: bool = False) -> bytes:
        """
        Lee un bloque PCM del micrófono con VAD adaptativo y supresión de auto-eco acústico.
        
        :param is_ai_speaking: Indica si la IA está actualmente reproduciendo sonido por los altavoces.
        :return: Bloque binario PCM de 16 bits (o silencio de reemplazo si es eco acústico).
        """
        if self.is_muted or not self.input_stream or not self.input_stream.is_active():
            return b'\x00' * (self.chunk_size * 2)

        try:
            data = self.input_stream.read(self.chunk_size, exception_on_overflow=False)

            # Calcular volumen RMS de la trama actual
            audio_data = np.frombuffer(data, dtype=np.int16)
            raw_vol = 0.0
            if len(audio_data) > 0:
                rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                raw_vol = min(1.0, (rms / 32768.0) * 5.0)

            # Actualizar piso de ruido ambiental (adaptativo si la IA no habla)
            if not is_ai_speaking:
                self._noise_floor = 0.96 * self._noise_floor + 0.04 * min(raw_vol, 0.15)

            # VAD dinámico: umbral adaptativo
            vad_threshold = max(0.018, self._noise_floor * 2.6)

            # Si la IA está hablando por altavoz:
            # Elevar umbral para filtrar el eco de la propia voz del asistente
            if is_ai_speaking:
                echo_barge_in_threshold = max(0.095, self._noise_floor * 4.2)
                if raw_vol < echo_barge_in_threshold:
                    # Supresión de eco acústico pasivo: devolver silencio
                    return b'\x00' * (self.chunk_size * 2)
                else:
                    logger.info(f"Barge-In genuino detectado (Voz sobre altavoz: {raw_vol:.3f} > {echo_barge_in_threshold:.3f})")

            # Almacenar en buffer circular pre-roll
            with self._lock:
                self._preroll_buffer.append(data)

            # Reportar al visualizador GUI
            if self.volume_callback and not self.is_muted and not is_ai_speaking:
                self._smoothed_volume = 0.5 * self._smoothed_volume + 0.5 * raw_vol
                self.volume_callback(self._smoothed_volume)

            return data
        except Exception as e:
            logger.debug(f"Excepción al leer micrófono: {e}")
            return b'\x00' * (self.chunk_size * 2)

    def get_preroll_audio(self) -> bytes:
        """Recupera el buffer de audio previo (~1.5s)."""
        with self._lock:
            if not self._preroll_buffer:
                return b''
            return b''.join(self._preroll_buffer)

    def write_output_chunk(self, data: bytes):
        """Encola un fragmento de audio PCM recibido de la IA para reproducirlo."""
        if data and self._is_playing_loop_running:
            self.output_queue.put(data)

    def clear_output_buffer(self):
        """Limpia el buffer de reproducción inmediatamente (Barge-In)."""
        with self._lock:
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                    self.output_queue.task_done()
                except Exception:
                    break
        self._last_playback_time = 0.0
        self._smoothed_volume = 0.0
        if self.volume_callback:
            self.volume_callback(0.0)

    def toggle_mute(self) -> bool:
        """Alterna el silencio del micrófono."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            self._smoothed_volume = 0.0
            if self.volume_callback:
                self.volume_callback(0.0)
        logger.info(f"Micrófono {'SILENCIADO' if self.is_muted else 'ACTIVO'}.")
        return self.is_muted

    def close(self):
        """Cierra de forma limpia los dispositivos de audio y libera recursos."""
        self._is_playing_loop_running = False
        self.clear_output_buffer()

        with self._lock:
            if self.input_stream:
                try:
                    if self.input_stream.is_active():
                        self.input_stream.stop_stream()
                    self.input_stream.close()
                except Exception:
                    pass
                self.input_stream = None

            if self.output_stream:
                try:
                    if self.output_stream.is_active():
                        self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception:
                    pass
                self.output_stream = None

            if self._pyaudio_instance:
                try:
                    self._pyaudio_instance.terminate()
                except Exception:
                    pass
                self._pyaudio_instance = None
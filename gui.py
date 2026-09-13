"""
GUI Module: Interfaz gráfica moderna, ciberpunk y reactiva construida con CustomTkinter.
Optimizaciones visuales y de rendimiento:
- Distribución fija por cuadrícula (Grid Layout) con rowconfigure/columnconfigure.
- Vúmetro dinámico interactivo de 10 bandas animadas en CTkCanvas con decaimiento suave a 60 FPS.
- Consola enriquecida con etiquetas de color (tag_config) para segmentación visual de eventos.
- Protocolo seguro de cierre (Graceful Shutdown) vinculado a WM_DELETE_WINDOW.
"""

import time
import math
import customtkinter as ctk
from typing import Callable, Optional, List


class JarvisGUI(ctk.CTk):
    """
    Ventana principal de JARVIS con estética ciberpunk futurista.
    Diseñada con layout por grid, vúmetro dinámico de 10 bandas y
    consola coloreada con tags nativos.
    """

    def __init__(
        self,
        on_toggle_connect: Callable[[], None],
        on_toggle_mute: Callable[[], None],
        on_toggle_wakeword: Callable[[], None],
        on_change_provider: Callable[[str], None],
        on_reconnect: Callable[[], None],
        on_close_requested: Optional[Callable[[], None]] = None,
        on_toggle_autostart: Optional[Callable[[bool], None]] = None
    ):
        super().__init__()

        self.on_toggle_connect = on_toggle_connect
        self.on_toggle_mute = on_toggle_mute
        self.on_toggle_wakeword = on_toggle_wakeword
        self.on_change_provider = on_change_provider
        self.on_reconnect = on_reconnect
        self.on_close_requested = on_close_requested
        self.on_toggle_autostart = on_toggle_autostart

        # Configuración de ventana
        self.title("⚡ JARVIS AI CORE - Cyberpunk Voice Agent")
        self.geometry("1020x760")
        self.minsize(880, 640)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Variables internas de estado
        self._is_muted = False
        self._is_wakeword_active = True
        self._active_engine_name = "OPENAI"
        self._current_volume = 0.0

        # Estados de las 10 bandas del ecualizador para animación continua
        self._num_bands = 10
        self._band_levels: List[float] = [0.0] * self._num_bands
        self._band_colors = [
            "#06b6d4", "#06b6d4", "#0891b2",  # Bandas bajas: Dark Cyan
            "#10b981", "#059669", "#10b981",  # Bandas medias: Emerald
            "#f59e0b", "#d97706",              # Bandas altas: Amber
            "#f43f5e", "#e11d48"               # Pico: Neon Crimson
        ]

        # Configuración de la cuadrícula principal (Grid Layout)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Fila 0: Header y Badges
        self.grid_rowconfigure(1, weight=0)  # Fila 1: Vúmetro dinámico en Canvas
        self.grid_rowconfigure(2, weight=1)  # Fila 2: Consola de terminal expandible
        self.grid_rowconfigure(3, weight=0)  # Fila 3: Barra de controles inferior

        # Construir interfaz gráfica
        self._build_ui()

        # Iniciar loop de animación del visualizador a ~50 FPS (20ms)
        self._animate_vu_meter()

        # Enlazar protocolo de cierre limpio de ventana
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

    def _build_ui(self):
        """Construye todos los paneles usando distribución fija por cuadrícula (Grid)."""

        # ---------------------------------------------------------
        # 1. BARRA SUPERIOR (HEADER Y BADGES) - Fila 0
        # ---------------------------------------------------------
        self.header_frame = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color="#0f172a",
            border_width=1,
            border_color="#1e293b"
        )
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        self.header_frame.grid_columnconfigure(0, weight=1)
        self.header_frame.grid_columnconfigure(1, weight=0)

        # Caja de Título
        self.title_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.title_box.grid(row=0, column=0, sticky="w", padx=16, pady=10)

        self.title_label = ctk.CTkLabel(
            self.title_box,
            text="⚡ JARVIS AI CORE",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#38bdf8"
        )
        self.title_label.pack(anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            self.title_box,
            text="Realtime Voice Core • Dynamic VAD & AEC • Dual-Tier Semantic RAG",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#94a3b8"
        )
        self.subtitle_label.pack(anchor="w")

        # Contenedor de Insignias a la derecha
        self.badges_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.badges_frame.grid(row=0, column=1, sticky="e", padx=16, pady=10)

        # Contador de contexto a corto plazo
        self.context_badge = ctk.CTkLabel(
            self.badges_frame,
            text="🧠 Contexto: 0 turnos",
            fg_color="#1e293b",
            text_color="#94a3b8",
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            width=135,
            height=28
        )
        self.context_badge.pack(side="left", padx=4)

        # Insignia de Proveedor Activo
        self.provider_badge = ctk.CTkLabel(
            self.badges_frame,
            text="AI: OPENAI REALTIME",
            fg_color="#0284c7",
            text_color="#ffffff",
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            width=145,
            height=28
        )
        self.provider_badge.pack(side="left", padx=4)

        # Insignia de Estado Operativo
        self.status_badge = ctk.CTkLabel(
            self.badges_frame,
            text="DESCONECTADO",
            fg_color="#475569",
            text_color="#ffffff",
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            width=185,
            height=28
        )
        self.status_badge.pack(side="left", padx=4)

        # ---------------------------------------------------------
        # 2. VISUALIZADOR DE AUDIO (VÚ-METRO DE 10 BANDAS EN CANVAS) - Fila 1
        # ---------------------------------------------------------
        self.viz_container = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color="#0f172a",
            border_width=1,
            border_color="#1e293b"
        )
        self.viz_container.grid(row=1, column=0, sticky="ew", padx=16, pady=4)
        self.viz_container.grid_columnconfigure(0, weight=1)

        self.viz_header = ctk.CTkFrame(self.viz_container, fg_color="transparent")
        self.viz_header.pack(fill="x", padx=14, pady=(8, 2))

        self.viz_title = ctk.CTkLabel(
            self.viz_header,
            text="DYNAMIC AUDIO ACTIVITY MONITOR (10 BANDS)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#64748b"
        )
        self.viz_title.pack(side="left")

        self.viz_level_text = ctk.CTkLabel(
            self.viz_header,
            text="-∞ dB | VAD: EN ESPERA",
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
            text_color="#38bdf8"
        )
        self.viz_level_text.pack(side="right")

        # Canvas para dibujar las 10 bandas reactivas
        self.viz_canvas = ctk.CTkCanvas(
            self.viz_container,
            height=54,
            bg="#0b1120",
            highlightthickness=1,
            highlightbackground="#1e293b"
        )
        self.viz_canvas.pack(fill="x", padx=12, pady=(2, 10))

        # ---------------------------------------------------------
        # 3. CONSOLA DE REGISTROS ENRIQUECIDA CON TAGS - Fila 2
        # ---------------------------------------------------------
        self.console_frame = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color="#0f172a",
            border_width=1,
            border_color="#1e293b"
        )
        self.console_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=4)
        self.console_frame.grid_columnconfigure(0, weight=1)
        self.console_frame.grid_rowconfigure(1, weight=1)

        self.console_header = ctk.CTkFrame(self.console_frame, fg_color="transparent")
        self.console_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))

        self.console_title = ctk.CTkLabel(
            self.console_header,
            text="TERMINAL DE EVENTOS, TRANSCRIPCIÓN & HERRAMIENTAS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        self.console_title.pack(side="left")

        self.btn_clear_log = ctk.CTkButton(
            self.console_header,
            text="Limpiar Consola",
            width=110,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self.clear_logs
        )
        self.btn_clear_log.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            self.console_frame,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=13),
            fg_color="#0b1120",
            text_color="#f8fafc"
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=12, pady=(2, 12))

        # Configuración de etiquetas de color para texto enriquecido
        self._configure_textbox_tags()
        self.log_textbox.configure(state="disabled")

        # Mensaje de bienvenida
        self.add_log("SISTEMA", "JARVIS AI Voice Core iniciado y optimizado. Pulsa '⚡ INICIAR AGENTE'.")

        # ---------------------------------------------------------
        # 4. PANEL DE CONTROLES INFERIOR - Fila 3
        # ---------------------------------------------------------
        self.controls_frame = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color="#0f172a",
            border_width=1,
            border_color="#1e293b"
        )
        self.controls_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 14))

        # Botón Iniciar / Detener
        self.btn_connect = ctk.CTkButton(
            self.controls_frame,
            text="⚡ INICIAR AGENTE",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=38,
            width=155,
            command=self.on_toggle_connect
        )
        self.btn_connect.pack(side="left", padx=8, pady=10)

        # Botón Wake Word Toggle
        self.btn_wakeword = ctk.CTkButton(
            self.controls_frame,
            text="🔔 WAKE WORD: ACTIVO",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#d97706",
            hover_color="#b45309",
            height=38,
            width=180,
            command=self.on_toggle_wakeword
        )
        self.btn_wakeword.pack(side="left", padx=5, pady=10)

        # Botón Silenciar Micrófono
        self.btn_mute = ctk.CTkButton(
            self.controls_frame,
            text="🎙️ SILENCIAR MIC",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            height=38,
            width=135,
            command=self.on_toggle_mute
        )
        self.btn_mute.pack(side="left", padx=5, pady=10)

        # Botón Reconectar
        self.btn_reconnect = ctk.CTkButton(
            self.controls_frame,
            text="🔄 RECONECTAR",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            height=38,
            width=125,
            command=self.on_reconnect
        )
        self.btn_reconnect.pack(side="left", padx=5, pady=10)

        # Selector de Proveedor
        self.selector_label = ctk.CTkLabel(
            self.controls_frame,
            text="Motor:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        self.selector_label.pack(side="left", padx=(10, 4), pady=10)

        self.engine_selector = ctk.CTkSegmentedButton(
            self.controls_frame,
            values=["OpenAI", "Google Gemini"],
            command=self._handle_engine_select,
            selected_color="#0284c7",
            selected_hover_color="#0369a1",
            unselected_color="#1e293b",
            unselected_hover_color="#334155",
            height=34
        )
        self.engine_selector.set("OpenAI")
        self.engine_selector.pack(side="left", padx=4, pady=10)

        # Switch para auto-inicio con el sistema
        self.switch_autostart = ctk.CTkSwitch(
            self.controls_frame,
            text="Inicio con SO",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
            progress_color="#10b981",
            command=self._handle_autostart_toggle
        )
        self.switch_autostart.pack(side="right", padx=12, pady=10)

    def _handle_autostart_toggle(self):
        """Maneja el evento de alternancia del switch de auto-arranque."""
        is_on = bool(self.switch_autostart.get())
        if self.on_toggle_autostart:
            self.on_toggle_autostart(is_on)

    def set_autostart_switch_state(self, enabled: bool):
        """Actualiza visualmente el estado del switch de auto-inicio."""
        if enabled:
            self.switch_autostart.select()
        else:
            self.switch_autostart.deselect()

    def _configure_textbox_tags(self):
        """Registra las etiquetas visuales para la consola de registro con código de color."""
        # Se configuran directamente en el widget subyacente tkinter.Text
        try:
            raw_text = self.log_textbox._textbox
            raw_text.tag_config("TAG_TIMESTAMP", foreground="#64748b", font=("Consolas", 11))
            raw_text.tag_config("TAG_SISTEMA", foreground="#38bdf8", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_USER", foreground="#4ade80", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_JARVIS", foreground="#60a5fa", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_HERRAMIENTA", foreground="#fbbf24", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_FALLBACK", foreground="#c084fc", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_WAKE", foreground="#f472b6", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_ERROR", foreground="#f87171", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_DEFAULT", foreground="#94a3b8", font=("Consolas", 12, "bold"))
            raw_text.tag_config("TAG_CONTENT", foreground="#f1f5f9", font=("Consolas", 12))
        except Exception:
            pass

    # ---------------------------------------------------------
    # ANIMACIÓN DEL VÚ-METRO DINÁMICO DE 10 BANDAS (CANVAS)
    # ---------------------------------------------------------

    def _animate_vu_meter(self):
        """
        Bucle de animación del Vúmetro en Canvas a 50-60 FPS.
        Simula distribución de espectro acústico en 10 bandas con decaimiento exponencial.
        """
        try:
            canvas_width = self.viz_canvas.winfo_width()
            canvas_height = self.viz_canvas.winfo_height()

            if canvas_width > 50 and canvas_height > 20:
                self.viz_canvas.delete("all")

                vol = self._current_volume
                spacing = 8
                total_spacing = spacing * (self._num_bands + 1)
                bar_width = max(6, int((canvas_width - total_spacing) / self._num_bands))

                # Factores de ponderación frecuencial para las 10 bandas
                freq_weights = [0.85, 1.0, 1.15, 1.05, 0.95, 0.90, 0.85, 0.75, 0.65, 0.55]

                for i in range(self._num_bands):
                    target = min(1.0, vol * freq_weights[i])
                    # Variación armónica suave
                    if target > 0.05:
                        phase = (time.time() * 12.0) + (i * 0.6)
                        target = target * (0.85 + 0.15 * math.sin(phase))

                    # Decaimiento exponencial suave (Exponential Decay)
                    if target > self._band_levels[i]:
                        self._band_levels[i] = 0.45 * self._band_levels[i] + 0.55 * target
                    else:
                        self._band_levels[i] = 0.80 * self._band_levels[i] + 0.20 * target

                    level = max(0.04, min(1.0, self._band_levels[i]))
                    bar_h = max(4, int(level * (canvas_height - 12)))

                    x0 = spacing + i * (bar_width + spacing)
                    x1 = x0 + bar_width
                    y1 = canvas_height - 6
                    y0 = y1 - bar_h

                    color = self._band_colors[i]
                    self.viz_canvas.create_rectangle(
                        x0, y0, x1, y1,
                        fill=color,
                        outline="",
                        width=0
                    )

                    # Tapa de pico (Peak Cap) superior
                    peak_y0 = max(4, y0 - 3)
                    peak_y1 = peak_y0 + 2
                    self.viz_canvas.create_rectangle(
                        x0, peak_y0, x1, peak_y1,
                        fill="#ffffff" if level > 0.6 else color,
                        outline="",
                        width=0
                    )
        except Exception:
            pass

        # Próximo frame en 20 ms (~50 FPS)
        self.after(20, self._animate_vu_meter)

    # ---------------------------------------------------------
    # MÉTODOS DE ACTUALIZACIÓN THREAD-SAFE
    # ---------------------------------------------------------

    def set_volume(self, value: float):
        """Actualiza el nivel de volumen para el animador del Vúmetro."""
        def _apply():
            self._current_volume = max(0.0, min(1.0, value))
            clamped = self._current_volume
            if clamped > 0.015:
                db_approx = int((clamped * 60) - 60)
                self.viz_level_text.configure(text=f"{db_approx} dB | VAD: TRANSMITIENDO")
            else:
                self.viz_level_text.configure(text="-∞ dB | VAD: ESPERA")
        self.after(0, _apply)

    def _handle_engine_select(self, choice: str):
        """Manejador del cambio de motor en el SegmentedButton."""
        provider_name = "OPENAI" if choice == "OpenAI" else "GEMINI"
        self.on_change_provider(provider_name)

    def update_status(self, status: str, color: str = "#475569"):
        """Actualiza la insignia de estado operativo."""
        def _apply():
            self.status_badge.configure(text=status, fg_color=color)
        self.after(0, _apply)

    def update_provider_badge(self, text: str, color: str, provider_name: str = "OPENAI"):
        """Actualiza la insignia del motor de IA activo y sincroniza el selector."""
        def _apply():
            self.provider_badge.configure(text=text, fg_color=color)
            if provider_name == "OPENAI":
                self.engine_selector.set("OpenAI")
            elif provider_name == "GEMINI":
                self.engine_selector.set("Google Gemini")
        self.after(0, _apply)

    def update_context_turns(self, count: int):
        """Actualiza el indicador de turnos en memoria de trabajo."""
        def _apply():
            self.context_badge.configure(text=f"🧠 Contexto: {count} turnos")
        self.after(0, _apply)

    def update_wakeword_button(self, is_enabled: bool):
        """Actualiza la apariencia del botón de Wake Word."""
        def _apply():
            self._is_wakeword_active = is_enabled
            if is_enabled:
                self.btn_wakeword.configure(
                    text="🔔 WAKE WORD: ACTIVO",
                    fg_color="#d97706",
                    hover_color="#b45309"
                )
            else:
                self.btn_wakeword.configure(
                    text="🎙️ MODO CONTINUO",
                    fg_color="#0284c7",
                    hover_color="#0369a1"
                )
        self.after(0, _apply)

    def update_mute_button(self, is_muted: bool):
        """Actualiza la apariencia del botón de silencio."""
        def _apply():
            self._is_muted = is_muted
            if is_muted:
                self.btn_mute.configure(
                    text="🔇 MIC SILENCIADO",
                    fg_color="#dc2626",
                    hover_color="#b91c1c"
                )
            else:
                self.btn_mute.configure(
                    text="🎙️ SILENCIAR MIC",
                    fg_color="#334155",
                    hover_color="#475569"
                )
        self.after(0, _apply)

    def update_connect_button(self, is_connected: bool):
        """Actualiza el botón de inicio/detención."""
        def _apply():
            if is_connected:
                self.btn_connect.configure(
                    text="🛑 DETENER AGENTE",
                    fg_color="#dc2626",
                    hover_color="#b91c1c"
                )
            else:
                self.btn_connect.configure(
                    text="⚡ INICIAR AGENTE",
                    fg_color="#10b981",
                    hover_color="#059669"
                )
        self.after(0, _apply)

    def add_log(self, sender: str, message: str):
        """Agrega un mensaje formateado a la consola con etiquetas de color (tags)."""
        def _apply():
            self.log_textbox.configure(state="normal")
            timestamp = time.strftime("%H:%M:%S")

            category = sender.upper().strip()
            tag_name = f"TAG_{category}"
            if tag_name not in [
                "TAG_SISTEMA", "TAG_USER", "TAG_JARVIS", "TAG_HERRAMIENTA",
                "TAG_FALLBACK", "TAG_WAKE", "TAG_ERROR"
            ]:
                tag_name = "TAG_DEFAULT"

            icons = {
                "JARVIS": "🤖 JARVIS",
                "USER": "👤 USUARIO",
                "SISTEMA": "⚡ SISTEMA",
                "HERRAMIENTA": "🛠️ TOOL",
                "FALLBACK": "🔀 FAILOVER",
                "WAKE": "🔔 WAKE WORD",
                "ERROR": "❌ ERROR"
            }
            prefix = icons.get(category, f"ℹ️ {sender}")

            try:
                raw_text = self.log_textbox._textbox
                # Insertar timestamp con tag TIME
                raw_text.insert("end", f"[{timestamp}] ", "TAG_TIMESTAMP")
                # Insertar prefijo con su tag de color específico
                raw_text.insert("end", f"{prefix}: ", tag_name)
                # Insertar contenido
                raw_text.insert("end", f"{message}\n\n", "TAG_CONTENT")
            except Exception:
                # Respaldo simple
                self.log_textbox.insert("end", f"[{timestamp}] {prefix}: {message}\n\n")

            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        self.after(0, _apply)

    def clear_logs(self):
        """Limpia la consola."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.add_log("SISTEMA", "Consola de registros reiniciada.")

    def _on_window_close(self):
        """Manejador de cierre ordenado de la ventana de la GUI."""
        if self.on_close_requested:
            try:
                self.on_close_requested()
            except Exception:
                pass
        self.destroy()
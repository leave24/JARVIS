# ⚡ JARVIS - Autonomous Voice Agent with Wake Word, Dynamic VAD & Dual Engine

JARVIS es un asistente de voz local autónomo de ultra-baja latencia y grado de producción, equipado con activación por voz (**Wake Word: "Hola JARVIS" / "Hey JARVIS"**), interfaz gráfica ciberpunk reactiva (**CustomTkinter Grid Layout con Vúmetro de 10 Bandas en Canvas**), arquitectura de **Memoria Dual** (memoria de trabajo a corto plazo + **RAG en RAM persistente con ChromaDB**), automatización profunda 100% asíncrona del sistema operativo y un **doble motor de IA con conmutación en caliente (Hot-Failover)** entre **OpenAI Realtime API** y **Google Gemini Live**.

---

## 🏛️ Arquitectura del Sistema Optimizada

```
                         ┌─────────────────────────────────────────────────────────┐
                         │                    CustomTkinter GUI                    │
                         │  (Grid Layout, Vúmetro 10 Bandas en Canvas a 60 FPS,    │
                         │   Consola con Color Tags, Cierre Graceful Shutdown)     │
                         └────────────────────────────┬────────────────────────────┘
                                                      │ (Thread-Safe Callbacks & Queues)
                                                      ▼
                         ┌─────────────────────────────────────────────────────────┐
                         │                JARVIS Core Orchestrator                 │
                         │      (asyncio event loop desacoplado en hilo worker)    │
                         └───────┬────────────────────┬────────────────────┬───────┘
                                 │                    │                    │
               ┌─────────────────┴─┐           ┌──────┴────────┐           └───────────────────┐
               ▼                   ▼           ▼               ▼                               ▼
   ┌───────────────────────┐ ┌───────────┐ ┌───────────────┐ ┌───────────────┐     ┌───────────────────────┐
   │ System Bootstrapper   │ │AI Provider│ │ Audio Handler │ │  Wake Word    │     │    System Control     │
   │ (Pre-flight Checks,   │ │ (OpenAI ↔ │ │ (24kHz 30ms,  │ │   Detector    │     │ (100% Async Launchers,│
   │  Warm-Up, Shutdown)   │ │  Gemini)  │ │  VAD & AEC)   │ │ ("Hola JARVIS")│    │  Apps, Volume, Diag)  │
   └───────────────────────┘ └─────┬─────┘ └───────────────┘ └───────────────┘     └───────────────────────┘
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
                    ┌─────────────┐   ┌─────────────┐   ┌───────────────────────────────────────────────┐
                    │   OpenAI    │   │   Google    │   │               Dual Memory System              │
                    │  Realtime   │   │ Gemini Live │   │ 1. Short-Term: Buffer rotativo de diálogo     │
                    │  WebSocket  │   │  WebSocket  │   │ 2. Long-Term: ChromaDB RAG + RAM LRU Cache    │
                    └─────────────┘   └─────────────┘   └───────────────────────────────────────────────┘
```

---

## ✨ Optimizaciones Clave Implementadas

1. **Arranque y Ciclo de Vida del Sistema (`bootstrap.py`)**:
   - **Bootstrapping Asíncrono**: Verificación previa de hardware de audio (micrófonos y altavoces PortAudio) y credenciales de API sin congelar el hilo principal.
   - **Warm-Up en Segundo Plano**: Pre-calienta el modelo de embeddings y el índice ChromaDB durante el inicio, eliminando retardos en la primera interacción del usuario.
   - **Graceful Shutdown**: Manejadores para `SIGINT`, `SIGTERM` y `WM_DELETE_WINDOW` para garantizar la liberación limpia de WebSockets, flujos de audio y tareas pendientes.

2. **Ultra-Baja Latencia y Supresión de Auto-Eco (`audio_handler.py`)**:
   - **Framing Optimizado de 30 ms**: Trama PCM a 24 kHz / 16-bit mono con `chunk_size = 720` muestras para minimizar el RTT de red.
   - **VAD Dinámico Adaptativo**: Mide continuamente el piso de ruido ambiental (*Noise Floor Tracking*) para ajustar el umbral de detección de voz automáticamente.
   - **Supresión Avanzada de Auto-Eco (AEC por software)**: Atenúa el retorno del altavoz hacia el micrófono mientras JARVIS está hablando, permitiendo solo interrupciones deliberadas (*Barge-In genuino*).

3. **Interfaz Gráfica Profesional y Reactiva (`gui.py`)**:
   - **Distribución Fija por Cuadrícula (Grid Layout)**: Organización sólida con `rowconfigure`/`columnconfigure` adaptables a cualquier resolución.
   - **Vúmetro Dinámico de 10 Bandas en Canvas**: 10 barras animadas con decaimiento exponencial suave a 60 FPS, con gradiente ciberpunk (Dark Cyan ➔ Emerald ➔ Amber ➔ Neon Crimson).
   - **Consola con Etiquetas de Color (`tag_config`)**: Diferenciación cromática en `CTkTextbox` para eventos de Sistema, Usuario, JARVIS, Herramientas, Wake Word, Failover y Errores.

4. **RAG Persistente en Memoria RAM (`memory_manager.py`)**:
   - **Caché LRU en RAM**: Almacena vectores calculados recientemente para responder inmediatamente sin recalcular embeddings.
   - **Deduplicación por Similitud Coseno en Memoria**: Compara recuerdos previos en memoria RAM antes de realizar escrituras en disco en ChromaDB.
   - **Auto-Aprendizaje Pasivo**: Detecta y memoriza automáticamente hechos, gustos y preferencias del usuario (*"mi color favorito es...", "vivo en..."*).

5. **Automatización 100% No Bloqueante (`system_control.py`)**:
   - Lanzador de aplicaciones multiplataforma (Windows, macOS, Linux) usando `asyncio.create_subprocess_shell`.
   - Control de volumen y multimedia asíncrono.
   - Diagnóstico integral de hardware en tiempo real (CPU, memoria RAM, batería, disco).

---

## 📦 Requisitos de Drivers del Sistema

Para el correcto funcionamiento de **PyAudio**, se requieren las librerías nativas de **PortAudio**:

### Windows
- En entornos con Python 3.10+, PyAudio se instala directamente mediante ruedas precompiladas (`pip install pyaudio`).

### macOS
```bash
brew install portaudio
```

### Linux (Ubuntu / Debian)
```bash
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio python3-tk
```

---

## 🚀 Instalación y Configuración

### 1. Clonar o Navegar al Directorio
```bash
cd c:\Users\RckG\Desktop\JARV
```

### 2. Crear y Activar Entorno Virtual
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar Variables de Entorno (`.env`)
Copia el archivo `.env.example` a `.env` y coloca tus claves de API:

```env
# Proveedor preferido (OPENAI o GEMINI)
PREFERRED_PROVIDER=OPENAI
AUTO_FALLBACK=true

# OpenAI Realtime API
OPENAI_API_KEY=sk-proj-tu-api-key-aqui
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview
OPENAI_VOICE=alloy

# Google Gemini Live API
GEMINI_API_KEY=tu-gemini-api-key-aqui
GOOGLE_API_KEY=tu-gemini-api-key-aqui
GEMINI_MODEL=gemini-3.1-flash-live-preview
GEMINI_VOICE=Puck

# Configuración de Wake Word
WAKE_WORD_ENABLED=true
WAKE_WORDS=hola jarvis,hey jarvis,jarvis,oye jarvis,ok jarvis
SLEEP_WORDS=gracias jarvis,descansa,adios jarvis,duermete,silencio jarvis,hasta luego
STANDBY_TIMEOUT_SECONDS=15

# Memoria Dual
SHORT_TERM_MEMORY_MAX_TURNS=10
AUTO_MEMORY_EXTRACTION=true
CHROMA_PERSIST_DIR=./jarvis_db
```

---

## 🎮 Ejecución

Para iniciar JARVIS con la interfaz gráfica optimizada:

```bash
python jarvis.py
```

1. Durante los primeros milisegundos, el **System Bootstrapper** pre-calentará la base vectorial y comprobará los dispositivos de audio en segundo plano.
2. Pulsa **⚡ INICIAR AGENTE**.
3. El indicador mostrará `💤 EN ESPERA ('Hola JARVIS')`.
4. Di: *"Hola JARVIS, ¿cuál es el diagnóstico del sistema?"* o *"Hola JARVIS, recuerda que mi comida favorita es el sushi"*.
5. JARVIS se activará de inmediato, mantendrá el seguimiento conversacional y responderá con voz continua de alta fidelidad.

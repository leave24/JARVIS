"""
Memory Manager: Arquitectura de memoria dual ultra-rápida para JARVIS.
Optimizaciones de rendimiento:
- Caché en memoria RAM para embeddings (LRU) que elimina latencia en consultas repetidas.
- Búsqueda y deduplicación acelerada por similitud coseno en memoria antes de escrituras en disco.
- Método de Warm-Up para precargar modelos y bases de datos durante el arranque.
- Memoria de trabajo a corto plazo (ShortTermMemory) para coherencia conversacional.
- Persistencia a largo plazo con ChromaDB y cascada tolerante a fallos.
"""

import os
import re
import time
import uuid
import sqlite3
import logging
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Normalizar credenciales de Google para evitar advertencia de API keys duplicadas en google_genai SDK
if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" in os.environ:
    if not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    del os.environ["GEMINI_API_KEY"]

logger = logging.getLogger("MemoryManager")


class ShortTermMemory:
    """
    Gestiona la memoria de trabajo y el historial conversacional a corto plazo.
    Mantiene los últimos N turnos para dar coherencia contextual inmediata a las respuestas.
    """

    def __init__(self, max_turns: Optional[int] = None):
        env_turns = int(os.getenv("SHORT_TERM_MEMORY_MAX_TURNS", "10"))
        self.max_turns = max_turns or env_turns
        self.history: List[Dict[str, Any]] = []

    def add_turn(self, role: str, content: str, tool_info: Optional[str] = None):
        """Registra un turno de conversación (USER, JARVIS, TOOL)."""
        if not content or not content.strip():
            return

        entry = {
            "role": role.upper().strip(),
            "content": content.strip(),
            "tool_info": tool_info,
            "timestamp": time.strftime("%H:%M:%S")
        }
        self.history.append(entry)

        if len(self.history) > self.max_turns * 2:
            self.history = self.history[-(self.max_turns * 2):]

    def get_formatted_context(self, limit: int = 6) -> str:
        """Devuelve el contexto reciente formateado para el modelo."""
        if not self.history:
            return "No hay interacciones previas en esta sesión."

        recent = self.history[-limit:]
        formatted = []
        for h in recent:
            role_label = "Usuario" if h["role"] == "USER" else ("JARVIS" if h["role"] == "JARVIS" else "Herramienta")
            formatted.append(f"[{h['timestamp']}] {role_label}: {h['content']}")

        return "\n".join(formatted)

    def get_turn_count(self) -> int:
        """Retorna el número de interacciones del usuario en la sesión actual."""
        return sum(1 for h in self.history if h["role"] == "USER")

    def clear(self):
        """Borra la memoria de trabajo de la sesión."""
        self.history.clear()
        logger.info("Memoria a corto plazo reiniciada.")


class PersistentSessionStore:
    """
    Almacenamiento relacional permanente (SQLite) para todas las conversaciones de JARVIS.
    Registra de manera indeleble cada turno de diálogo de todas las sesiones pasadas
    y presentes para garantizar que ningún dato, archivo o tema conversado se pierda jamás.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.current_session_id = f"session_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._init_db()
        self.start_session(self.current_session_id)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Inicializa las tablas e índices de sesiones e historial conversacional."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT UNIQUE,
                        started_at TEXT,
                        ended_at TEXT,
                        title TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        turn_index INTEGER,
                        timestamp TEXT,
                        role TEXT,
                        content TEXT,
                        tool_info TEXT,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON conversation_turns(timestamp)")
                conn.commit()
            logger.info(f"Base de datos de sesiones persistentes SQLite inicializada en '{self.db_path}'.")
        except Exception as e:
            logger.error(f"Error al inicializar SQLite de sesiones: {e}")

    def start_session(self, session_id: str):
        """Registra el inicio de una nueva sesión de conversación."""
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (session_id, started_at, title) VALUES (?, ?, ?)",
                    (session_id, started_at, f"Sesión del {started_at}")
                )
                conn.commit()
            logger.info(f"Sesión persistente '{session_id}' iniciada.")
        except Exception as e:
            logger.error(f"Error al registrar sesión en SQLite: {e}")

    def record_turn(self, role: str, content: str, tool_info: Optional[str] = None):
        """Guarda de forma atómica e inmediata un turno de conversación."""
        if not content or not content.strip():
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM conversation_turns WHERE session_id = ?",
                    (self.current_session_id,)
                )
                turn_idx = cursor.fetchone()[0] + 1
                conn.execute(
                    """
                    INSERT INTO conversation_turns (session_id, turn_index, timestamp, role, content, tool_info)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self.current_session_id, turn_idx, timestamp, role.upper().strip(), content.strip(), tool_info)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error registrando turno en SQLite: {e}")

    def get_past_sessions_summary(self, max_sessions: int = 5, turns_per_session: int = 4) -> str:
        """
        Recupera el resumen cronológico de sesiones anteriores para
        mantener la continuidad total entre ejecuciones de JARVIS.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT session_id, started_at FROM sessions WHERE session_id != ? ORDER BY id DESC LIMIT ?",
                    (self.current_session_id, max_sessions)
                )
                sessions = cursor.fetchall()
                if not sessions:
                    return "No hay sesiones anteriores registradas en el historial permanente."

                summary_blocks = []
                for s in reversed(sessions):
                    sid = s["session_id"]
                    st_time = s["started_at"]
                    t_cursor = conn.execute(
                        "SELECT timestamp, role, content FROM conversation_turns WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                        (sid, turns_per_session)
                    )
                    turns = t_cursor.fetchall()
                    if turns:
                        lines = [f"• Sesión [{st_time}]:"]
                        for t in turns:
                            role_str = "Usuario" if t["role"] == "USER" else ("JARVIS" if t["role"] == "JARVIS" else "Herramienta")
                            lines.append(f"  - {role_str}: {t['content'][:150]}")
                        summary_blocks.append("\n".join(lines))

                return "\n\n".join(summary_blocks)
        except Exception as e:
            logger.error(f"Error leyendo resumen de sesiones SQLite: {e}")
            return "No fue posible recuperar el historial de sesiones anteriores."

    def search_all_history(self, query: str, limit: int = 10) -> str:
        """
        Busca menciones textuales en todos los turnos registrados históricamente en SQLite.
        """
        if not query or not query.strip():
            return "Error: Consulta vacía."
        clean_q = f"%{query.strip()}%"
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT session_id, timestamp, role, content, tool_info
                    FROM conversation_turns
                    WHERE content LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (clean_q, limit)
                )
                rows = cursor.fetchall()
                if not rows:
                    return f"No se encontraron registros de conversaciones pasadas que coincidan con '{query}'."

                results = []
                for r in rows:
                    role_label = "Usuario" if r["role"] == "USER" else ("JARVIS" if r["role"] == "JARVIS" else f"Herramienta ({r['tool_info']})")
                    results.append(f"[{r['timestamp']}] {role_label}: {r['content']}")

                return f"Coincidencias en el historial permanente de conversaciones ({len(rows)} turnos):\n" + "\n".join(results)
        except Exception as e:
            logger.error(f"Error buscando en SQLite de sesiones: {e}")
            return f"Error consultando el historial permanente: {str(e)}"


class MemoryManager:
    """
    Gestiona el almacenamiento dual de JARVIS:
    - Base de datos relacional SQLite de sesiones completas (PersistentSessionStore).
    - Memoria vectorial persistente semántica con ChromaDB y caché en RAM.
    - Memoria de trabajo a corto plazo para respuestas inmediatas.
    """

    def __init__(self, persist_directory: Optional[str] = None):
        self.persist_directory = persist_directory or os.getenv("CHROMA_PERSIST_DIR", "./jarvis_db")
        self.collection_name = "jarvis_persistent_memory"
        self.auto_extraction_enabled = os.getenv("AUTO_MEMORY_EXTRACTION", "true").lower() in ("true", "1", "yes")

        # 1. Memoria de trabajo a corto plazo (RAM)
        self.short_term = ShortTermMemory()

        # 2. Base de datos SQLite persistente de todas las sesiones
        db_path = os.path.join(self.persist_directory, "sessions_history.db")
        self.session_store = PersistentSessionStore(db_path=db_path)

        # 3. Caché LRU en memoria RAM para embeddings (hasta 500 vectores cacheados)
        self._embedding_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._max_cache_size = 500

        # 4. Caché en memoria de recuerdos recientes para deduplicación instantánea por coseno
        self._memory_cache: List[Dict[str, Any]] = []

        # 5. Inicialización de embeddings y ChromaDB
        self.embeddings = self._init_embeddings()
        self.vector_store = self._init_vector_store()

        # Pre-cargar recuerdos existentes en la caché de RAM
        self._preload_memory_cache()

    def _init_embeddings(self):
        """
        Instancia el modelo de embeddings disponible en cascada:
        1. OpenAI text-embedding-3-small
        2. Google Gemini text-embedding-004
        3. HuggingFace all-MiniLM-L6-v2 (Local)
        4. Generador determinista seguro por SHA-256
        """
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        gemini_key = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()

        # 1. Intentar OpenAI
        if openai_key and len(openai_key) > 10 and not openai_key.startswith("sk-proj-your"):
            try:
                from langchain_openai import OpenAIEmbeddings
                logger.info("Inicializando embeddings con OpenAI (text-embedding-3-small)...")
                emb = OpenAIEmbeddings(
                    model="text-embedding-3-small",
                    api_key=openai_key
                )
                emb.embed_query("test")
                return emb
            except Exception as e:
                logger.warning(f"OpenAIEmbeddings no disponible ({e}). Probando siguiente proveedor...")

        # 2. Intentar Google Gemini con el nuevo SDK google-genai
        if gemini_key and len(gemini_key) > 10 and not gemini_key.startswith("your_google"):
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)

                selected_model = None
                # Priorizar text-embedding-004 según especificación, con fallback automático a gemini-embedding-001
                for candidate in ["text-embedding-004", "gemini-embedding-001", "gemini-embedding-2"]:
                    try:
                        res = client.models.embed_content(model=candidate, contents="warmup")
                        if res and hasattr(res, "embeddings") and res.embeddings:
                            selected_model = candidate
                            logger.info(f"Google GenAI SDK: embeddings validado exitosamente con '{selected_model}'.")
                            break
                    except Exception as model_err:
                        logger.debug(f"Modelo '{candidate}' no disponible en Google GenAI ({model_err}).")

                if selected_model:
                    class GoogleGenAIEmbeddings:
                        """Adaptador de embeddings compatible con LangChain/ChromaDB para el SDK google-genai."""
                        def __init__(self, genai_client, model_name: str):
                            self._client = genai_client
                            self._model = model_name

                        def embed_query(self, text: str) -> List[float]:
                            clean_text = text.strip() or " "
                            res = self._client.models.embed_content(
                                model=self._model,
                                contents=clean_text
                            )
                            return res.embeddings[0].values

                        def embed_documents(self, texts: List[str]) -> List[List[float]]:
                            clean_texts = [t.strip() or " " for t in texts]
                            try:
                                res = self._client.models.embed_content(
                                    model=self._model,
                                    contents=clean_texts
                                )
                                return [emb.values for emb in res.embeddings]
                            except Exception:
                                return [self.embed_query(t) for t in clean_texts]

                    return GoogleGenAIEmbeddings(client, selected_model)
                else:
                    logger.warning("Ningún modelo de embedding de Google GenAI respondió afirmativamente.")
            except Exception as e:
                logger.warning(f"Google GenAI SDK embeddings no disponible ({e}). Pasando a respaldo local...")

        # 3. Respaldo Local (HuggingFace) con optimización de caché offline
        try:
            try:
                from langchain_huggingface import HuggingFaceEmbeddings
            except ImportError:
                from langchain_community.embeddings import HuggingFaceEmbeddings

            logger.info("Inicializando embeddings locales con HuggingFace (all-MiniLM-L6-v2)...")
            try:
                # Intentar cargar prioritariamente desde la caché local (local_files_only=True)
                # para eliminar peticiones HTTP y acelerar el bootstrap a <2s
                emb = HuggingFaceEmbeddings(
                    model_name="all-MiniLM-L6-v2",
                    model_kwargs={"local_files_only": True}
                )
                logger.info("HuggingFace cargado exitosamente desde caché local (offline mode).")
            except Exception as cache_err:
                logger.info(f"Modelo local no encontrado en caché ({cache_err}). Descargando desde HuggingFace Hub...")
                emb = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

            return emb
        except Exception as e:
            logger.warning(f"HuggingFace local no disponible ({e}). Usando generador sintético seguro...")

            class BasicDeterministicEmbeddings:
                def embed_documents(self, texts: List[str]) -> List[List[float]]:
                    return [self.embed_query(t) for t in texts]

                def embed_query(self, text: str) -> List[float]:
                    import hashlib
                    h = hashlib.sha256(text.encode("utf-8")).digest()
                    vector = [((b / 255.0) * 2 - 1) for b in h]
                    while len(vector) < 384:
                        vector.extend(vector[:min(len(vector), 384 - len(vector))])
                    return vector[:384]

            return BasicDeterministicEmbeddings()

    def _init_vector_store(self):
        """Inicializa ChromaDB con directorio persistente local."""
        try:
            try:
                from langchain_chroma import Chroma
            except ImportError:
                from langchain_community.vectorstores import Chroma

            os.makedirs(self.persist_directory, exist_ok=True)

            store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=self.persist_directory
            )
            logger.info(f"ChromaDB cargado exitosamente en '{self.persist_directory}'.")
            return store
        except Exception as e:
            logger.error(f"Error al inicializar ChromaDB: {e}")
            raise e

    def warmup(self):
        """
        Pre-calienta el motor de embeddings y el motor ChromaDB en segundo plano
        durante el arranque para eliminar la latencia inicial del usuario.
        """
        logger.info("Ejecutando Warm-up de memoria RAG...")
        t0 = time.time()
        try:
            # Pre-computar embedding de prueba en caché
            _ = self.get_cached_embedding("JARVIS sistema activo")
            # Forzar carga de índice ChromaDB
            _ = self.vector_store.similarity_search("warmup_query", k=1)
            elapsed = time.time() - t0
            logger.info(f"Warm-up de memoria RAG completado en {elapsed:.2f}s.")
        except Exception as e:
            logger.warning(f"Aviso durante Warm-up de memoria: {e}")

    def get_cached_embedding(self, text: str) -> np.ndarray:
        """
        Calcula o recupera de la caché en RAM el embedding de un texto.
        """
        clean_text = text.strip()
        if clean_text in self._embedding_cache:
            self._embedding_cache.move_to_end(clean_text)
            return self._embedding_cache[clean_text]

        raw_vec = self.embeddings.embed_query(clean_text)
        vec = np.array(raw_vec, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        self._embedding_cache[clean_text] = vec
        if len(self._embedding_cache) > self._max_cache_size:
            self._embedding_cache.popitem(last=False)

        return vec

    def _preload_memory_cache(self):
        """Carga recuerdos existentes de ChromaDB en la caché de RAM para deduplicación ultra-rápida."""
        try:
            collection = self.vector_store._collection
            count = collection.count()
            if count > 0:
                raw_data = collection.get(limit=100)
                documents = raw_data.get("documents", [])
                for doc_text in documents:
                    if doc_text and doc_text.strip():
                        vec = self.get_cached_embedding(doc_text)
                        self._memory_cache.append({"text": doc_text.strip(), "vector": vec})
            logger.debug(f"{len(self._memory_cache)} recuerdos pre-cargados en caché RAM.")
        except Exception as e:
            logger.debug(f"Aviso al pre-cargar caché de memoria: {e}")

    @staticmethod
    def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Calcula la similitud coseno entre dos vectores normalizados."""
        dot = np.dot(vec_a, vec_b)
        return float(dot)

    def save_memory(self, content: str, metadata: Optional[Dict[str, Any]] = None, deduplicate: bool = True) -> str:
        """
        Almacena un recuerdo con deduplicación ultra-rápida por similitud coseno en RAM
        antes de realizar escrituras en disco en ChromaDB.
        """
        if not content or not content.strip():
            return "Error: El contenido a memorizar no puede estar vacío."

        clean_text = content.strip()

        # 1. Deduplicación en memoria RAM por similitud coseno (evita I/O de disco)
        query_vec = self.get_cached_embedding(clean_text)
        if deduplicate and self._memory_cache:
            for item in self._memory_cache:
                sim = self._cosine_similarity(query_vec, item["vector"])
                if sim > 0.88 or item["text"].lower() == clean_text.lower():
                    logger.info(f"Deduplicación en RAM: recuerdo existente con similitud {sim:.3f}: '{clean_text}'")
                    return f"Este dato ya estaba registrado en mi memoria: '{clean_text}'"

        meta = metadata or {}
        meta["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Escritura en ChromaDB
            self.vector_store.add_texts(
                texts=[clean_text],
                metadatas=[meta]
            )
            # Actualizar caché en RAM
            self._memory_cache.append({"text": clean_text, "vector": query_vec})
            logger.info(f"Recuerdo persistido exitosamente: '{clean_text}'")
            return f"He memorizado permanentemente: '{clean_text}'"
        except Exception as e:
            logger.error(f"Fallo al guardar en memoria: {e}")
            return f"Error al persistir la información: {str(e)}"

    def search_memory(self, query: str, k: int = 3) -> str:
        """
        Busca recuerdos semánticamente relevantes en la memoria persistente.
        """
        if not query or not query.strip():
            return "Error: La consulta de búsqueda no puede estar vacía."

        try:
            results = self.vector_store.similarity_search(query.strip(), k=k)
            if not results:
                return "No se encontraron registros ni recuerdos relevantes sobre ese tema en la memoria."

            formatted_memories = []
            for i, doc in enumerate(results, start=1):
                timestamp = doc.metadata.get("timestamp", "Fecha no registrada")
                formatted_memories.append(f"{i}. [{timestamp}] {doc.page_content}")

            response = "Información recuperada de la memoria a largo plazo:\n" + "\n".join(formatted_memories)
            logger.info(f"Búsqueda de memoria para '{query}': {len(results)} resultados encontrados.")
            return response
        except Exception as e:
            logger.error(f"Fallo al buscar en memoria: {e}")
            return f"Error al consultar la base de datos de memoria: {str(e)}"

    def auto_extract_and_save_facts(self, user_text: str) -> Optional[str]:
        """
        Analiza pasivamente las frases del usuario para extraer hechos, preferencias
        y datos personales clave y almacenarlos automáticamente en ChromaDB.
        """
        if not self.auto_extraction_enabled or not user_text:
            return None

        clean = user_text.strip()
        lower = clean.lower()

        patterns = [
            r'\b(?:me llamo|mi nombre es)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+)',
            r'\b(?:recuerda que|no olvides que|ten en cuenta que)\s+(.+)',
            r'\b(?:mi\s+(?:color|comida|lenguaje|sistema|ciudad|musica|hobby|profesion)\s+favorit[oa]\s+es)\s+(.+)',
            r'\b(?:vivo en|radico en|soy de)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+)',
            r'\b(?:trabajo en|estudio en)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+)',
            r'\b(?:mi cumpleanos es el|naci el)\s+(.+)',
            r'\b(?:prefiero que me llames|dime)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+)'
        ]

        for pat in patterns:
            match = re.search(pat, lower, re.IGNORECASE)
            if match:
                extracted_fact = clean
                logger.info(f"[AUTO-MEMORY] Hecho clave detectado automáticamente: '{extracted_fact}'")
                self.save_memory(extracted_fact, metadata={"source": "auto_extracted"}, deduplicate=True)
                return extracted_fact

        return None

    def list_recent_memories(self, limit: int = 5) -> str:
        """Lista los registros más recientes en ChromaDB."""
        try:
            collection = self.vector_store._collection
            count = collection.count()
            if count == 0:
                return "La memoria persistente está vacía actualmente."

            raw_data = collection.get(limit=limit)
            documents = raw_data.get("documents", [])
            if not documents:
                return "No hay recuerdos registrados."

            entries = [f"- {doc}" for doc in documents]
            return f"Últimos {len(entries)} recuerdos en la base de datos ({count} totales):\n" + "\n".join(entries)
        except Exception as e:
            return f"Error al listar recuerdos recientes: {str(e)}"

    def clear_memory(self) -> str:
        """Limpia la base de datos vectorial y la caché en RAM."""
        try:
            collection = self.vector_store._collection
            count = collection.count()
            collection.delete(where={})
            self._memory_cache.clear()
            self._embedding_cache.clear()
            return f"Memoria persistente limpiada correctamente. Se eliminaron {count} registros."
        except Exception as e:
            return f"Error al limpiar la memoria persistente: {str(e)}"

    # =========================================================================
    # REGISTRO Y RECUPERACIÓN MULTI-SESIÓN PERMANENTE
    # =========================================================================

    def record_turn(self, role: str, content: str, tool_info: Optional[str] = None):
        """
        Registra de forma unificada un turno en:
        1. Memoria de trabajo a corto plazo (RAM).
        2. Almacenamiento relacional permanente SQLite (sin pérdida de datos).
        3. Extracción pasiva de hechos clave a ChromaDB si el rol es USER.
        """
        if not content or not content.strip():
            return

        # 1. Memoria a corto plazo (RAM)
        self.short_term.add_turn(role=role, content=content, tool_info=tool_info)

        # 2. Persistencia en base de datos relacional SQLite
        self.session_store.record_turn(role=role, content=content, tool_info=tool_info)

        # 3. Extracción semántica automática para ChromaDB
        if role.upper().strip() == "USER":
            self.auto_extract_and_save_facts(content)

    def get_past_sessions_summary(self, max_sessions: int = 5) -> str:
        """Obtiene el resumen de sesiones anteriores guardadas en SQLite."""
        return self.session_store.get_past_sessions_summary(max_sessions=max_sessions)

    def search_all_sessions_history(self, query: str, limit: int = 10) -> str:
        """Busca en todo el historial conversacional acumulado en SQLite."""
        return self.session_store.search_all_history(query=query, limit=limit)

    def get_combined_context_for_prompt(self, recent_limit: int = 6) -> str:
        """
        Construye el bloque de contexto integral para la directiva del sistema (System Instruction),
        combinando tanto el resumen de sesiones pasadas como los últimos turnos de la sesión actual.
        """
        past_summary = self.get_past_sessions_summary(max_sessions=3)
        current_context = self.short_term.get_formatted_context(limit=recent_limit)

        sections = []
        if past_summary and "No hay sesiones anteriores" not in past_summary:
            sections.append(f"### Memoria de Sesiones Anteriores (Historial Permanente):\n{past_summary}")

        sections.append(f"### Conversación de la Sesión Actual:\n{current_context}")
        return "\n\n".join(sections)
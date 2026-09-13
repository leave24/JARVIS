"""
Tools Configuration: Definición formal de esquemas de Function Calling para
OpenAI Realtime API y Google Gemini Live API, junto con el despachador universal
de ejecución desacoplado de los proveedores de IA.
"""

import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger("ToolsConfig")

# ==============================================================================
# 1. ESQUEMAS PARA OPENAI REALTIME API (Formato JSON Schema estándar)
# ==============================================================================
OPENAI_REALTIME_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "guardar_en_memoria",
        "description": "Guarda información clave, preferencias o hechos mencionados por el usuario en la base de datos persistente RAG.",
        "parameters": {
            "type": "object",
            "properties": {
                "contenido": {
                    "type": "string",
                    "description": "El texto o dato preciso que se desea almacenar en la memoria."
                }
            },
            "required": ["contenido"]
        }
    },
    {
        "type": "function",
        "name": "buscar_en_memoria",
        "description": "Consulta la base de datos vectorial para recuperar recuerdos o datos almacenados previamente a largo plazo.",
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Pregunta o término de búsqueda semántica para recuperar recuerdos."
                },
                "k": {
                    "type": "integer",
                    "description": "Número de resultados más relevantes a devolver (por defecto 3)."
                }
            },
            "required": ["consulta"]
        }
    },
    {
        "type": "function",
        "name": "consultar_contexto_reciente",
        "description": "Consulta el historial reciente de la conversación a corto plazo para recordar temas hablados en esta sesión.",
        "parameters": {
            "type": "object",
            "properties": {
                "limite_turnos": {
                    "type": "integer",
                    "description": "Cantidad de turnos recientes a revisar (por defecto 5)."
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "abrir_aplicacion",
        "description": "Abre o ejecuta cualquier programa instalado, aplicación de software (ej: Photoshop, Illustrator, Visual Studio, Spotify, Discord, Steam, Epic Games, Office, navegadores), carpeta del sistema (Descargas, Documentos, etc.) o archivo en el dispositivo del usuario.",
        "parameters": {
            "type": "object",
            "properties": {
                "nombre_app": {
                    "type": "string",
                    "description": "Nombre del programa, aplicación, carpeta o archivo a abrir (ej: 'photoshop', 'visual studio', 'epic games', 'descargas', 'spotify', 'chrome')."
                }
            },
            "required": ["nombre_app"]
        }
    },
    {
        "type": "function",
        "name": "buscar_y_abrir_archivo",
        "description": "Busca y abre un archivo específico (PDF, Excel, Word, imágenes, código, etc.) o carpeta en el dispositivo del usuario.",
        "parameters": {
            "type": "object",
            "properties": {
                "nombre_archivo": {
                    "type": "string",
                    "description": "Nombre o término de búsqueda del archivo o documento a abrir (ej: 'reporte.pdf', 'tesis.docx', 'descargas')."
                }
            },
            "required": ["nombre_archivo"]
        }
    },
    {
        "type": "function",
        "name": "ejecutar_comando_consola",
        "description": "Ejecuta un comando en la terminal o consola del sistema operativo y devuelve la salida generada (stdout/stderr).",
        "parameters": {
            "type": "object",
            "properties": {
                "comando": {
                    "type": "string",
                    "description": "Línea de comando exacta a ejecutar en la shell del sistema."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Límite de tiempo en segundos (por defecto 30)."
                }
            },
            "required": ["comando"]
        }
    },
    {
        "type": "function",
        "name": "controlar_volumen_sistema",
        "description": "Controla el volumen de audio del sistema (subir, bajar, mutear, desmutear).",
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {
                    "type": "string",
                    "enum": ["subir", "bajar", "mutear", "desmutear"],
                    "description": "Acción a realizar sobre el volumen del sistema."
                }
            },
            "required": ["accion"]
        }
    },
    {
        "type": "function",
        "name": "controlar_reproduccion_multimedia",
        "description": "Controla la reproducción de música y video (play/pausa, siguiente, anterior).",
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {
                    "type": "string",
                    "enum": ["play_pause", "next", "prev", "stop"],
                    "description": "Acción multimedia a ejecutar."
                }
            },
            "required": ["accion"]
        }
    },
    {
        "type": "function",
        "name": "obtener_diagnostico_sistema",
        "description": "Obtiene el diagnóstico completo del hardware: uso de CPU, memoria RAM, batería, disco y fecha/hora.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "bloquear_pantalla",
        "description": "Bloquea la sesión del sistema operativo por seguridad.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "type": "function",
        "name": "gestionar_inicio_sistema",
        "description": "Configura si JARVIS debe iniciar o activarse automáticamente junto con el sistema operativo al encender el equipo.",
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {
                    "type": "string",
                    "enum": ["activar", "desactivar", "consultar"],
                    "description": "Acción a realizar: 'activar', 'desactivar' o 'consultar' el estado de auto-inicio."
                }
            },
            "required": ["accion"]
        }
    },
    {
        "type": "function",
        "name": "gestionar_archivo_proyecto",
        "description": "Crea, lee, edita, sobrescribe, anexa o elimina cualquier archivo de código o texto de un proyecto (Python, JS, HTML, CSS, C++, JSON, Markdown, scripts, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {
                    "type": "string",
                    "enum": ["crear", "leer", "editar", "sobrescribir", "anexar", "eliminar"],
                    "description": "Operación a realizar sobre el archivo."
                },
                "ruta_archivo": {
                    "type": "string",
                    "description": "Ruta absoluta o relativa del archivo en el proyecto."
                },
                "contenido": {
                    "type": "string",
                    "description": "Contenido a escribir o anexar en el archivo (para crear, sobrescribir, anexar o reemplazar completamente)."
                },
                "texto_a_buscar": {
                    "type": "string",
                    "description": "Fragmento exacto de texto que se desea sustituir (al usar accion 'editar')."
                },
                "texto_reemplazo": {
                    "type": "string",
                    "description": "Texto con el que se reemplazará el fragmento buscado."
                }
            },
            "required": ["accion", "ruta_archivo"]
        }
    },
    {
        "type": "function",
        "name": "listar_estructura_proyecto",
        "description": "Muestra el árbol jerárquico de archivos y carpetas de un proyecto o directorio.",
        "parameters": {
            "type": "object",
            "properties": {
                "ruta_directorio": {
                    "type": "string",
                    "description": "Directorio base a explorar (por defecto '.' para la carpeta actual)."
                },
                "profundidad_maxima": {
                    "type": "integer",
                    "description": "Profundidad máxima de subcarpetas a listar (por defecto 3)."
                }
            },
            "required": []
        }
    },
    {
        "type": "function",
        "name": "ejecutar_comando_proyecto",
        "description": "Ejecuta un comando de desarrollo, compilación, ejecución de scripts, git o pruebas en la consola de un proyecto.",
        "parameters": {
            "type": "object",
            "properties": {
                "comando": {
                    "type": "string",
                    "description": "Comando de desarrollo o terminal a ejecutar (ej: 'python script.py', 'npm test', 'git status')."
                },
                "directorio_trabajo": {
                    "type": "string",
                    "description": "Directorio de trabajo donde ejecutar el comando (opcional)."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Tiempo límite en segundos (por defecto 60)."
                }
            },
            "required": ["comando"]
        }
    },
    {
        "type": "function",
        "name": "calcular_expresion_matematica",
        "description": "Evalúa y resuelve expresiones matemáticas, científicas, algebraicas, trigonométricas o estadísticas con alta precisión.",
        "parameters": {
            "type": "object",
            "properties": {
                "expresion": {
                    "type": "string",
                    "description": "La expresión matemática a evaluar (ej: 'sqrt(144) + 15 * 3', 'sin(pi/3)', 'mean([10, 20, 30])', '2**16')."
                }
            },
            "required": ["expresion"]
        }
    },
    {
        "type": "function",
        "name": "consultar_historial_sesiones_completas",
        "description": "Busca y recupera temas, instrucciones o datos conversados en sesiones anteriores archivadas en la base de datos persistente.",
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Término o frase a buscar en el historial de todas las sesiones pasadas."
                },
                "limite": {
                    "type": "integer",
                    "description": "Cantidad máxima de coincidencias a retornar (por defecto 10)."
                }
            },
            "required": ["consulta"]
        }
    }
]

# ==============================================================================
# 2. ESQUEMAS PARA GOOGLE GEMINI LIVE API (Formato FunctionDeclaration)
# ==============================================================================
GEMINI_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "guardar_en_memoria",
        "description": "Guarda información clave, preferencias o hechos del usuario en la memoria persistente RAG.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "contenido": {
                    "type": "STRING",
                    "description": "El texto o dato preciso que se desea almacenar en la memoria."
                }
            },
            "required": ["contenido"]
        }
    },
    {
        "name": "buscar_en_memoria",
        "description": "Consulta la base de datos vectorial para recuperar información o recuerdos almacenados previamente.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "consulta": {
                    "type": "STRING",
                    "description": "Pregunta o término de búsqueda semántica para recuperar recuerdos."
                },
                "k": {
                    "type": "INTEGER",
                    "description": "Número de resultados más relevantes a devolver (por defecto 3)."
                }
            },
            "required": ["consulta"]
        }
    },
    {
        "name": "consultar_contexto_reciente",
        "description": "Consulta el historial de diálogo de la sesión actual para recordar temas hablados recientemente.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "limite_turnos": {
                    "type": "INTEGER",
                    "description": "Cantidad de turnos recientes a revisar (por defecto 5)."
                }
            },
            "required": []
        }
    },
    {
        "name": "abrir_aplicacion",
        "description": "Abre o ejecuta cualquier programa, aplicación instalada, carpeta del sistema (Descargas, Documentos, etc.) o archivo en el dispositivo del usuario.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "nombre_app": {
                    "type": "STRING",
                    "description": "Nombre de la aplicación, programa, carpeta o archivo a abrir (ej: 'photoshop', 'visual studio', 'epic games', 'descargas', 'spotify', 'chrome')."
                }
            },
            "required": ["nombre_app"]
        }
    },
    {
        "name": "buscar_y_abrir_archivo",
        "description": "Busca y abre un archivo específico (documentos PDF, Word, Excel, fotos, videos) o carpeta del usuario en el dispositivo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "nombre_archivo": {
                    "type": "STRING",
                    "description": "Nombre o término del archivo a buscar y abrir (ej: 'reporte.pdf', 'foto.png', 'descargas')."
                }
            },
            "required": ["nombre_archivo"]
        }
    },
    {
        "name": "ejecutar_comando_consola",
        "description": "Ejecuta un comando en la terminal/consola del sistema y devuelve la salida generada.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "comando": {
                    "type": "STRING",
                    "description": "Línea de comando a ejecutar en el sistema."
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": "Tiempo límite en segundos (por defecto 30)."
                }
            },
            "required": ["comando"]
        }
    },
    {
        "name": "controlar_volumen_sistema",
        "description": "Controla el volumen del sistema operativo (subir, bajar, mutear, desmutear).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "accion": {
                    "type": "STRING",
                    "description": "Acción a realizar: 'subir', 'bajar', 'mutear', 'desmutear'."
                }
            },
            "required": ["accion"]
        }
    },
    {
        "name": "controlar_reproduccion_multimedia",
        "description": "Controla la reproducción de audio y video (play_pause, next, prev, stop).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "accion": {
                    "type": "STRING",
                    "description": "Acción multimedia: 'play_pause', 'next', 'prev', 'stop'."
                }
            },
            "required": ["accion"]
        }
    },
    {
        "name": "obtener_diagnostico_sistema",
        "description": "Obtiene el diagnóstico completo del hardware: CPU, RAM, batería, disco y fecha/hora.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "bloquear_pantalla",
        "description": "Bloquea la sesión del sistema operativo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "gestionar_inicio_sistema",
        "description": "Configura si JARVIS se inicia o activa automáticamente junto con el sistema operativo al encender la computadora.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "accion": {
                    "type": "STRING",
                    "description": "Acción a realizar: 'activar', 'desactivar' o 'consultar'."
                }
            },
            "required": ["accion"]
        }
    },
    {
        "name": "gestionar_archivo_proyecto",
        "description": "Crea, lee, edita, sobrescribe, anexa o elimina cualquier archivo de código o texto de un proyecto (Python, JS, HTML, CSS, C++, JSON, Markdown, etc.).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "accion": {
                    "type": "STRING",
                    "description": "Operación: 'crear', 'leer', 'editar', 'sobrescribir', 'anexar', 'eliminar'."
                },
                "ruta_archivo": {
                    "type": "STRING",
                    "description": "Ruta del archivo en el proyecto."
                },
                "contenido": {
                    "type": "STRING",
                    "description": "Contenido a escribir o anexar."
                },
                "texto_a_buscar": {
                    "type": "STRING",
                    "description": "Texto exacto a reemplazar al editar."
                },
                "texto_reemplazo": {
                    "type": "STRING",
                    "description": "Texto de sustitución."
                }
            },
            "required": ["accion", "ruta_archivo"]
        }
    },
    {
        "name": "listar_estructura_proyecto",
        "description": "Muestra el árbol jerárquico de archivos y subcarpetas de un proyecto o directorio.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "ruta_directorio": {
                    "type": "STRING",
                    "description": "Directorio base a explorar (por defecto '.')."
                },
                "profundidad_maxima": {
                    "type": "INTEGER",
                    "description": "Nivel máximo de profundidad en el árbol de carpetas (por defecto 3)."
                }
            },
            "required": []
        }
    },
    {
        "name": "ejecutar_comando_proyecto",
        "description": "Ejecuta comandos de desarrollo, pruebas, git o compilación en un proyecto.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "comando": {
                    "type": "STRING",
                    "description": "Línea de comando a ejecutar en la terminal del proyecto."
                },
                "directorio_trabajo": {
                    "type": "STRING",
                    "description": "Directorio de trabajo (opcional)."
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": "Tiempo límite en segundos (por defecto 60)."
                }
            },
            "required": ["comando"]
        }
    },
    {
        "name": "calcular_expresion_matematica",
        "description": "Evalúa y resuelve expresiones matemáticas, científicas o estadísticas complejas.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "expresion": {
                    "type": "STRING",
                    "description": "La expresión matemática a evaluar (ej: 'sqrt(144) + 15 * 3', 'sin(pi/3)')."
                }
            },
            "required": ["expresion"]
        }
    },
    {
        "name": "consultar_historial_sesiones_completas",
        "description": "Busca y recupera temas, instrucciones o conversaciones de sesiones anteriores.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "consulta": {
                    "type": "STRING",
                    "description": "Término a buscar en el historial de sesiones."
                },
                "limite": {
                    "type": "INTEGER",
                    "description": "Cantidad de resultados a recuperar (por defecto 10)."
                }
            },
            "required": ["consulta"]
        }
    }
]

# ==============================================================================
# 3. DESPACHADOR UNIVERSAL DE EJECUCIÓN DE HERRAMIENTAS
# ==============================================================================
async def execute_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    memory_manager: Any,
    system_control: Any
) -> str:
    """
    Ejecuta de manera segura y unificada cualquier función invocada por cualquiera
    de los motores de IA (OpenAI o Google Gemini).
    
    :param tool_name: Nombre de la función invocada.
    :param args: Diccionario con los argumentos pasados por la IA.
    :param memory_manager: Instancia de MemoryManager.
    :param system_control: Instancia de SystemControl.
    :return: Cadena de texto con el resultado de la ejecución.
    """
    logger.info(f"Despachando herramienta '{tool_name}' con argumentos: {args}")

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}

    try:
        # 1. Herramientas de Memoria
        if tool_name == "guardar_en_memoria":
            content = args.get("contenido", "")
            return memory_manager.save_memory(content=content, deduplicate=True)

        elif tool_name == "buscar_en_memoria":
            query = args.get("consulta", "")
            k = int(args.get("k", 3))
            return memory_manager.search_memory(query=query, k=k)

        elif tool_name == "consultar_contexto_reciente":
            limit = int(args.get("limite_turnos", 5))
            return memory_manager.short_term.get_formatted_context(limit=limit)

        # 2. Herramientas del Sistema y Aplicaciones
        elif tool_name in ("abrir_aplicacion", "buscar_y_abrir_archivo"):
            target_name = (
                args.get("nombre_app") or
                args.get("nombre_archivo") or
                args.get("nombre") or
                args.get("app") or
                args.get("archivo") or
                ""
            )
            return await system_control.open_application(app_or_file_name=target_name)

        elif tool_name == "ejecutar_comando_consola":
            cmd = args.get("comando", "")
            timeout = int(args.get("timeout", 30))
            return await system_control.run_terminal_command(command=cmd, timeout=timeout)

        elif tool_name == "controlar_volumen_sistema":
            accion = args.get("accion", "subir")
            return await system_control.control_volume(action=accion)

        elif tool_name == "controlar_reproduccion_multimedia":
            accion = args.get("accion", "play_pause")
            return await system_control.control_media(action=accion)

        elif tool_name in ("obtener_diagnostico_sistema", "obtener_estado_sistema"):
            return await system_control.get_hardware_diagnostics()

        elif tool_name == "bloquear_pantalla":
            return await system_control.lock_workstation()

        # 3. Gestión de Inicio con el Sistema
        elif tool_name == "gestionar_inicio_sistema":
            accion = args.get("accion", "consultar").lower().strip()
            if accion in ("activar", "enable", "on"):
                return system_control.enable_autostart(True)
            elif accion in ("desactivar", "disable", "off"):
                return system_control.enable_autostart(False)
            else:
                is_active = system_control.is_autostart_enabled()
                state_str = "ACTIVADO (iniciará con el sistema)" if is_active else "DESACTIVADO"
                return f"El inicio automático con el sistema se encuentra actualmente: {state_str}."

        # 4. Gestión Completa de Proyectos y Código
        elif tool_name == "gestionar_archivo_proyecto":
            accion = args.get("accion", "leer")
            file_path = args.get("ruta_archivo", "")
            content = args.get("contenido")
            search_text = args.get("texto_a_buscar")
            replace_text = args.get("texto_reemplazo")
            return await system_control.manage_project_file(
                action=accion,
                file_path=file_path,
                content=content,
                search_text=search_text,
                replace_text=replace_text
            )

        elif tool_name == "listar_estructura_proyecto":
            dir_path = args.get("ruta_directorio", ".")
            max_depth = int(args.get("profundidad_maxima", 3))
            return await system_control.list_project_structure(dir_path=dir_path, max_depth=max_depth)

        elif tool_name == "ejecutar_comando_proyecto":
            cmd = args.get("comando", "")
            cwd = args.get("directorio_trabajo")
            timeout = int(args.get("timeout", 60))
            return await system_control.execute_project_command(command=cmd, working_dir=cwd, timeout_seconds=timeout)

        # 5. Cálculos Matemáticos y Científicos
        elif tool_name == "calcular_expresion_matematica":
            expr = args.get("expresion", "")
            return system_control.calculate_mathematical_expression(expression=expr)

        # 6. Historial de Sesiones Completas
        elif tool_name == "consultar_historial_sesiones_completas":
            query = args.get("consulta", "")
            limite = int(args.get("limite", 10))
            return memory_manager.search_all_sessions_history(query=query, limit=limite)

        else:
            logger.warning(f"Herramienta desconocida solicitada: '{tool_name}'")
            return f"Error: La herramienta '{tool_name}' no está registrada en el sistema."

    except Exception as e:
        logger.error(f"Error durante la ejecución de la herramienta '{tool_name}': {e}")
        return f"Excepción durante la ejecución de '{tool_name}': {str(e)}"
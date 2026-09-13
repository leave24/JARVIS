"""
System Control: Módulo avanzado de indexación, búsqueda profunda y automatización del sistema operativo
multiplataforma (Windows, macOS, Linux) 100% no bloqueante.
Capacidades:
- Indexación dinámica de todo el software instalado (Accesos directos, Registro, UWP, Program Files, .desktop, .app).
- Búsqueda difusa (Fuzzy Matching) y resolución inteligente de alias para encontrar y ejecutar cualquier programa.
- Acceso y apertura instantánea de archivos, documentos y carpetas especiales del usuario (Descargas, Documentos, etc.).
- Control asíncrono de volumen, reproducción multimedia y diagnóstico integral de hardware.
"""

import sys
import os
import re
import glob
import math
import difflib
import platform
import asyncio
import logging
import unicodedata
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("SystemControl")


class SystemProgramFinder:
    """
    Motor de indexación y búsqueda dinámica de aplicaciones, archivos y carpetas del sistema.
    Escanea en segundo plano todos los directorios de instalación, accesos directos,
    claves de registro y paquetes del sistema para permitir abrir cualquier software de forma eficaz.
    """

    _indexed_apps: Dict[str, Dict[str, Any]] = {}
    _is_indexed = False
    _lock = asyncio.Lock()

    @staticmethod
    def normalize_name(text: str) -> str:
        """Normaliza una cadena eliminando acentos, caracteres especiales y mayúsculas."""
        if not text:
            return ""
        t = unicodedata.normalize('NFD', text)
        t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
        t = re.sub(r'[^a-zA-Z0-9\s]', ' ', t).lower()
        return re.sub(r'\s+', ' ', t).strip()

    @classmethod
    def index_applications(cls) -> int:
        """
        Escanea el sistema operativo e indexa todas las aplicaciones instaladas.
        Se ejecuta de forma síncrona o en un hilo de fondo durante el arranque.
        """
        apps: Dict[str, Dict[str, Any]] = {}
        current_os = sys.platform

        # ---------------------------------------------------------
        # 1. INDEXACIÓN EN WINDOWS
        # ---------------------------------------------------------
        if current_os.startswith("win"):
            # A. Accesos directos en Menú Inicio y Escritorio
            shortcut_dirs = [
                os.path.expandvars(r'%ProgramData%\Microsoft\Windows\Start Menu\Programs'),
                os.path.expandvars(r'%AppData%\Microsoft\Windows\Start Menu\Programs'),
                os.path.expandvars(r'%UserProfile%\Desktop'),
                os.path.expandvars(r'%Public%\Desktop'),
                os.path.expandvars(r'%LocalAppData%\Programs')
            ]

            for s_dir in shortcut_dirs:
                if os.path.exists(s_dir):
                    for root, _, files in os.walk(s_dir):
                        for f in files:
                            lower_f = f.lower()
                            if lower_f.endswith(('.lnk', '.exe', '.url')):
                                # Filtrar desinstaladores obvios
                                if any(bad in lower_f for bad in ["uninstall", "desinstalar", "unins000", "help", "readme"]):
                                    continue

                                base_name = os.path.splitext(f)[0]
                                norm_key = cls.normalize_name(base_name)
                                full_path = os.path.join(root, f)

                                if norm_key and (norm_key not in apps or lower_f.endswith('.lnk')):
                                    apps[norm_key] = {
                                        "name": base_name,
                                        "path": full_path,
                                        "type": "shortcut" if lower_f.endswith('.lnk') else "executable",
                                        "priority": 10 if lower_f.endswith('.lnk') else 5
                                    }

            # B. Registro de Windows: App Paths (Ejecutables registrados)
            try:
                import winreg
                for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                    try:
                        with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                            num_subkeys = winreg.QueryInfoKey(key)[0]
                            for i in range(num_subkeys):
                                subkey_name = winreg.EnumKey(key, i)
                                try:
                                    with winreg.OpenKey(key, subkey_name) as app_key:
                                        target_path = winreg.QueryValue(app_key, '')
                                        if target_path and os.path.exists(target_path):
                                            base = os.path.splitext(subkey_name)[0]
                                            norm_k = cls.normalize_name(base)
                                            if norm_k and norm_k not in apps:
                                                apps[norm_k] = {
                                                    "name": base,
                                                    "path": target_path,
                                                    "type": "registry",
                                                    "priority": 8
                                                }
                                except Exception:
                                    pass
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Aviso leyendo registro de Windows: {e}")

            # C. UWP / Windows Store Apps y StartApps de PowerShell
            try:
                import subprocess
                import json
                ps_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-StartApps | ConvertTo-Json -Compress"]
                res = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=5, errors="ignore")
                if res.returncode == 0 and res.stdout.strip():
                    try:
                        raw_apps = json.loads(res.stdout)
                        if isinstance(raw_apps, dict):
                            raw_apps = [raw_apps]
                        for a in raw_apps:
                            name = a.get("Name", "")
                            app_id = a.get("AppID", "")
                            if name and app_id:
                                lower_n = name.lower()
                                if any(bad in lower_n for bad in ["uninstall", "desinstalar"]):
                                    continue
                                norm_k = cls.normalize_name(name)
                                if norm_k and norm_k not in apps:
                                    apps[norm_k] = {
                                        "name": name,
                                        "path": f"shell:AppsFolder\\{app_id}",
                                        "type": "uwp",
                                        "priority": 9
                                    }
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Aviso consultando Get-StartApps: {e}")

        # ---------------------------------------------------------
        # 2. INDEXACIÓN EN MACOS
        # ---------------------------------------------------------
        elif current_os == "darwin":
            mac_dirs = ["/Applications", "/System/Applications", os.path.expanduser("~/Applications")]
            for m_dir in mac_dirs:
                if os.path.exists(m_dir):
                    for item in os.listdir(m_dir):
                        if item.endswith(".app"):
                            base = item[:-4]
                            norm_k = cls.normalize_name(base)
                            apps[norm_k] = {
                                "name": base,
                                "path": os.path.join(m_dir, item),
                                "type": "app_bundle",
                                "priority": 10
                            }

        # ---------------------------------------------------------
        # 3. INDEXACIÓN EN LINUX (.desktop files)
        # ---------------------------------------------------------
        else:
            linux_dirs = [
                "/usr/share/applications",
                "/usr/local/share/applications",
                os.path.expanduser("~/.local/share/applications"),
                "/var/lib/flatpak/exports/share/applications",
                "/var/lib/snapd/desktop/applications"
            ]
            for l_dir in linux_dirs:
                if os.path.exists(l_dir):
                    for f in glob.glob(os.path.join(l_dir, "*.desktop")):
                        try:
                            with open(f, "r", encoding="utf-8", errors="ignore") as df:
                                content = df.read()
                                name_match = re.search(r"^Name=(.+)$", content, re.MULTILINE)
                                exec_match = re.search(r"^Exec=(.+)$", content, re.MULTILINE)
                                if name_match and exec_match:
                                    app_name = name_match.group(1).strip()
                                    exec_cmd = exec_match.group(1).split()[0]
                                    norm_k = cls.normalize_name(app_name)
                                    if norm_k not in apps:
                                        apps[norm_k] = {
                                            "name": app_name,
                                            "path": exec_cmd,
                                            "desktop_file": f,
                                            "type": "desktop",
                                            "priority": 10
                                        }
                        except Exception:
                            pass

        cls._indexed_apps = apps
        cls._is_indexed = True
        logger.info(f"SystemProgramFinder: {len(apps)} aplicaciones y accesos directos indexados en el sistema.")
        return len(apps)

    @classmethod
    def get_special_folders(cls) -> Dict[str, str]:
        """Devuelve un mapa de carpetas personales y directorios clave del usuario."""
        home = os.path.expanduser("~")
        return {
            "descargas": os.path.join(home, "Downloads"),
            "downloads": os.path.join(home, "Downloads"),
            "documentos": os.path.join(home, "Documents"),
            "documents": os.path.join(home, "Documents"),
            "escritorio": os.path.join(home, "Desktop"),
            "desktop": os.path.join(home, "Desktop"),
            "imagenes": os.path.join(home, "Pictures"),
            "fotos": os.path.join(home, "Pictures"),
            "pictures": os.path.join(home, "Pictures"),
            "musica": os.path.join(home, "Music"),
            "music": os.path.join(home, "Music"),
            "videos": os.path.join(home, "Videos"),
            "inicio": home,
            "home": home,
            "proyecto": os.getcwd(),
            "carpeta actual": os.getcwd(),
            "directorio actual": os.getcwd()
        }

    @classmethod
    def find_best_match(cls, target: str) -> Optional[Dict[str, Any]]:
        """
        Localiza la mejor coincidencia para una aplicación dada su nombre o alias,
        utilizando coincidencia exacta, tokens de contención y coincidencia difusa (fuzzy).
        """
        if not cls._is_indexed:
            cls.index_applications()

        norm_query = cls.normalize_name(target)
        if not norm_query:
            return None

        # 0. Carpetas Especiales Directas
        special_folders = cls.get_special_folders()
        if norm_query in special_folders:
            return {
                "name": target,
                "path": special_folders[norm_query],
                "type": "special_folder",
                "priority": 20
            }

        # 1. Mapeo de Alias Populares
        aliases = {
            "navegador": ["chrome", "msedge", "edge", "firefox", "brave", "opera", "safari"],
            "browser": ["chrome", "msedge", "edge", "firefox", "brave", "opera"],
            "internet": ["chrome", "msedge", "edge", "firefox"],
            "consola": ["powershell", "terminal", "cmd"],
            "terminal": ["powershell", "terminal", "cmd"],
            "explorador": ["explorer"],
            "archivos": ["explorer"],
            "carpetas": ["explorer"],
            "bloc de notas": ["notepad"],
            "notas": ["notepad", "sticky notes"],
            "calculadora": ["calculadora", "calc"],
            "configuracion": ["configuracion", "settings", "ms settings"],
            "ajustes": ["configuracion", "settings"],
            "correo": ["correo", "mail", "outlook"],
            "visual studio": ["visual studio code", "code", "visual studio"],
            "visual": ["visual studio code", "code"],
            "vscode": ["visual studio code", "code"],
            "vs code": ["visual studio code", "code"]
        }

        if norm_query in aliases:
            for candidate in aliases[norm_query]:
                for k, info in cls._indexed_apps.items():
                    if candidate in k:
                        return info

        # 2. Coincidencia Exacta
        if norm_query in cls._indexed_apps:
            return cls._indexed_apps[norm_query]

        # 3. Coincidencia por Palabras Clave / Substrings
        query_words = set(norm_query.split())
        best_token_match = None
        highest_word_overlap = 0

        for k, info in cls._indexed_apps.items():
            k_words = set(k.split())
            overlap = len(query_words.intersection(k_words))
            if overlap > highest_word_overlap:
                highest_word_overlap = overlap
                best_token_match = info

        if highest_word_overlap == len(query_words) and best_token_match:
            return best_token_match

        # 4. Coincidencia por Substring directa
        for k, info in cls._indexed_apps.items():
            if norm_query in k:
                return info

        # 5. Coincidencia Difusa (Fuzzy Match con difflib)
        all_keys = list(cls._indexed_apps.keys())
        close_matches = difflib.get_close_matches(norm_query, all_keys, n=1, cutoff=0.52)
        if close_matches:
            return cls._indexed_apps[close_matches[0]]

        return None

    @classmethod
    def search_user_files(cls, filename_query: str, max_depth: int = 3) -> Optional[str]:
        """
        Busca un archivo o documento específico en las carpetas comunes del usuario
        (Escritorio, Documentos, Descargas y Workspace).
        """
        home = os.path.expanduser("~")
        search_dirs = [
            os.getcwd(),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Pictures")
        ]

        clean_query = filename_query.lower().strip()
        best_file = None
        best_score = 0.0

        for base_dir in search_dirs:
            if not os.path.exists(base_dir):
                continue

            current_depth = 0
            for root, dirs, files in os.walk(base_dir):
                rel = os.path.relpath(root, base_dir)
                if rel != "." and rel.count(os.sep) >= max_depth:
                    dirs.clear()
                    continue

                for f in files:
                    lower_f = f.lower()
                    # 1. Coincidencia exacta de nombre
                    if lower_f == clean_query or os.path.splitext(lower_f)[0] == clean_query:
                        return os.path.join(root, f)

                    # 2. Coincidencia de similitud
                    ratio = difflib.SequenceMatcher(None, clean_query, lower_f).ratio()
                    if ratio > best_score and ratio > 0.65:
                        best_score = ratio
                        best_file = os.path.join(root, f)

        return best_file


class SystemControl:
    """
    Controlador central de herramientas del sistema operativo.
    Implementa funciones nativas y subprocesos asíncronos para control integral
    sin bloquear el bucle de eventos ni el streaming de audio.
    """

    @classmethod
    def index_installed_applications(cls) -> int:
        """Punto de entrada para indexar aplicaciones en segundo plano."""
        return SystemProgramFinder.index_applications()

    @staticmethod
    async def open_application(app_or_file_name: str) -> str:
        """
        Localiza y ejecuta de forma eficaz cualquier programa, aplicación instalada,
        carpeta o archivo del usuario sin importar la ruta o el sistema operativo.
        """
        if not app_or_file_name or not app_or_file_name.strip():
            return "Error: No se especificó el nombre de ninguna aplicación o archivo."

        target = app_or_file_name.strip()
        norm_target = SystemProgramFinder.normalize_name(target)
        current_os = sys.platform

        # ---------------------------------------------------------
        # 1. COMPROBAR CARPETAS ESPECIALES DEL SISTEMA
        # ---------------------------------------------------------
        special_folders = SystemProgramFinder.get_special_folders()
        if norm_target in special_folders:
            folder_path = special_folders[norm_target]
            if os.path.exists(folder_path):
                logger.info(f"Abriendo carpeta del sistema: {folder_path}")
                await SystemControl._launch_file_path(folder_path)
                return f"Carpeta '{target}' ({folder_path}) abierta exitosamente."

        # ---------------------------------------------------------
        # 2. COMPROBAR SI ES UNA RUTA DIRECTA DE ARCHIVO O CARPETA
        # ---------------------------------------------------------
        expanded_target = os.path.expanduser(os.path.expandvars(target))
        if os.path.exists(expanded_target):
            logger.info(f"Abriendo ruta directa: {expanded_target}")
            await SystemControl._launch_file_path(expanded_target)
            return f"Ruta '{target}' abierta correctamente."

        # ---------------------------------------------------------
        # 3. BUSCAR EN EL ÍNDICE DE APLICACIONES INSTALADAS
        # ---------------------------------------------------------
        match_info = SystemProgramFinder.find_best_match(target)
        if match_info:
            app_name = match_info["name"]
            app_path = match_info["path"]
            logger.info(f"Aplicación encontrada: '{app_name}' -> '{app_path}'")
            try:
                await SystemControl._launch_file_path(app_path)
                return f"Aplicación '{app_name}' iniciada correctamente."
            except Exception as e:
                logger.error(f"Error al abrir {app_name}: {e}")

        # ---------------------------------------------------------
        # 4. BUSCAR EN ARCHIVOS Y DOCUMENTOS PERSONALES DEL USUARIO
        # ---------------------------------------------------------
        found_file = SystemProgramFinder.search_user_files(target)
        if found_file:
            logger.info(f"Archivo de usuario encontrado: {found_file}")
            await SystemControl._launch_file_path(found_file)
            return f"Archivo '{os.path.basename(found_file)}' abierto con el programa predeterminado del sistema."

        # ---------------------------------------------------------
        # 5. INTENTO UNIVERSAL DE LANZAMIENTO POR COMANDO DE SO
        # ---------------------------------------------------------
        try:
            if current_os.startswith("win"):
                # Protocolos de Windows o comando start
                await asyncio.create_subprocess_shell(
                    f"start \"\" \"{target}\"",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                return f"Comando de apertura para '{target}' enviado a Windows."
            elif current_os == "darwin":
                await asyncio.create_subprocess_shell(
                    f"open -a \"{target}\"",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                return f"Comando de apertura para '{target}' enviado a macOS."
            else:
                await asyncio.create_subprocess_shell(
                    f"xdg-open \"{target}\"",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                return f"Comando de apertura para '{target}' enviado a Linux."
        except Exception as e:
            return f"No se pudo encontrar ni ejecutar '{target}' en el dispositivo: {str(e)}"

    @staticmethod
    async def find_and_open_file(file_or_folder_name: str) -> str:
        """Busca y abre un archivo o documento específico en el dispositivo del usuario."""
        if not file_or_folder_name or not file_or_folder_name.strip():
            return "Error: No se especificó el nombre del archivo a buscar."

        # Reutilizar el pipeline inteligente de open_application
        return await SystemControl.open_application(file_or_folder_name)

    @staticmethod
    async def _launch_file_path(path: str):
        """Lanza de forma 100% no bloqueante una ruta de archivo, ejecutable o UWP en el SO."""
        current_os = sys.platform

        if current_os.startswith("win"):
            # En Windows: si es UWP shell:AppsFolder o un path ejecutable
            loop = asyncio.get_running_loop()
            if hasattr(os, "startfile") and not path.startswith("shell:AppsFolder"):
                # os.startfile es la API nativa de ShellExecuteW
                await loop.run_in_executor(None, os.startfile, path)
            else:
                # Usar explorer.exe para shell:AppsFolder y ejecutables complejos
                await asyncio.create_subprocess_shell(
                    f'explorer.exe "{path}"',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
        elif current_os == "darwin":
            await asyncio.create_subprocess_shell(
                f'open "{path}"',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
        else:
            await asyncio.create_subprocess_shell(
                f'xdg-open "{path}"',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )

    @staticmethod
    async def run_terminal_command(command: str, timeout_seconds: int = 15) -> str:
        """
        Ejecuta un comando de consola de forma segura y asíncrona con límite de tiempo.
        """
        if not command or not command.strip():
            return "Error: Comando vacío."

        # Lista de comandos destructivos prohibidos
        forbidden = [
            "rmdir /s /q c:\\", "format c:", "del /f /s /q c:",
            ":(){ :|:& };:", "dd if=/dev/zero", "mkfs"
        ]
        lowered = command.lower()
        if any(f in lowered for f in forbidden):
            return "Operación rechazada por motivos de seguridad: comando potencialmente destructivo."

        logger.info(f"Ejecutando comando asíncrono: '{command}' (Timeout: {timeout_seconds}s)")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                return f"Error: El comando superó el tiempo límite de {timeout_seconds} segundos y fue cancelado."

            out_str = stdout_data.decode("utf-8", errors="replace").strip()
            err_str = stderr_data.decode("utf-8", errors="replace").strip()

            if process.returncode == 0:
                result = out_str if out_str else "(El comando se ejecutó exitosamente sin salida de texto)"
                return f"Salida exitosa:\n{result}"
            else:
                msg = err_str if err_str else out_str
                return f"El comando finalizó con código de error {process.returncode}:\n{msg}"

        except Exception as e:
            logger.error(f"Error en subprocess: {e}")
            return f"Fallo al ejecutar el comando en la consola: {str(e)}"

    @staticmethod
    async def control_volume(action: str, level: Optional[int] = None) -> str:
        """
        Controla el volumen maestro del sistema (subir, bajar, mutear, desmutear).
        """
        act = action.lower().strip()
        current_os = sys.platform

        try:
            if current_os.startswith("win"):
                import ctypes
                VK_VOLUME_MUTE = 0xAD
                VK_VOLUME_DOWN = 0xAE
                VK_VOLUME_UP = 0xAF

                if act in ("subir", "up", "aumentar"):
                    steps = max(1, min(10, int(level / 2) if level else 3))
                    for _ in range(steps):
                        ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                        ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)
                    return f"Volumen aumentado ({steps * 2}% aprox)."

                elif act in ("bajar", "down", "disminuir"):
                    steps = max(1, min(10, int(level / 2) if level else 3))
                    for _ in range(steps):
                        ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                        ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 2, 0)
                    return f"Volumen disminuido ({steps * 2}% aprox)."

                elif act in ("silenciar", "mutear", "mute", "desmutear"):
                    ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
                    return "Estado de silencio (mute) del sistema alternado."

            elif current_os == "darwin":
                if act in ("subir", "up"):
                    await asyncio.create_subprocess_shell("osascript -e 'set volume output volume ((output volume of (get volume settings)) + 10)'")
                    return "Volumen subido en macOS."
                elif act in ("bajar", "down"):
                    await asyncio.create_subprocess_shell("osascript -e 'set volume output volume ((output volume of (get volume settings)) - 10)'")
                    return "Volumen bajado en macOS."
                elif act in ("silenciar", "mutear", "mute"):
                    await asyncio.create_subprocess_shell("osascript -e 'set volume with output muted'")
                    return "Volumen silenciado en macOS."

            elif current_os.startswith("linux"):
                if act in ("subir", "up"):
                    await asyncio.create_subprocess_shell("amixer -D pulse sset Master 5%+")
                    return "Volumen subido en Linux."
                elif act in ("bajar", "down"):
                    await asyncio.create_subprocess_shell("amixer -D pulse sset Master 5%-")
                    return "Volumen bajado en Linux."
                elif act in ("silenciar", "mutear", "mute"):
                    await asyncio.create_subprocess_shell("amixer -D pulse sset Master toggle")
                    return "Silencio alternado en Linux."

            return f"Acción de volumen '{action}' ejecutada."
        except Exception as e:
            return f"No se pudo controlar el volumen: {str(e)}"

    @staticmethod
    async def control_media(action: str) -> str:
        """Controla la reproducción multimedia (play, pause, siguiente, anterior)."""
        act = action.lower().strip()
        current_os = sys.platform

        try:
            if current_os.startswith("win"):
                import ctypes
                VK_MEDIA_NEXT_TRACK = 0xB0
                VK_MEDIA_PREV_TRACK = 0xB1
                VK_MEDIA_PLAY_PAUSE = 0xB3

                key = None
                if act in ("play", "pause", "reproducir", "pausar", "alternar"):
                    key = VK_MEDIA_PLAY_PAUSE
                elif act in ("siguiente", "next"):
                    key = VK_MEDIA_NEXT_TRACK
                elif act in ("anterior", "previous", "prev"):
                    key = VK_MEDIA_PREV_TRACK

                if key:
                    ctypes.windll.user32.keybd_event(key, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(key, 0, 2, 0)
                    return f"Comando multimedia '{action}' enviado."

            return f"Acción multimedia '{action}' procesada."
        except Exception as e:
            return f"Error en control multimedia: {str(e)}"

    @staticmethod
    async def get_hardware_diagnostics() -> str:
        """Obtiene un reporte asíncrono y completo del estado del hardware."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, SystemControl._sync_hardware_diagnostics)

    @staticmethod
    def _sync_hardware_diagnostics() -> str:
        """Cálculo síncrono ejecutado en hilo del pool de ejecutores."""
        try:
            import psutil
            cpu_usage = psutil.cpu_percent(interval=0.1)
            cpu_cores = psutil.cpu_count(logical=True)
            ram = psutil.virtual_memory()
            ram_used_gb = ram.used / (1024 ** 3)
            ram_total_gb = ram.total / (1024 ** 3)
            disk = psutil.disk_usage('/')
            disk_free_gb = disk.free / (1024 ** 3)
            battery = psutil.sensors_battery()
            bat_str = f"{battery.percent}% ({'Cargando / Conectado' if battery.power_plugged else 'Descargando'})" if battery else "No disponible (Equipo de sobremesa o sensor inactivo)"

            return (
                f"Diagnóstico del Sistema:\n"
                f"- ⏱️ Fecha y Hora Local: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"- 💻 Sistema: {platform.system()} {platform.release()} ({platform.machine()})\n"
                f"- ⚡ Uso de CPU: {cpu_usage}% ({cpu_cores} núcleos)\n"
                f"- 🧠 Memoria RAM: {ram.percent}% usado ({ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB)\n"
                f"- 💾 Disco Principal: {disk.percent}% usado ({disk_free_gb:.1f} GB libres)\n"
                f"- 🔋 Batería: {bat_str}"
            )
        except Exception as e:
            return f"Diagnóstico del Sistema:\n- ⏱️ Hora: {datetime.now().strftime('%H:%M:%S')}\n- 💻 SO: {sys.platform}\n(Detalle no disponible: {e})"

    @staticmethod
    async def lock_workstation() -> str:
        """Bloquea la sesión del usuario de forma segura."""
        current_os = sys.platform
        try:
            if current_os.startswith("win"):
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return "Estación de trabajo bloqueada."
            elif current_os == "darwin":
                await asyncio.create_subprocess_shell("pmset displaysleepnow")
                return "Pantalla bloqueada en macOS."
            elif current_os.startswith("linux"):
                await asyncio.create_subprocess_shell("xdg-screensaver lock")
                return "Sesión bloqueada en Linux."
            return "Comando de bloqueo no soportado en este SO."
        except Exception as e:
            return f"Error al bloquear la estación: {str(e)}"

    # =========================================================================
    # AUTO-ARRANQUE CON EL SISTEMA OPERATIVO
    # =========================================================================

    @staticmethod
    def is_autostart_enabled() -> bool:
        """
        Comprueba si JARVIS está configurado para iniciar automáticamente con el SO.
        """
        current_os = sys.platform
        try:
            if current_os.startswith("win"):
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    try:
                        val, _ = winreg.QueryValueEx(key, "JARVIS_AI_CORE")
                        return bool(val)
                    except FileNotFoundError:
                        return False
            elif current_os == "darwin":
                plist_path = os.path.expanduser("~/Library/LaunchAgents/com.jarvis.agent.plist")
                return os.path.exists(plist_path)
            elif current_os.startswith("linux"):
                desktop_path = os.path.expanduser("~/.config/autostart/jarvis.desktop")
                return os.path.exists(desktop_path)
            return False
        except Exception as e:
            logger.debug(f"Error verificando auto-inicio: {e}")
            return False

    @staticmethod
    def enable_autostart(enable: bool) -> str:
        """
        Activa o desactiva el inicio automático de JARVIS con el sistema operativo.
        """
        current_os = sys.platform
        app_path = os.path.abspath("jarvis.py")
        exec_path = sys.executable

        try:
            if current_os.startswith("win"):
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                    if enable:
                        cmd = f'"{exec_path}" "{app_path}"'
                        winreg.SetValueEx(key, "JARVIS_AI_CORE", 0, winreg.REG_SZ, cmd)
                        logger.info(f"Auto-inicio en Windows activado: {cmd}")
                        return "El inicio automático con Windows ha sido activado exitosamente."
                    else:
                        try:
                            winreg.DeleteValue(key, "JARVIS_AI_CORE")
                            logger.info("Auto-inicio en Windows desactivado.")
                            return "El inicio automático con Windows ha sido desactivado."
                        except FileNotFoundError:
                            return "El inicio automático ya se encontraba desactivado."

            elif current_os == "darwin":
                plist_path = os.path.expanduser("~/Library/LaunchAgents/com.jarvis.agent.plist")
                if enable:
                    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
                    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exec_path}</string>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
                    with open(plist_path, "w", encoding="utf-8") as f:
                        f.write(plist_content)
                    return "Inicio automático en macOS configurado correctamente."
                else:
                    if os.path.exists(plist_path):
                        os.remove(plist_path)
                    return "Inicio automático en macOS desactivado."

            elif current_os.startswith("linux"):
                desktop_path = os.path.expanduser("~/.config/autostart/jarvis.desktop")
                if enable:
                    os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
                    entry = f"""[Desktop Entry]
Type=Application
Exec="{exec_path}" "{app_path}"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=JARVIS AI Core
Comment=JARVIS Voice Assistant
"""
                    with open(desktop_path, "w", encoding="utf-8") as f:
                        f.write(entry)
                    return "Inicio automático en Linux configurado correctamente."
                else:
                    if os.path.exists(desktop_path):
                        os.remove(desktop_path)
                    return "Inicio automático en Linux desactivado."

            return f"Auto-inicio no soportado en plataforma {current_os}."
        except Exception as e:
            logger.error(f"Fallo al cambiar configuración de auto-inicio: {e}")
            return f"Error al modificar el inicio con el sistema: {str(e)}"

    # =========================================================================
    # GESTIÓN COMPLETA DE PROYECTOS, ARCHIVOS Y CÓDIGO FUENTE
    # =========================================================================

    @staticmethod
    async def manage_project_file(
        action: str,
        file_path: str,
        content: Optional[str] = None,
        search_text: Optional[str] = None,
        replace_text: Optional[str] = None
    ) -> str:
        """
        Crea, lee, edita, sobrescribe, anexa o elimina cualquier archivo de proyecto
        (código fuente Python, JS, HTML, C++, Markdown, texto, configuración JSON/YAML, etc.).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            SystemControl._sync_manage_project_file,
            action,
            file_path,
            content,
            search_text,
            replace_text
        )

    @staticmethod
    def _sync_manage_project_file(
        action: str,
        file_path: str,
        content: Optional[str] = None,
        search_text: Optional[str] = None,
        replace_text: Optional[str] = None
    ) -> str:
        """Implementación síncrona de gestión de archivos para ejecución en hilo secundario."""
        if not file_path or not file_path.strip():
            return "Error: No se proporcionó la ruta del archivo."

        act = action.lower().strip()
        abs_path = os.path.abspath(file_path.strip())

        try:
            # 1. CREAR ARCHIVO O SOBRESCRIBIR
            if act in ("create", "crear", "new"):
                parent_dir = os.path.dirname(abs_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                file_content = content if content is not None else ""
                with open(abs_path, "w", encoding="utf-8", errors="replace") as f:
                    f.write(file_content)

                byte_size = len(file_content.encode("utf-8"))
                return f"Archivo creado exitosamente en: '{abs_path}' ({byte_size} bytes escritos)."

            # 2. LEER ARCHIVO
            elif act in ("read", "leer", "open"):
                if not os.path.exists(abs_path):
                    return f"Error: El archivo no existe en la ruta: '{abs_path}'."
                if os.path.isdir(abs_path):
                    return f"Error: La ruta especificada es un directorio, no un archivo: '{abs_path}'."

                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()

                total_lines = len(lines)
                if total_lines > 120:
                    preview = "".join(lines[:100])
                    return (
                        f"Contenido del archivo '{os.path.basename(abs_path)}' (mostrando primeras 100 líneas de {total_lines}):\n"
                        f"----------------------------------------\n"
                        f"{preview}\n"
                        f"----------------------------------------\n"
                        f"[... Archivo truncado por extensión: {total_lines} líneas totales]"
                    )
                else:
                    return (
                        f"Contenido del archivo '{os.path.basename(abs_path)}' ({total_lines} líneas):\n"
                        f"----------------------------------------\n"
                        f"{''.join(lines)}"
                    )

            # 3. EDITAR / REEMPLAZAR TEXTO EN ARCHIVO
            elif act in ("edit", "editar", "replace", "reemplazar", "patch"):
                if not os.path.exists(abs_path):
                    return f"Error: El archivo a editar no existe: '{abs_path}'."

                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    original_text = f.read()

                if search_text:
                    if search_text not in original_text:
                        return f"Error de reemplazo: El texto a buscar no fue encontrado en '{os.path.basename(abs_path)}'."
                    new_text = original_text.replace(search_text, replace_text or "")
                    with open(abs_path, "w", encoding="utf-8", errors="replace") as f:
                        f.write(new_text)
                    return f"Edición completada en '{os.path.basename(abs_path)}': texto reemplazado satisfactoriamente."
                elif content is not None:
                    # Si no hay search_text pero hay content, sustitución completa
                    with open(abs_path, "w", encoding="utf-8", errors="replace") as f:
                        f.write(content)
                    return f"Archivo '{os.path.basename(abs_path)}' actualizado con el nuevo contenido ({len(content)} caracteres)."
                else:
                    return "Error: Para editar un archivo debe especificarse 'search_text' con 'replace_text', o bien 'content'."

            # 4. ANEXAR (APPEND)
            elif act in ("append", "anexar", "agregar"):
                parent_dir = os.path.dirname(abs_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                append_content = content if content is not None else ""
                with open(abs_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(append_content)
                return f"Contenido anexado con éxito a '{os.path.basename(abs_path)}'."

            # 5. ELIMINAR ARCHIVO
            elif act in ("delete", "eliminar", "borrar", "remove"):
                if not os.path.exists(abs_path):
                    return f"El archivo ya no existía en '{abs_path}'."
                os.remove(abs_path)
                return f"Archivo eliminado correctamente: '{abs_path}'."

            else:
                return f"Acción '{action}' no reconocida. Opciones válidas: 'create', 'read', 'edit', 'append', 'delete'."

        except Exception as e:
            logger.error(f"Error operando archivo '{file_path}': {e}")
            return f"Error durante la operación de archivo: {str(e)}"

    @staticmethod
    async def list_project_structure(dir_path: str = ".", max_depth: int = 3, show_hidden: bool = False) -> str:
        """
        Explora y formatea la estructura jerárquica de archivos y carpetas de un proyecto.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            SystemControl._sync_list_project_structure,
            dir_path,
            max_depth,
            show_hidden
        )

    @staticmethod
    def _sync_list_project_structure(dir_path: str = ".", max_depth: int = 3, show_hidden: bool = False) -> str:
        """Generación síncrona del árbol de directorios de proyecto."""
        target_dir = os.path.abspath(dir_path.strip() if dir_path else ".")
        if not os.path.exists(target_dir):
            return f"Error: El directorio especificado no existe: '{target_dir}'."
        if not os.path.isdir(target_dir):
            return f"Error: La ruta no es un directorio: '{target_dir}'."

        ignored_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            "dist", "build", ".idea", ".vscode", "target", ".next"
        }

        tree_lines = [f"📁 {os.path.basename(target_dir) or target_dir}/"]

        def _format_size(size_bytes: int) -> str:
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            else:
                return f"{size_bytes / (1024 * 1024):.1f} MB"

        def _walk(current_path: str, depth: int, prefix: str):
            if depth > max_depth:
                return

            try:
                entries = sorted(os.listdir(current_path))
            except PermissionError:
                tree_lines.append(f"{prefix}└── [Permiso denegado]")
                return

            visible_entries = []
            for e in entries:
                if not show_hidden and e.startswith("."):
                    continue
                if e in ignored_dirs:
                    continue
                visible_entries.append(e)

            count = len(visible_entries)
            for i, name in enumerate(visible_entries):
                is_last = (i == count - 1)
                connector = "└── " if is_last else "├── "
                full_entry_path = os.path.join(current_path, name)

                if os.path.isdir(full_entry_path):
                    tree_lines.append(f"{prefix}{connector}📁 {name}/")
                    extension = "    " if is_last else "│   "
                    _walk(full_entry_path, depth + 1, prefix + extension)
                else:
                    try:
                        sz = os.path.getsize(full_entry_path)
                        sz_str = _format_size(sz)
                    except Exception:
                        sz_str = "? B"
                    tree_lines.append(f"{prefix}{connector}📄 {name} ({sz_str})")

        _walk(target_dir, 1, "")
        return "\n".join(tree_lines)

    @staticmethod
    async def execute_project_command(
        command: str,
        working_dir: Optional[str] = None,
        timeout_seconds: int = 60
    ) -> str:
        """
        Ejecuta de forma asíncrona un comando de desarrollo o construcción de proyecto
        (ej: python, npm, cargo, gcc, git) en el directorio especificado.
        """
        if not command or not command.strip():
            return "Error: Comando de proyecto vacío."

        cwd = os.path.abspath(working_dir) if working_dir else os.getcwd()
        if not os.path.exists(cwd):
            return f"Error: El directorio de trabajo especificado no existe: '{cwd}'."

        forbidden = ["rm -rf /", "rmdir /s /q c:\\", "format c:", "del /f /s /q c:"]
        lowered = command.lower()
        if any(f in lowered for f in forbidden):
            return "Operación cancelada por seguridad: comando destructivo detectado."

        logger.info(f"Ejecutando comando de proyecto: '{command}' en '{cwd}' (Timeout: {timeout_seconds}s)")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                return f"Tiempo límite de {timeout_seconds} segundos excedido al ejecutar '{command}'."

            out_str = stdout_data.decode("utf-8", errors="replace").strip()
            err_str = stderr_data.decode("utf-8", errors="replace").strip()

            if process.returncode == 0:
                result = out_str if out_str else "(Comando ejecutado con éxito sin salida de texto)"
                return f"Resultado exitoso:\n{result}"
            else:
                msg = err_str if err_str else out_str
                return f"Comando finalizó con código de error {process.returncode}:\n{msg}"

        except Exception as e:
            logger.error(f"Fallo al ejecutar comando de proyecto: {e}")
            return f"Error al ejecutar comando de proyecto: {str(e)}"

    # =========================================================================
    # MOTOR DE CÁLCULO MATEMÁTICO, ESTADÍSTICO Y CIENTÍFICO
    # =========================================================================

    @staticmethod
    def calculate_mathematical_expression(expression: str) -> str:
        """
        Evalúa de forma segura cálculos matemáticos, estadísticos y científicos
        (aritmética, álgebra, trigonometría, potencias, logaritmos, etc.).
        """
        if not expression or not expression.strip():
            return "Error: Expresión matemática vacía."

        clean_expr = expression.strip()
        # Normalizar caracteres habituales: ^ a **, coma decimal a punto si procede
        clean_expr = clean_expr.replace("^", "**").replace("×", "*").replace("÷", "/")

        # Construir entorno seguro de cálculo con math y numpy si está disponible
        safe_dict: Dict[str, Any] = {
            "__builtins__": {},
            "math": math,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
            "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
            "sqrt": math.sqrt, "cbrt": lambda x: x ** (1/3),
            "log": math.log, "log10": math.log10, "log2": math.log2,
            "exp": math.exp, "pow": pow, "abs": abs, "round": round,
            "pi": math.pi, "e": math.e, "tau": math.tau,
            "factorial": math.factorial, "gcd": math.gcd,
            "radians": math.radians, "degrees": math.degrees,
            "ceil": math.ceil, "floor": math.floor
        }

        try:
            import numpy as np
            safe_dict["np"] = np
            safe_dict["mean"] = np.mean
            safe_dict["median"] = np.median
            safe_dict["std"] = np.std
            safe_dict["var"] = np.var
        except ImportError:
            pass

        # Validar tokens peligrosos
        dangerous_tokens = ["import", "open", "os", "sys", "exec", "eval", "__", "lambda", "compile", "subprocess"]
        if any(d in clean_expr.lower() for d in dangerous_tokens):
            return "Error: La expresión contiene identificadores no permitidos por seguridad."

        try:
            result = eval(clean_expr, {"__builtins__": {}}, safe_dict)
            # Formatear números con precisión adecuada
            if isinstance(result, float):
                if result.is_integer():
                    res_str = str(int(result))
                else:
                    res_str = f"{result:.8f}".rstrip("0").rstrip(".")
            else:
                res_str = str(result)
            return f"Cálculo matemático: {clean_expr} = {res_str}"
        except Exception as e:
            return f"Error calculando '{clean_expr}': {str(e)}"
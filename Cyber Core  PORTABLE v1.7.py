# ==================================================================================
# 🗂️ Cyber Core Worker v 1.7 (PRODUCTION STABLE - COMPLETE EDITION) - ЧАСТЬ 1
# ==================================================================================

import sys
import os
import requests
import json
import re
import queue
import copy
import time
import sqlite3  
import subprocess  
import webbrowser  
import base64
import urllib.request
import urllib.parse


import cv2

# Импорт сопутствующих локальных модулей проекта
from autonomous_agent import AutonomousAgentWorker
from media_processor import MediaProcessor, OCRWorker
from chart_processor import ChartProcessor
from image_generation_expert import LocalDiffusionWorker
from portable_backend import PortableLlamaEngine

# Поддержка красивой раскраски синтаксиса программного кода
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTextEdit, QLineEdit, QPushButton, 
                             QLabel, QFileDialog, QComboBox, QSlider, QGroupBox, 
                             QFormLayout, QListWidget, QListWidgetItem, QSplitter,
                             QCheckBox, QTabWidget, QProgressDialog, QSizePolicy, QMenu, QTreeView) 
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QProcess
from PyQt6.QtGui import QAction, QTextCursor, QPixmap, QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QFileSystemModel

# Безопасный импорт psutil для мониторинга ресурсов системы
try:
    import psutil
except ImportError:
    class DummyVirtualMemory: percent = 0.0
    class DummyPsutil:
        @staticmethod
        def cpu_percent(): return 0.0
        @staticmethod
        def virtual_memory(): return DummyVirtualMemory()
    psutil = DummyPsutil()

class HardwareMonitor(QThread):
    """📈 Фоновый поток для замера ресурсов ПК (CPU, RAM, Intel Arc GPU, VRAM)"""
    stats_updated = pyqtSignal(float, float, float, float)

    def __init__(self):
        super().__init__()
        self.is_running = True

    def _get_windows_gpu_stats(self):
        gpu_load = 0.0
        vram_gb = 0.0
        if os.name != 'nt':
            return gpu_load, vram_gb
        try:
            # Читаем нагрузку движков 3D и Compute (именно на них работает Vulkan llama-server)
            cmd = 'typeperf "\\GPU Engine(*)\\Utilization Percentage" -sc 1'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip().startswith('"') and not l.startswith('"(PDH')]
                if lines:
                    vals = [float(x.strip('"')) for x in lines[-1].split(',')[1:] if x.strip('"').replace('.', '', 1).isdigit()]
                    if vals:
                        gpu_load = min(100.0, max(vals))
        except Exception:
            pass
        return gpu_load, vram_gb

    def run(self):
        tick = 0
        cached_gpu = 0.0
        cached_vram = 0.0
        while self.is_running:
            try:
                cpu_p = psutil.cpu_percent()
                ram_p = psutil.virtual_memory().percent
                # Замеряем GPU раз в 2 секунды, чтобы не нагружать систему
                if tick % 2 == 0:
                    cached_gpu, cached_vram = self._get_windows_gpu_stats()
                tick += 1
                self.stats_updated.emit(float(cpu_p), float(ram_p), float(cached_gpu), float(cached_vram))
            except Exception:
                pass
            for _ in range(10):
                if not self.is_running:
                    break
                self.msleep(100)

    def stop(self):
        self.is_running = False

class VoiceWorker(QThread):
    """🎙️ Фоновый поток для локальной записи и распознавания речи с микрофона"""
    text_recognized = pyqtSignal(str)
    status_updated = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.fs = 16000  
        self.audio_queue = queue.Queue()  
        self.is_recording = False
        self.audio_stream = None 
        self._whisper_model = None  

    def _get_model(self):
        """Загружает Whisper один раз и бережно хранит его в ОЗУ"""
        if self._whisper_model is None:
            from faster_whisper import WhisperModel
            self.status_updated.emit("⏳ Загрузка модели Whisper...")
            self._whisper_model = WhisperModel(
                "tiny", 
                device="cpu", 
                compute_type="int8", 
                cpu_threads=4
            )
        return self._whisper_model

    def start_recording(self):
        if self.isRunning():
            self.status_updated.emit("❌ Поток занят обработкой")
            return
        try:
            self.audio_queue = queue.Queue()  
            self.is_recording = True
            self.status_updated.emit("🎙️ Запись... Говорите")
            self.audio_stream = sd.InputStream(
                samplerate=self.fs, 
                channels=1, 
                callback=self.audio_callback
            )
            self.audio_stream.start()
        except Exception as e:
            self.is_recording = False
            self.status_updated.emit("❌ Ошибка микрофона")
            self.text_recognized.emit(f"[Микрофон не найден или занят: {str(e)}]")

    def audio_callback(self, indata, frames, time, status):
        if self.is_recording:
            self.audio_queue.put(indata.copy())

    def stop_and_process(self):
        if not self.is_recording:
            return
        self.is_recording = False
        if self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception:
                pass
            self.audio_stream = None
        self.status_updated.emit("⏳ Распознавание речи...")
        self.start()  

    def run(self):
        if self.audio_queue.empty():
            self.text_recognized.emit("")
            return
        try:
            audio_chunks = []
            while not self.audio_queue.empty():
                audio_chunks.append(self.audio_queue.get())
            audio_data = np.concatenate(audio_chunks, axis=0).flatten()
            model = self._get_model()
            segments, info = model.transcribe(audio_data, beam_size=5, language="ru")
            text = "".join([segment.text for segment in segments])
            self.text_recognized.emit(text.strip())
        except Exception as e:
            self.text_recognized.emit(f"[Ошибка распознавания речи: {str(e)}]")
class SmartLineEdit(QTextEdit):
    """Поле ввода с отправкой по Enter и переносом строки по Shift+Enter"""
    enter_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Введите ваш промпт здесь...\n[Enter] — отправить\n[Shift + Enter] — перенос строки")
        self.setFixedHeight(180) 

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.enter_pressed.emit()
                event.accept()  
                return
        super().keyPressEvent(event)

class AIWorker(QThread):
    """Фоновый поток ИИ, высчитывающий скорость генерации и поддерживающий мгновенный стоп с тотальной очисткой кортежей"""
    response_received = pyqtSignal(str)
    stats_updated = pyqtSignal(float, int)  # Передает (скорость tok/sec, общее число токенов)
    finished = pyqtSignal()

    def __init__(self, model, messages, options, is_portable_backend=True):
        super().__init__()
        if isinstance(model, tuple):
            model = model[0] if model else ""
        self.model = str(model).replace("('", "").replace("',)", "").strip()
        
        self.messages = self.clean_structures(messages)
        self.options = self.clean_structures(options) if options else {}
        
        # Безальтернативный портативный бэкенд
        self.is_portable_backend = True
        
        self.start_time = None
        self.char_count = 0
        self.is_stopped = False

    def clean_structures(self, data):
        """🔄 Рекурсивная очистка: превращает любые кортежи из БД в чистые типы Python"""
        if isinstance(data, tuple):
            if len(data) == 1:
                return self.clean_structures(data[0])
            return [self.clean_structures(item) for item in data]
        elif isinstance(data, list):
            return [self.clean_structures(item) for item in data]
        elif isinstance(data, dict):
            return {str(k).replace("('", "").replace("',)", "").strip(): self.clean_structures(v) for k, v in data.items()}
        elif isinstance(data, str):
            return data.replace("('", "").replace("',)", "").strip()
        else:
            return data

    def stop_generation(self):
        self.is_stopped = True

    def run(self):
        """Запуск стриминга ответов локального ИИ с гарантированной защитой от tuple-ошибок pydantic и крашей"""
        import traceback
        import logging
        import time
        
        try:
            self.start_time = time.time()
            
            if not isinstance(self.messages, list):
                self.messages = [{"role": "user", "content": str(self.messages)}]
                
            if not isinstance(self.options, dict):
                self.options = {}
                
            # Исключаем экспертные флаги UI, оставляя только чистые математические веса для llama-server
            clean_options = {k: v for k, v in self.options.items() if k not in ["active_experts"]}
            
            # ЧИСТЫЙ ЛОКАЛЬНЫЙ КОНТУР ИНФЕРЕНСА (Порт 8080)
            from portable_backend import PortableLlamaEngine
            engine = PortableLlamaEngine(self.model, options=clean_options)
            stream_generator = engine.generate_chat_stream(self.messages)
            
            for text in stream_generator:
                if self.is_stopped:
                    break
                if text:
                    self.char_count += len(text)
                    elapsed = time.time() - self.start_time
                    tokens_estimated = int(self.char_count / 3.8) + 1
                    tok_sec = tokens_estimated / elapsed if elapsed > 0 else 0.0
                    self.response_received.emit(text)
                    self.stats_updated.emit(tok_sec, tokens_estimated)
                    
        except Exception as e:
            raw_err = traceback.format_exc()
            logging.error(f"[Исключение AIWorker QThread]:\n{raw_err}")
            
            with open("crash_report.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- СБОЙ СТРИМИНГА ИИ ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
                f.write(raw_err)
            
            human_error = f"\n<b style='color:red;'>[Ошибка инференса]:</b> {str(e)}<br><pre style='color:#ff8888; font-size:11px;'>{raw_err}</pre>"
            self.response_received.emit(human_error)
            
        finally:
            self.finished.emit()


class MarkdownHighlighter:
    """Парсер Markdown для красивой раскраски синтаксиса программного кода"""
    @staticmethod
    def to_html(text):
        if not text: return ""
        import html
        pattern = r"```([a-zA-Z0-9_+-]*?)\n(.*?)(?:```|$)"
        code_blocks = []
        
        def replace_with_placeholder(match):
            lang = match.group(1).strip()
            code = match.group(2)
            try:
                lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
            except Exception:
                lexer = get_lexer_by_name("text")
            formatter = HtmlFormatter(style="monokai", noclasses=True)
            highlighted_code = highlight(code, lexer, formatter)
            html_block = (
                f"<div class='code-container' style='border:1px solid #005c4e;"
                f"border-radius:6px;padding:10px;background-color:#13171c;"
                f"margin:10px 0;font-family:Consolas,monospace;'>"
                f"{highlighted_code}</div>"
            )
            placeholder = f"___CODE_BLOCK_PLACEHOLDER_{len(code_blocks)}___"
            code_blocks.append((placeholder, html_block))
            return placeholder

        processed_text = re.sub(pattern, replace_with_placeholder, text, flags=re.DOTALL)
        processed_text = html.escape(processed_text)
        for placeholder, html_block in code_blocks:
            processed_text = processed_text.replace(html.escape(placeholder), html_block)
        processed_text = processed_text.replace("\n", "<br>")
        return processed_text
class PythonSyntaxHighlighter(QSyntaxHighlighter):
    """🎨 Класс нативной подсветки синтаксиса Python в реальном времени для QTextEdit"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # 1. Подсветка ключевых слов Python (Розовый неон)
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#ff0055"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "False", "None", "True", "and", "as", "assert", "async", "await",
            "break", "class", "continue", "def", "del", "elif", "else",
            "except", "finally", "for", "from", "global", "if", "import",
            "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
            "return", "try", "while", "with", "yield"
        ]
        for word in keywords:
            pattern = re.compile(r'\b' + word + r'\b')
            self.highlighting_rules.append((pattern, keyword_format))

        # 2. Подсветка встроенных функций (Бирюзовый)
        builtins_format = QTextCharFormat()
        builtins_format.setForeground(QColor("#00ffcc"))
        builtins = ["print", "input", "len", "range", "str", "int", "float", "list", "dict", "set", "open", "type"]
        for word in builtins:
            pattern = re.compile(r'\b' + word + r'\b')
            self.highlighting_rules.append((pattern, builtins_format))

        # 3. Подсветка объявлений классов и функций (Оранжевый / Зеленый)
        self.class_format = QTextCharFormat()
        self.class_format.setForeground(QColor("#ffaa00"))
        self.class_format.setFontWeight(QFont.Weight.Bold)
        self.highlighting_rules.append((re.compile(r'\bclass\s+[A-Za-z_][A-Za-z0-9_]*'), self.class_format))

        self.function_format = QTextCharFormat()
        self.function_format.setForeground(QColor("#00b395"))
        self.highlighting_rules.append((re.compile(r'\bdef\s+[A-Za-z_][A-Za-z0-9_]*'), self.function_format))

        # 4. Комментарии (Приглушенный серый)
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#5c7080"))
        self.highlighting_rules.append((re.compile(r'#[^\n]*'), self.comment_format))

        # 5. Строковые литералы (Светлый текст)
        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#e3e8ef"))
        self.highlighting_rules.append((re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'), self.string_format))
        self.highlighting_rules.append((re.compile(r"'[^'\\]*(\\.[^'\\]*)*'"), self.string_format))

        # 6. Числа (Оранжевый)
        self.number_format = QTextCharFormat()
        self.number_format.setForeground(QColor("#ffaa00"))
        self.highlighting_rules.append((re.compile(r'\b[0-9]+(?:\.[0-9]+)?\b'), self.number_format))

    def highlightBlock(self, text):
        """Автоматический перебор правил регулярных выражений при изменении текста"""
        for pattern, char_format in self.highlighting_rules:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, char_format)


class AIClientApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CyberCore - AI Station")
        self.resize(1300, 850)
        
        # Расширенная сетка шагов памяти контекста
        self.ctx_steps = {1: 1024, 2: 2048, 3: 4096, 4: 8192, 5: 16384, 6: 32768, 7: 65536, 8: 98304, 9: 131072, 10: 262144}
        
        # 🔥 НОВАЯ СЕТКА ШАГОВ ДЛЯ ЛИМИТА ВЫВОДА (num_predict)
        self.predict_steps = {1: 1024, 2: 2048, 3: 4096, 4: 8192, 5: 16384, 6: 32768}
        
        # 1. Загрузка баз данных и сессий чатов
        self.init_database()
        self.load_sessions_from_db()
        
        self.current_model = ""
        self.bot_response_buffer = "" 
        self.last_code_block = ""  
        self.attached_file_context = "" 
        self.attached_media_path = None
        
        self.btn_toggle_sidebar = None  

        # 🎙️ Инициализация локального микрофона Whisper
        self.voice_worker = VoiceWorker()
        self.voice_worker.text_recognized.connect(self.on_voice_text_received)
        self.voice_worker.status_updated.connect(self.on_voice_status_updated)

        # 🔊 Инициализация системного спикера Windows
        self.speech_process = QProcess(self)
        self.speech_queue = queue.Queue()  
        self._speech_buffer = ""
        
        # 📈 Запуск фонового замера ресурсов ПК
        self.hw_monitor = HardwareMonitor()
        self.hw_monitor.stats_updated.connect(self.update_hardware_stats)
        self.hw_monitor.start()




        self.sandbox_process = None
        self.worker = None 


        # 1. Сначала собираем интерфейс, меню и применяем тему (виджеты гарантированно создаются!)
        self.init_menu()
        self.init_ui()
        self.apply_cyberpunk_theme() 
        
        # 2. Активируем подсветку синтаксиса
        self.editor_highlighter = PythonSyntaxHighlighter(self.code_editor_field.document())
        
        # 3. Восстанавливаем сохраненные ползунки и сессии
        self.load_saved_settings()   
        if self.session_list_widget.count() > 0:
            first_chat = self.session_list_widget.item(0).text()
            self.switch_chat_session(first_chat)
        self.vision_models = []
        
        # 4. И СТРОГО В САМОМ КОНЦЕ ЗАПУСКАЕМ МОНИТОРИНГ И АВТО-СТАРТ СЕРВЕРА
        self.hw_monitor.start()

        # 📡 Запуск двустороннего моста Telegram
        from telegram_bridge import TelegramListenerWorker
        self.tg_bridge = TelegramListenerWorker()
        self.tg_bridge.status_log.connect(lambda msg: self.chat_area.append(f"<i style='color:#00ffcc;'>{msg}</i>"))
        self.tg_bridge.command_received.connect(self.on_telegram_command_received)
        self.tg_bridge.start()

        # 🔍 Запуск авто-анализатора логов llama-server в чат
        from server_log_analyzer import LlamaLogWatcherWorker
        llama_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Model", "LLAMA CCP", "llama_server.log")
        self.log_watcher = LlamaLogWatcherWorker(llama_log_path)
        self.log_watcher.log_translated.connect(lambda msg: self.chat_area.append(msg))
        self.log_watcher.start()

        
        QTimer.singleShot(100, self.start_portable_backend_server)

       


    def closeEvent(self, event):
        """❌ Вызывается автоматически при закрытии приложения пользователем. 
        Гарантированно гасит все фоновые процессы и освобождает ОЗУ/VRAM."""
        print("Инициализация полной очистки подсистем CyberCore (Portable)...")
        try:
            # 1. Мягко тушим внутренний объект отслеживания llama.cpp
            if hasattr(self, 'current_model') and self.current_model:
                from portable_backend import PortableLlamaEngine
                engine_dummy = PortableLlamaEngine("")
                engine_dummy.stop_server_process()
        except Exception:
            pass

        try:
            # 2. Остановка аппаратного монитора ресурсов ПК
            if hasattr(self, 'hw_monitor') and self.hw_monitor:
                self.hw_monitor.stop()
                self.hw_monitor.wait()
        except Exception:
            pass

        try:
            # 3. ЖЕСТКИЙ СИСТЕМНЫЙ КИЛЛ-СВИТЧ ДЛЯ LLAMA-SERVER
            import subprocess
            if os.name == 'nt':
                # Вырезаем зомби-процессы портативного движка llama.cpp
                subprocess.run("taskkill /f /t /im llama-server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("taskkill /f /t /im llama-server", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("taskkill /f /t /im server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Универсальная очистка для Unix-подобных систем
                subprocess.run("pkill -f llama-server", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 4. Освобождаем фоновые дескрипторы медиа-подсистем
            if hasattr(self, 'tts_handle') and self.tts_handle:
                try:
                    self.tts_handle.terminate()
                    self.tts_handle.wait(timeout=500)
                except Exception:
                    try: self.tts_handle.kill()
                    except Exception: pass
        except Exception as e:
            print(f"Критическое предупреждение при очистке памяти ОС: {e}")
        try:
            if hasattr(self, 'tg_bridge') and self.tg_bridge:
                self.tg_bridge.stop()
        except Exception:
            pass
            
        event.accept()


    def start_portable_backend_server(self):
        """🚀 Портативный запуск: автоматически находит GGUF, проверяет сокет 8080 и разворачивает сервер"""
        import time
        from PyQt6.QtWidgets import QProgressDialog, QFileDialog
        from PyQt6.QtCore import Qt
        from portable_backend import PortableLlamaEngine
        
        # 1. Сканируем папку на наличие локальных моделей GGUF
        detected_models = PortableLlamaEngine.get_local_gguf_models()
        if not detected_models:
            self.chat_area.append("<br><b style='color:orange;'>⚠️ [Система]: Внутри папки Model файлы .gguf не обнаружены! Развертывание прервано.</b><br>")
            self.status_label.setText("🔴 Файлы GGUF не найдены")
            return

        # 2. Пытаемся восстановить имя последней выбранной пользователем модели из БД
        # 2. Пытаемся восстановить имя последней выбранной пользователем модели из БД
        selected_model = ""
        try:
            self.db_cursor.execute("SELECT val FROM ui_settings WHERE key = 'selected_model_name'")
            row = self.db_cursor.fetchone()
            if row:
                saved_m = str(row[0]).strip().replace("\\", "/")
                saved_m = saved_m.replace("Model/LLAMA CCP/Model/", "").replace("Model/LLAMA CCP/", "")
                if saved_m.startswith("Model/"):
                    saved_m = saved_m[6:]
                selected_model = saved_m
        except Exception:
            pass

        # Если в БД пусто или сохраненная модель имеет битый путь — берем первую валидную из папки
        if not selected_model or selected_model not in detected_models:
            selected_model = detected_models[0]
            self.save_ui_setting("selected_model_name", selected_model)

        self.current_model = selected_model

        # 3. Проверяем, возможно нативный сервер уже запущен в системе и слушает порт 8080?
        engine_check = PortableLlamaEngine(self.current_model)
        if engine_check._check_server_alive():
            self.chat_area.append(f"<br><i style='color:#00ffcc;'>✅ [Система]: Локальное портативное ядро уже активно и обслуживает модель: <b>{os.path.basename(self.current_model)}</b></i>")
            self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
            self.load_installed_models() 
            return

        self.chat_area.append(f"<br><i style='color:#ffaa00;'>⏳ [Система]: Инициализация скрытого процесса llama-server для <b>{os.path.basename(self.current_model)}</b>...</i>")
        # 4. Асинхронный запуск подпроцесса движка
        try:
            engine = PortableLlamaEngine(self.current_model, self.get_ai_options())
            # Запускаем сервер без блокировки основного GUI-потока
            import threading
            threading.Thread(target=engine.start_server_if_needed, daemon=True).start()
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:#ff4444;'>❌ [Система]: Ошибка вызова подпроцесса ядра: {e}</b><br>")
            return
            
        # ... ДАЛЬШЕ КОД МЕТОДА ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ (Сборка и стилизация прогресс-бара) ...

        # 5. Сборка и стилизация прогресс-бара ожидания сокета
        progress = QProgressDialog("Развертывание портативного ядра нейросети...", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(5)
        
        progress.setStyleSheet("""
            QProgressDialog { background-color: #13171c; color: #00ffcc; font-weight: bold; border: 1px solid #005c4e; }
            QLabel { color: #00ffcc; }
            QProgressBar { border: 1px solid #005c4e; border-radius: 4px; text-align: center; color: #13171c; font-weight: bold; }
            QProgressBar::chunk { background-color: #00ffcc; }
            QPushButton { background-color: #1a1f26; color: #00ffcc; border: 1px solid #005c4e; padding: 3px 10px; }
        """)

        # Пошаговый цикл проверки доступности порта 8080 (таймаут 10 секунд)
        server_ready = False
        for i in range(1, 41):
            time.sleep(0.5) 
            progress.setValue(int(5 + (i * 4.5)))
            
            if progress.wasCanceled():
                self.chat_area.append("<br><b style='color:#ff4444;'>❌ [Система]: Ожидание запуска отменено пользователем.</b><br>")
                return
                
            if engine._check_server_alive():
                server_ready = True
                break

        progress.setValue(100)

        if server_ready:
            self.chat_area.append(f"<br><i style='color:#00ffcc;'>🚀 [Система]: Локальный сервер успешно запущен, порт 8080 активен!</i>")
            self.status_label.setText("🟢 Движок: Портативный")
            self.load_installed_models()
        else:
            self.chat_area.append("<br><b style='color:#ff4444;'>❌ [Система]: Превышено время ожидания. Порт 8080 не отвечает.</b>")
            self.chat_area.append("<b style='color:#ffaa00;'>Совет: Убедитесь, что файлы моделей GGUF исправны и лежат в папке Model.</b><br>")
            self.status_label.setText("🔴 Ошибка запуска ядра")
            
        self.chat_area.moveCursor(QTextCursor.MoveOperation.End)


    def parse_and_execute_agent_commands(self, text):
        """🔍 Исправленный парсер команд Агента с перехватом консоли"""
        if not self.agent_active_action.isChecked():
            return

        cmd_pattern = r"\[RUN_CMD:\s*(.*?)\]"
        url_pattern = r"\[OPEN_URL:\s*(.*?)\]"
        dir_pattern = r"\[MAKE_DIR:\s*(.*?)\]"
        file_pattern = r"\[CREATE_FILE:\s*([^|]+)\|([\s\S]*?)\]"

        executed_any = False
        # Выполнение команд с перехватом stdout/stderr
        for cmd in re.findall(cmd_pattern, text):
            cmd = cmd.strip()
            try:
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Выполняю команду '{cmd}'...</i>")
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                stdout_msg = f"<br><b>Вывод:</b><pre>{result.stdout}</pre>" if result.stdout.strip() else ""
                stderr_msg = f"<br><b>Ошибка:</b><pre style='color:red;'>{result.stderr}</pre>" if result.stderr.strip() else ""
                self.chat_area.append(stdout_msg + stderr_msg)
                
                feedback = f"[РЕЗУЛЬТАТ ВЫПОЛНЕНИЯ КОМАНДЫ {cmd}]:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                self.chat_history.append({"role": "user", "content": feedback})
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:red;'>❌ [Агент]: Ошибка: {e}</b>")

        # Создание файлов [CREATE_FILE: путь|текст]
        for filename, content in re.findall(file_pattern, text):
            filename = filename.strip()
            content = content.strip()
            try:
                dirname = os.path.dirname(filename)
                if dirname: os.makedirs(dirname, exist_ok=True)
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Записан файл '{filename}'</i>")
                self.chat_history.append({"role": "user", "content": f"[АГЕНТ СИСТЕМЫ]: Файл успешно записан: {filename}"})
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:red;'>❌ [Агент]: Ошибка записи файла: {e}</b>")

        # Остальные теги (папки и ссылки)
        for folder_path in re.findall(dir_pattern, text):
            folder_path = folder_path.strip()
            try:
                os.makedirs(folder_path, exist_ok=True)
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Создана директория '{folder_path}'</i>")
                self.chat_history.append({"role": "user", "content": f"[АГЕНТ СИСТЕМЫ]: Папка создана: {folder_path}"})
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:red;'>❌ [Агент]: Ошибка создания папки: {e}</b>")

        for url in re.findall(url_pattern, text):
            url = url.strip()
            try:
                webbrowser.open(url)
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Открыта ссылка '{url}'</i>")
                self.chat_history.append({"role": "user", "content": f"[АГЕНТ СИСТЕМЫ]: Ссылка открыта в браузере: {url}"})
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:red;'>❌ [Агент]: Ошибка открытия ссылки: {e}</b>")

        if executed_any:
            self.chat_area.moveCursor(QTextCursor.MoveOperation.End)

    def toggle_sidebar_visibility(self):
        """🔘 Сворачивает или разворачивает левое окно истории чатов"""
        if self.session_sidebar.isVisible():
            self.session_sidebar.hide()
            self.btn_toggle_sidebar.setText("▶")
        else:
            self.session_sidebar.show()
            self.btn_toggle_sidebar.setText("◀")


    def clear_chat_context(self):
        """🗑️ Полный сброс памяти: очистка массивов, истории и обнуление счетчика токенов"""
        # 1. Тотальное обнуление текущей сессии в словарях памяти приложений
        self.chat_sessions[self.current_session] = []
        self.chat_html_history[self.current_session] = ""
        
        # 2. Очищаем активную историю, которая улетает в payload к серверу
        if hasattr(self, 'chat_history'):
            self.chat_history = []
            
        # 3. Полный сброс текстовых буферов генерации и озвучки
        self.bot_response_buffer = ""
        self._speech_buffer = ""
        self.last_code_block = ""
        
        # 4. Очистка визуального текстового поля
        self.chat_area.clear()
        self.chat_area.append(f"<i>🟢 Память сессии '{self.current_session}' полностью очищена. Контекст сброшен в ноль.</i><br><br>")
        
        # 5. Принудительное ручное обнуление графического интерфейса счетчиков
        max_ctx = int(self.ctx_steps.get(self.slider_ctx.value(), 2048))
        self.lbl_token_usage.setText(f"Занято: 0 / {max_ctx} токенов (0%)")
        self.lbl_generation_speed.setText("Скорость ИИ: 0.0 tok/sec")
        
        # 6. Синхронизируем пустую сессию с локальной базой данных SQLite
        self.save_session_to_db(self.current_session)


    def on_voice_status_updated(self, status_text):
        """Обновляет статус записи голоса"""
        self.status_label.setText(status_text)
        if "❌" in status_text:
            self.btn_voice.setChecked(False)
            self.btn_voice.setText("🎙️ Голосовой ввод")
            self.btn_voice.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")

    def open_chat_context_menu(self, position):
        """📂 Всплывающее контекстное меню по правой кнопке мыши для списка чатов"""
        item = self.session_list_widget.itemAt(position)
        if not item: return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #13171c; border: 1px solid #005c4e; color: #00ffcc; padding: 2px; }
            QMenu::item:selected { background-color: #ff0055; color: #ffffff; }
        """)
        delete_action = QAction("🗑️ Удалить этот чат", self)
        delete_action.triggered.connect(lambda: self.delete_chat_session(item.text()))
        menu.addAction(delete_action)
        menu.exec(self.session_list_widget.mapToGlobal(position))

    def on_file_tree_double_clicked(self, index):
        """📄 Двойной клик по дереву: загружает текстовые файлы прямо в редактор кода"""
        file_path = self.file_model.filePath(index)
        if os.path.isfile(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in [".py", ".txt", ".log", ".ino", ".json", ".bat"]:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    self.code_editor_field.setPlainText(content)
                    self.last_code_block = content
                    self.bottom_tabs.setCurrentIndex(1) # Переключаем на вкладку "Редактор кода"
                    self.chat_area.append(f"<br><i style='color:#00ffcc;'>[CyberCore UI]: Файл {os.path.basename(file_path)} успешно открыт в редакторе!</i><br>")
                except Exception as e:
                    self.chat_area.append(f"<b style='color:red;'>Ошибка открытия файла: {e}</b><br>")

    def open_file_tree_context_menu(self, position):
        """🗑️ Вызов меню удаления для файлов воркспейса по правой кнопке мыши"""
        index = self.file_tree_view.indexAt(position)
        if not index.isValid(): return
        
        file_path = self.file_model.filePath(index)
        is_dir = self.file_model.isDir(index)
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #13171c; border: 1px solid #005c4e; color: #00ffcc; padding: 2px; }
            QMenu::item:selected { background-color: #d9534f; color: #ffffff; }
        """)
        
        delete_action = QAction(f"🗑️ Удалить {'папку' if is_dir else 'файл'}", self)
        def handle_delete():
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "Удаление объекта", 
                f"Вы уверены, что хотите окончательно удалить {os.path.basename(file_path)}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    if is_dir:
                        import shutil
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                    self.chat_area.append(f"<br><b style='color:#ff0055;'>🔴 [CyberCore UI]: Объект {os.path.basename(file_path)} стерт с диска.</b><br>")
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка", f"Не удалось удалить: {e}")
                    
        delete_action.triggered.connect(handle_delete)
        menu.addAction(delete_action)
        menu.exec(self.file_tree_view.mapToGlobal(position))

    def delete_chat_session(self, session_name):
        """🗄️ Полное удаление чата из памяти приложения и локальной базы данных SQLite"""
        if self.session_list_widget.count() <= 1:
            self.chat_area.append("<br><b style='color:orange;'>Система: Нельзя удалить единственный активный чат!</b><br>")
            return
        try:
            if session_name in self.chat_sessions: del self.chat_sessions[session_name]
            if session_name in self.chat_html_history: del self.chat_html_history[session_name]
            if session_name in self.chat_individual_settings: del self.chat_individual_settings[session_name]
            self.db_cursor.execute("DELETE FROM chat_sessions WHERE name = ?", (session_name,))
            self.db_conn.commit()
            self.session_list_widget.blockSignals(True)
            self.session_list_widget.clear()
            for k in self.chat_sessions.keys(): self.session_list_widget.addItem(k)
            self.session_list_widget.blockSignals(False)
            first_remaining = list(self.chat_sessions.keys())[0]
            self.switch_chat_session(first_remaining)
            for i in range(self.session_list_widget.count()):
                if self.session_list_widget.item(i).text() == first_remaining:
                    self.session_list_widget.setCurrentRow(i)
                    break
            self.chat_area.append(f"<br><b style='color:#ff0055;'>🔴 Система: Чат '{session_name}' успешно удален.</b><br>")
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>Система: Ошибка при удалении чата: {str(e)}</b><br>")

    def init_database(self):
        """🗄️ Создает таблицы для автоматического сохранения всей истории и ползунков"""
        try:
            self.db_conn = sqlite3.connect("ai_combain.db")
            self.db_cursor = self.db_conn.cursor()
            
            self.db_cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    name TEXT PRIMARY KEY, 
                    json_history TEXT, 
                    html_history TEXT
                )""")
            try:
                self.db_cursor.execute("SELECT settings FROM chat_sessions LIMIT 1")
            except sqlite3.OperationalError:
                self.db_cursor.execute("ALTER TABLE chat_sessions ADD COLUMN settings TEXT")
                self.db_conn.commit()

            self.db_cursor.execute("""
                CREATE TABLE IF NOT EXISTS ui_settings (
                    key TEXT PRIMARY KEY, val REAL
                )""")
            self.db_conn.commit()
        except Exception as e:
            print(f"Ошибка БД: {e}")

    def load_sessions_from_db(self):
        """Загружает сохраненные чаты и их уникальные настройки из SQLite"""
        self.chat_sessions = {}
        self.chat_html_history = {}
        self.chat_individual_settings = {}
        
        try:
            self.db_cursor.execute("SELECT name, json_history, html_history, settings FROM chat_sessions")
            rows = self.db_cursor.fetchall()
            for row in rows:
                try:
                    session_name = str(row[0])
                    self.chat_sessions[session_name] = json.loads(row[1])
                    self.chat_html_history[session_name] = str(row[2])
                    if len(row) > 3 and row[3]:
                        self.chat_individual_settings[session_name] = json.loads(row[3])
                    else:
                        self.chat_individual_settings[session_name] = {}
                except Exception as row_err:
                    print(f"Ошибка восстановления сессии: {row_err}")
                    continue
        except Exception as e:
            print(f"Ошибка чтения сессий из БД: {e}")
            
        if not self.chat_sessions:
            self.chat_sessions = {"Чат 1": []}
            self.chat_html_history["Чат 1"] = "<i>Система: Начало нового диалога.</i><br><br>"
            self.chat_individual_settings["Чат 1"] = {}
        
        self.current_session = list(self.chat_sessions.keys())[0]

    def save_session_to_db(self, session_name):
        """Сохраняет измененную вкладку диалога и её настройки в базу данных"""
        try:
            json_str = json.dumps(self.chat_sessions.get(session_name, []))
            html_str = self.chat_html_history.get(session_name, "")
            
            current_settings = {
                "model": self.model_selector.currentText(),
                "temp": self.slider_temp.value(),
                "topp": self.slider_topp.value(),
                "topk": self.slider_topk.value(),
                "miro": self.slider_miro.value(),
                "penalty": self.slider_penalty.value(),
                "freq": self.slider_freq_penalty.value(),
                "pres": self.slider_pres_penalty.value(),
                "ctx": self.slider_ctx.value(),
                "predict": self.slider_predict.value(),
                "threads": self.slider_threads.value()
            }
            self.chat_individual_settings[session_name] = current_settings
            settings_str = json.dumps(current_settings)

            self.db_cursor.execute(
                "INSERT OR REPLACE INTO chat_sessions (name, json_history, html_history, settings) VALUES (?, ?, ?, ?)",
                (session_name, json_str, html_str, settings_str)
            )
            self.db_conn.commit()
        except Exception as e:
            print(f"Ошибка сохранения сессии: {e}")
    def attach_local_file(self):
        """📎 Безопасное чтение файлов с поддержкой кодировок Windows, Arduino (.ino) и пакетного выбора"""
        try:
            # Изменено на getOpenFileNames для поддержки мультивыбора
            result = QFileDialog.getOpenFileNames(
                self, "Прикрепить документы для анализа", "", 
                "Документы (*.txt *.py *.log *.ino *.pdf *.docx)"
            )
            
            # getOpenFileNames возвращает кортеж (список_путей, фильтр)
            if not result or not result[0]: 
                return
                
            file_paths = result[0]  # Извлекаем чистый список путей к файлам
            self.attached_file_context = ""
            successful_files = []
            total_characters = 0

            for current_path in file_paths:
                file_path = current_path.strip()
                if not os.path.exists(file_path):
                    continue
                    
                ext = os.path.splitext(file_path)[1].lower().strip()
                text_content = ""

                if ext in [".txt", ".py", ".log", ".ino"]:
                    encodings_to_try = ['utf-8', 'utf-8-sig', 'cp1251', 'utf-16', 'cp866', 'latin-1']
                    success = False
                    for enc in encodings_to_try:
                        try:
                            with open(file_path, "r", encoding=enc, errors="strict") as f: 
                                text_content = f.read()
                            success = True
                            break
                        except (UnicodeDecodeError, Exception):
                            continue
                    
                    if not success:
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                                text_content = f.read()
                        except Exception as e:
                            self.chat_area.append(f"<b style='color:red;'>Ошибка файловой системы ({os.path.basename(file_path)}): {e}</b><br>")
                            continue

                elif ext == ".pdf":
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(file_path)
                        text_content = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                    except Exception as e:
                        self.chat_area.append(f"<b style='color:red;'>Ошибка PDF-модуля ({os.path.basename(file_path)}): {e}</b><br>")
                        continue
                        
                elif ext == ".docx":
                    try:
                        import docx
                        doc = docx.Document(file_path)
                        text_content = "\n".join([p.text for p in doc.paragraphs])
                    except Exception as e:
                        self.chat_area.append(f"<b style='color:red;'>Ошибка Word-модуля ({os.path.basename(file_path)}): {e}</b><br>")
                        continue
                
                if text_content and text_content.strip():
                    self.attached_file_context += f"\n=== СВЕДЕНИЯ ИЗ ДОКУМЕНТА ({os.path.basename(file_path)}):\n{text_content.strip()}\n===\n"
                    successful_files.append(os.path.basename(file_path))
                    total_characters += len(text_content)

            if successful_files:
                files_str = ", ".join(successful_files)
                self.chat_area.append(f"<i>📎 Система: Успешно считан пакет файлов [{files_str}] (Всего: {total_characters} симв.).</i><br>")
                self.btn_attach_file.setText(f"📄 Загружено ({len(successful_files)})")
                self.btn_attach_file.setStyleSheet("background-color: #005c4e; color: #00ffcc; font-weight: bold;")
            else:
                self.chat_area.append(f"<b style='color:orange;'>Система: Выбранные файлы пусты, заблокированы или защищены от чтения!</b><br>")
                
        except Exception as global_err:
            self.chat_area.append(f"<b style='color:red;'>Система: Сбой файлового менеджера при пакетной загрузке: {str(global_err)}</b><br>")


    def save_code_from_editor(self):
        """💾 Сохраняет текущее содержимое вкладки-редактора в файл .py на диске"""
        code_text = self.code_editor_field.toPlainText().strip()
        if not code_text:
            self.chat_area.append("<br><b style='color:orange;'>Система: Редактор кода пуст. Нечего сохранять!</b><br>")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Сохранить скрипт Python", "script.py", "Файлы Python (*.py)")
        if not file_path: return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code_text)
            self.chat_area.append(f"<br><b style='color:#5cb85c;'>🟢 Система: Код успешно экспортирован на ПК в файл: {os.path.basename(file_path)}</b><br>")
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>🔴 Система: Ошибка сохранения файла: {str(e)}</b><br>")


    def run_code_in_sandbox(self):
        """💻 Запуск кода из Вкладки-Редактора с системой авто-отладки CyberCore (Self-Healing)"""
        current_code = self.code_editor_field.toPlainText().strip()
        
        if not current_code and hasattr(self, 'last_code_block') and self.last_code_block.strip():
            current_code = self.last_code_block
            self.code_editor_field.setText(current_code)

        if not current_code:
            self.chat_area.append("<br><b style='color:orange;'>[CyberCore]: Редактор кода пуст! Нечего запускать.</b><br>")
            return
            
        self.chat_area.append("<br><b style='color:#00ffcc;'>🔄 Песочница: Запуск изолированного подпроцесса CyberCore...</b><br>")
        
        # Защита от зомби-процессов: если старый процесс запущен, принудительно убиваем его
        if hasattr(self, 'sandbox_process') and self.sandbox_process and self.sandbox_process.state() == QProcess.ProcessState.Running:
            self.sandbox_process.kill()
            self.sandbox_process.waitForFinished(1000)

        temp_file = os.path.join(os.getcwd(), "sandbox_temp.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f: 
                f.write(current_code)
        except Exception as e:
            self.chat_area.append(f"<b style='color:red;'>Песочница: Ошибка записи: {e}</b><br>")
            return

        self.sandbox_process = QProcess(self)
        
        def on_sandbox_finished(exit_code, exit_status):
            raw_out = self.sandbox_process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
            raw_err = self.sandbox_process.readAllStandardError().data().decode('utf-8', errors='ignore')
            
            self.chat_area.append("<b>💻 Результат выполнения в CyberCore:</b>")
            if raw_out.strip():
                self.chat_area.append(f"<pre style='color:#5cb85c; background:#13171c; padding:8px; border:1px solid #005c4e; border-radius:4px;'>{raw_out}</pre>")
            
            if raw_err.strip():
                self.chat_area.append(f"<pre style='color:#d9534f; background:#13171c; padding:8px; border-radius:4px;'>{raw_err}</pre>")
                self.chat_area.append("<br><b style='color:#ffaa00;'>🚨 [CyberCore]: Обнаружен сбой скрипта! Активирую автоматический ИИ-отладчик...</b><br>")
                self.trigger_ai_self_healing(current_code, raw_err)
                return  # Прерываем выполнение, чтобы нижний блок не срабатывал ложно
                
            if not raw_out.strip() and not raw_err.strip():
                self.chat_area.append("<i style='color:gray;'>[Скрипт успешно завершился без вывода на экран]</i><br>")
                
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except Exception: pass

        self.sandbox_process.finished.connect(on_sandbox_finished)
        self.sandbox_process.start(sys.executable, [temp_file])

        
    def trigger_ai_self_healing(self, broken_code, traceback_error):
        """🔧 Модуль автоматического восстановления кода локальной нейросетью (Portable)"""
        if not self.current_model:
            self.chat_area.append("<b style='color:red;'>[Отладчик]: Ошибка исправления. Не выбрана активная модель ИИ.</b><br>")
            return

        # Формируем изолированный жесткий промпт для исправления дефекта
        healing_prompt = (
            f"Ты — встроенный модуль отладки CyberCore Sandbox. Программа упала со следующим исключением:\n"
            f"--- ОШИБКА / TRACEBACK ---\n{traceback_error}\n\n"
            f"--- ИСХОДНЫЙ ДЕФЕКТНЫЙ КОД ---\n```python\n{broken_code}\n```\n\n"
            f"Найди причину падения скрипта. Выдай ИСПРАВЛЕННЫЙ код целиком внутри ОДНОГО блока кода Markdown (```python ... ```). "
            f"Не пиши лишних объяснений, только исправленный рабочий вариант."
        )

        self.chat_area.append(f"<i>⏳ Модель <b>{os.path.basename(self.current_model)}</b> анализирует стек ошибки и переписывает код...</i><br>")
        
        # Готовим пакет данных
        messages = [{"role": "user", "content": healing_prompt}]
        ollama_options = self.get_ai_options()
        ollama_options["temperature"] = 0.0 

        # Блокируем кнопку отправки на время отладки
        self.send_btn.setText("⏳ Исправление...")
        self.send_btn.setEnabled(False)

        # Передаем True четвертым аргументом для работы строго через llama-server
        self.healing_worker = AIWorker(str(self.current_model).strip(), messages, ollama_options, is_portable_backend=True)
        self.healing_buffer = ""
        
        def handle_healing_chunk(text):
            self.healing_buffer += text

        def handle_healing_finished():
            self.send_btn.setText("⚡ Отправить")
            self.send_btn.setEnabled(True)
            
            code_blocks = re.findall(r'```python\n([\s\(\S\)]*?)(?:```|$)', self.healing_buffer)
            if not code_blocks:
                code_blocks = re.findall(r'```([\s\(\S\)]*?)(?:```|$)', self.healing_buffer)

            if code_blocks and code_blocks[0].strip():
                fixed_code = code_blocks[0].strip()
                self.code_editor_field.setPlainText(fixed_code)
                self.last_code_block = fixed_code
                
                self.chat_area.append(
                    "<br><b style='color:#5cb85c;'>✅ [CyberCore]: Скрипт успешно реанимирован! "
                    "Исправленная версия загружена во вкладку 'Редактор кода'. Нажмите 'Старт' для повторной проверки.</b><br>"
                )
                self.bottom_tabs.setCurrentIndex(1)
            else:
                self.chat_area.append("<br><b style='color:orange;'>[CyberCore]: ИИ предложил решение, но не смог обернуть его в валидный блок кода. Проверьте чат.</b><br>")

        self.healing_worker.response_received.connect(handle_healing_chunk)
        self.healing_worker.finished.connect(handle_healing_finished)
        self.healing_worker.start()


    def copy_last_code_block(self):
        """Копирует текущее содержимое текстового поля редактора кода"""
        code_text = self.code_editor_field.toPlainText().strip()
        if not code_text and hasattr(self, 'last_code_block'):
            code_text = self.last_code_block
        
        if code_text.strip():
            QApplication.clipboard().setText(code_text.strip())
            self.btn_copy_code.setText("✅ Скопировано!")
            QTimer.singleShot(2000, lambda: self.btn_copy_code.setText("📋 Буфер"))
        else:
            self.btn_copy_code.setText("❌ Пусто")
            QTimer.singleShot(2000, lambda: self.btn_copy_code.setText("📋 Буфер"))
    def export_chat_to_markdown(self):
        current_history = self.chat_sessions.get(self.current_session, [])
        if not current_history:
            self.chat_area.append("<br><b style='color:orange;'>Система: История чата пуста!</b><br>")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчет чата", f"{self.current_session}_report.md", "Markdown Файлы (*.md)")
        if not file_path: return
        try:
            md_content = [f"# Отчет генерации ИИ — {self.current_session}\n", f"**Модель:** {self.current_model}\n", "---\n"]
            for msg in current_history:
                role = "### 🧑 Пользователь" if msg["role"] == "user" else "### 🤖 Системная роль" if msg["role"] == "system" else "### 💻 ИИ-Ассистент"
                md_content.append(f"{role}:\n{msg['content']}\n\n---\n")
            with open(file_path, "w", encoding="utf-8") as f: f.write("\n".join(md_content))
            self.chat_area.append(f"<br><b style='color:#5cb85c;'>🟢 Система: Чат сохранен в: {os.path.basename(file_path)}</b><br>")
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>🔴 Система: Ошибка экспорта: {str(e)}</b><br>")

# СТАЛО:
    def update_token_counter(self):
        """Расчет занятых токенов в текущей сессии с оптимизацией частоты вызовов для защиты от фризов GUI"""
        try:
            # Инициализируем внутренний счетчик пропущенных чанков для снижения нагрузки на CPU
            if not hasattr(self, '_token_counter_skip_frames'):
                self._token_counter_skip_frames = 0
            
            # Если ИИ прямо сейчас генерирует текст, выполняем расчет только каждый 40-й вызов
            if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
                self._token_counter_skip_frames += 1
                if self._token_counter_skip_frames % 40 != 0:
                    return

            max_ctx = int(self.ctx_steps.get(self.slider_ctx.value(), 4096))
            current_history = []
            if hasattr(self, 'chat_history') and self.chat_history:
                current_history = self.chat_history
            elif hasattr(self, 'chat_sessions') and self.current_session in self.chat_sessions:
                current_history = self.chat_sessions[self.current_session]
            
            # Высокоскоростное слияние строк через генератор списка вместо конкатенации в цикле +=
            chunks = [str(msg.get("content", "")) for msg in current_history]
            if hasattr(self, 'bot_response_buffer') and self.bot_response_buffer:
                chunks.append(self.bot_response_buffer)
            
            total_text = " ".join(chunks)
            total_len = len(total_text)
            
            # Быстрый атомарный подсчет
            if total_len < 10:
                tokens_used = 0
            else:
                try:
                    import tiktoken
                    encoding = tiktoken.get_encoding("cl100k_base")
                    tokens_used = len(encoding.encode(total_text))
                except ImportError:
                    tokens_used = int(total_len / 3.8) + 1
            
            percentage = min(int((tokens_used / max_ctx) * 100), 100)
            self.lbl_token_usage.setText(f"Занято: {tokens_used} / {max_ctx} токенов ({percentage}%)")
        except Exception as e: 
            print(f"⚠️ [TokenCounter Exception]: {e}")

    def save_ui_setting(self, key, val):
        """Сохранение параметров интерфейса и конфигураций в базу данных SQLite"""
        try:
            self.db_cursor.execute("INSERT OR REPLACE INTO ui_settings (key, val) VALUES (?, ?)", (key, str(val)))
            self.db_conn.commit()
        except Exception: 
            pass

    def load_saved_settings(self):
        """Загрузка конфигурации ползунков и глобальных чекбоксов из SQLite при старте"""
        try:
            self.db_cursor.execute("SELECT key, val FROM ui_settings")
            rows = self.db_cursor.fetchall()
            settings = {row[0]: row[1] for row in rows}
            
            def get_int(k, default_v):
                try:
                    return int(float(settings.get(k, default_v)))
                except Exception:
                    return int(default_v)

            t_v = get_int("temp", 2)
            topp_v = get_int("topp", 9)
            topk_v = get_int("topk", 40)
            miro_v = get_int("miro", 0)
            pen_v = get_int("penalty", 11)
            freq_v = get_int("freq", 0)
            pres_v = get_int("pres", 0)
            ctx_v = get_int("ctx", 7)
            thr_v = get_int("threads", 12)
            
            predict_val = get_int("predict", 3)
            if predict_val > 6 or predict_val < 1:
                predict_val = 3

            self.slider_temp.blockSignals(True); self.slider_temp.setValue(t_v); self.slider_temp.blockSignals(False)
            self.slider_topp.blockSignals(True); self.slider_topp.setValue(topp_v); self.slider_topp.blockSignals(False)
            self.slider_topk.blockSignals(True); self.slider_topk.setValue(topk_v); self.slider_topk.blockSignals(False)
            self.slider_miro.blockSignals(True); self.slider_miro.setValue(miro_v); self.slider_miro.blockSignals(False)
            self.slider_penalty.blockSignals(True); self.slider_penalty.setValue(pen_v); self.slider_penalty.blockSignals(False)
            self.slider_freq_penalty.blockSignals(True); self.slider_freq_penalty.setValue(freq_v); self.slider_freq_penalty.blockSignals(False)
            self.slider_pres_penalty.blockSignals(True); self.slider_pres_penalty.setValue(pres_v); self.slider_pres_penalty.blockSignals(False)
            self.slider_ctx.blockSignals(True); self.slider_ctx.setValue(ctx_v); self.slider_ctx.blockSignals(False)
            self.slider_predict.blockSignals(True); self.slider_predict.setValue(predict_val); self.slider_predict.blockSignals(False)
            self.slider_threads.blockSignals(True); self.slider_threads.setValue(thr_v); self.slider_threads.blockSignals(False)
            
            # Синхронизируем текстовые индикаторы рядом со слайдерами
            self.lbl_temp_val.setText(str(t_v / 10.0))
            self.lbl_topp_val.setText(str(topp_v / 10.0))
            self.lbl_topk_val.setText(str(topk_v))
            self.lbl_miro_val.setText(str(miro_v))
            self.lbl_penalty_val.setText(str(pen_v / 10.0))
            self.lbl_freq_val.setText(str(freq_v / 10.0))
            self.lbl_pres_val.setText(str(pres_v / 10.0))
            self.lbl_ctx_val.setText(str(self.ctx_steps.get(ctx_v, 65536)))
            self.lbl_predict_val.setText(str(self.predict_steps.get(predict_val, 4096)))
            self.lbl_threads_val.setText(str(thr_v))

            if "kv_compress" in settings:
                self.cb_kv_compress.setChecked(bool(get_int("kv_compress", 0)))

            if "np_slots" in settings:
                np_v = get_int("np_slots", 1)
                self.slider_np.blockSignals(True)
                self.slider_np.setValue(np_v)
                self.slider_np.blockSignals(False)
                self.lbl_np_val.setText(str(np_v))
            if "no_kv_offload" in settings:
                self.cb_no_kv_offload.setChecked(bool(get_int("no_kv_offload", 0)))
           
                
            if "speech_on" in settings: 
                self.cb_speech_on.setChecked(bool(get_int("speech_on", 0)))

            if "enable_thinking" in settings:
                self.cb_thinking.setChecked(bool(get_int("enable_thinking", 0)))

            if "max_steps" in settings:
                ms_v = get_int("max_steps", 100)
                self.slider_max_steps.blockSignals(True)
                self.slider_max_steps.setValue(ms_v)
                self.slider_max_steps.blockSignals(False)
                self.lbl_max_steps_val.setText(str(ms_v))

            self.update_token_counter()
        except Exception as e: 
            print(f"Ошибка восстановления глобальных настроек: {e}")


    def update_hardware_stats(self, cpu_p, ram_p, gpu_p, vram_p):
        """📈 Отображение текущей утилизации ресурсов процессора, памяти и видеокарты"""
        self.lbl_sys_cpu.setText(f"Загрузка CPU: {cpu_p:.1f}%")
        self.lbl_sys_ram.setText(f"Использование RAM: {ram_p:.1f}%")
        if hasattr(self, 'lbl_sys_gpu'):
            self.lbl_sys_gpu.setText(f"Загрузка GPU : {gpu_p:.1f}%")
            if gpu_p > 50.0:
                self.lbl_sys_gpu.setStyleSheet("color: #ffaa00; font-weight: bold;")
            else:
                self.lbl_sys_gpu.setStyleSheet("color: #00b395;")

    def check_server_status(self):
        """Проверка доступности локального API сервера инференса по порту 8080"""
        try:
            response = requests.get("http://localhost:8080/health", timeout=2)
            if response.status_code == 200:
                self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
                self.load_installed_models()
            else:
                self.status_label.setText(f"🔴 Ошибка ядра (Код: {response.status_code})")
        except Exception:
            self.status_label.setText("❌ Сервер нейросети выключен")
            self.chat_area.clear()
            self.chat_area.append(
                "<b style='color: #d9534f;'>Портативное ядро llama-server не отвечает на порту 8080!</b><br>"
                "Запустите его вручную или выберите: Меню -> Сервис -> Запустить локальный сервер.<br><br>"
            )

    def load_installed_models(self):
        """Загрузка списка локально установленных ИИ-моделей (.gguf) с диска ПК"""
        from portable_backend import PortableLlamaEngine
        try:
            self.model_selector.blockSignals(True)
            self.model_selector.clear()
            
            # Нативно вычитываем файлы .gguf из папки Model/LLAMA CCP/Model
            extracted_models = PortableLlamaEngine.get_local_gguf_models()
            
            if not extracted_models:
                self.status_label.setText("⚠️ Модели GGUF не найдены")
                self.model_selector.blockSignals(False)
                return
                
            # Заполняем выпадающий список чистыми именами файлов
            for model_name in extracted_models:
                if model_name: 
                    self.model_selector.addItem(str(model_name).strip())
            
            # Восстановление последней выбранной модели из настроек UI
            saved_model = ""
            try:
                self.db_cursor.execute("SELECT val FROM ui_settings WHERE key = 'selected_model_name'")
                row = self.db_cursor.fetchone()
                if row: 
                    saved_model = str(row[0]).replace("('", "").replace("',)", "").strip()
            except Exception:
                pass
            index_to_set = 0
            if saved_model:
                found_index = self.model_selector.findText(saved_model)
                if found_index != -1:
                    index_to_set = found_index
                    
            self.model_selector.setCurrentIndex(index_to_set)
            self.current_model = self.model_selector.itemText(index_to_set)
            
            self.model_selector.blockSignals(False)
            
            # Обновляем статус готовности, если сокет отвечает
            from portable_backend import PortableLlamaEngine
            engine_check = PortableLlamaEngine(self.current_model)
            if engine_check._check_server_alive():
                self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
            else:
                self.status_label.setText("⚪ Движок: Ожидание запуска")
        except Exception as e: 
            print(f"Ошибка заполнения списка GGUF моделей: {e}")
            self.model_selector.blockSignals(False)

    def init_menu(self):
        """📂 Верхняя строка меню: Файл, Сервис, Справка"""
        menu_bar = self.menuBar()
        
        # Меню Файл
        file_menu = menu_bar.addMenu("Файл")
        export_action = QAction("📂 Экспортировать чат в Markdown...", self)
        export_action.triggered.connect(self.export_chat_to_markdown)
        file_menu.addAction(export_action)
        connect_action = QAction("Подключить модель (.gguf)...", self)
        connect_action.triggered.connect(self.import_gguf_model)
        file_menu.addAction(connect_action)
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Меню Сервис
        # Меню Сервис
        service_menu = menu_bar.addMenu("Сервис")
        start_ollama_action = QAction("🚀 Запустить локальный сервер", self)
        # ЖЕСТКАЯ ПРИВЯЗКА К НОВОМУ ПОРТАТИВНОМУ МЕТОДУ ВСЕГДА
        start_ollama_action.triggered.connect(self.start_portable_backend_server)
        service_menu.addAction(start_ollama_action)


        self.raw_debug_action = QAction("📋 СЫРОЙ ОТВЕТ ИИ (Отладка)", self, checkable=True)
        try:
            self.db_cursor.execute("SELECT val FROM ui_settings WHERE key = 'raw_debug_enabled'")
            row = self.db_cursor.fetchone()
            if row: self.raw_debug_action.setChecked(bool(int(row[0])))
        except Exception: pass
        
        self.raw_debug_action.triggered.connect(self.toggle_raw_debug_mode)
        service_menu.addAction(self.raw_debug_action)

        # Меню Справка
        help_menu = menu_bar.addMenu("Справка")
        
        about_action = QAction("ℹ️ О программе...", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)
        
        all_tools_action = QAction("🛠️ Каталог всех инструментов ИИ", self)
        all_tools_action.triggered.connect(self.show_all_tools_help_dialog)
        help_menu.addAction(all_tools_action)
        
        diffusion_help_action = QAction("🎨 Справка: Генерация графики (SD)", self)
        diffusion_help_action.triggered.connect(self.show_diffusion_help_dialog)
        help_menu.addAction(diffusion_help_action)
        
        agent_help_action = QAction("🔌 Справка: ИИ Агент", self)
        agent_help_action.triggered.connect(self.show_agent_help_dialog)
        help_menu.addAction(agent_help_action)
        
        sliders_help_action = QAction("⚙️ Справка: Ползунки и чекбоксы ИИ", self)
        sliders_help_action.triggered.connect(self.show_sliders_help_dialog)
        help_menu.addAction(sliders_help_action)

        telegram_help_action = QAction("📲 Справка: Настройка Telegram-бота", self)
        telegram_help_action.triggered.connect(self.show_telegram_help_dialog)
        help_menu.addAction(telegram_help_action)

        server_flags_help_action = QAction("🚀 Справка: Флаги запуска сервера (Vulkan / GPU)", self)
        server_flags_help_action.triggered.connect(self.show_server_flags_help_dialog)
        help_menu.addAction(server_flags_help_action)

        
    def show_agent_help_dialog(self):
        """📂 Расширенное окно документации по возможностям ИИ-Агента в фирменном стиле"""
        from PyQt6.QtWidgets import QMessageBox, QSpacerItem, QGridLayout, QSizePolicy
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Документация: ИИ Агент Автоматизации ПК")
        
        help_text = (
            "<h2>🔌 Руководство по ИИ Агенту автоматизации</h2>"
            "Когда в меню <b>Сервис</b> активен режим Агента, модель получает скрытую системную "
            "инструкцию. Она позволяет ИИ управлять вашей операционной системой в фоновом режиме "
            "с помощью специальных синтаксических макросов (тегов).<br><br>"
            "<h3>📂 1. Управление файловой системой</h3>"
            "• <code>[MAKE_DIR: путь_к_папке]</code> — Создание дерева директорий.<br>"
            "• <code>[CREATE_FILE: путь/имя.ext|содержимое]</code> — Запись текста или кода на диск.<br><br>"
            "<h3>💻 2. Запуск системных утилит и команд</h3>"
            "• <code>[RUN_CMD: команда]</code> — Исполнение строки в командной оболочке.<br>"
            "• <b>Стандартные утилиты Windows:</b> <code>calc</code>, <code>notepad</code>, <code>explorer</code>, <code>taskmgr</code>.<br><br>"
            "<h3>🌐 3. Веб-автоматизация</h3>"
            "• <code>[OPEN_URL: ссылка]</code> — Открытие веб-сайтов в браузере.<br><br>"
            "<h3>⚠️ Внимание и безопасность:</h3>"
            "Так как макросы выполняются через оболочку вашей ОС, ИИ имеет прямой доступ к файловой системе. "
            "<b>Не используйте режим Агента с непроверенными или сомнительными моделями.</b>"
        )
        
        msg.setText(help_text)
        msg.setStyleSheet("""
            QMessageBox { background-color: #0d0f12; min-width: 780px; }
            QLabel { color: #e3e8ef; font-size: 13px; line-height: 1.5; }
            h2 { color: #00ffcc; font-size: 16px; font-weight: bold; margin-bottom: 10px; }
            h3 { color: #00b395; font-size: 14px; font-weight: bold; margin-top: 15px; margin-bottom: 5px; }
            code { background-color: #13171c; color: #ffaa00; padding: 2px 5px; border-radius: 3px; font-family: monospace; font-size: 12px; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; padding: 6px 25px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; border: 1px solid #00b395; }
        """)
        
        layout = msg.layout()
        if layout and isinstance(layout, QGridLayout):
            spacer = QSpacerItem(750, 0, QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Ignored)
            layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())

        msg.exec()

    def _open_cyber_help_window(self, title, html_body, width=820, height=620):
        """📖 Универсальное прокручиваемое окно справки в стиле CyberCore"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton, QHBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(width, height)
        dlg.setStyleSheet("""
            QDialog { background-color: #0d0f12; border: 1px solid #005c4e; }
            QTextBrowser { background-color: #13171c; color: #e3e8ef; border: 1px solid #005c4e; border-radius: 6px; padding: 12px; font-size: 13px; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; padding: 7px 28px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; }
        """)

        layout = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        styled_html = f"""
        <style>
            h2 {{ color: #00ffcc; font-size: 17px; border-bottom: 1px solid #005c4e; padding-bottom: 5px; }}
            h3 {{ color: #00b395; font-size: 14px; margin-top: 14px; margin-bottom: 4px; }}
            code {{ background-color: #0d0f12; color: #ffaa00; padding: 2px 5px; border-radius: 3px; font-family: Consolas, monospace; }}
            li {{ margin-bottom: 4px; }}
        </style>
        {html_body}
        """
        browser.setHtml(styled_html)
        layout.addWidget(browser)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("Понятно")
        btn_ok.clicked.connect(dlg.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        dlg.exec()


    def show_telegram_help_dialog(self):
        """📲 Подробная инструкция по настройке двустороннего моста Telegram"""
        html_text = """
        <h2>📲 Настройка и управление через Telegram-бота (CyberCore Bridge)</h2>
        Модуль <code>telegram_bridge.py</code> позволяет управлять станцией CyberCore удалённо со смартфона.<br>

        <h3>🔑 Шаг 1. Получение токена и вашего Chat ID</h3>
        <ul>
            <li>Откройте в Telegram бота <code>@BotFather</code>, отправьте <code>/newbot</code>, задайте имя и скопируйте <b>HTTP API Token</b>.</li>
            <li>Чтобы узнать свой числовой <b>Chat ID</b>, напишите боту <code>@userinfobot</code> (или напишите своему боту — он пришлёт ваш ID).</li>
        </ul>

        <h3>📄 Шаг 2. Файл конфигурации <code>telegram_config.txt</code></h3>
        Создайте в корневой папке программы текстовый файл <code>telegram_config.txt</code> (UTF-8):<br><br>
        <code>TELEGRAM_BOT_TOKEN=1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxx</code><br>
        <code>TELEGRAM_CHAT_ID=111111111</code><br>
        <code>TELEGRAM_GUEST_IDS=222222222,333333333</code><br>

        <h3>🛡️ Шаг 3. Разделение прав (Администратор и Гость)</h3>
        <ul>
            <li><b>Администратор (<code>TELEGRAM_CHAT_ID</code>):</b> Полный доступ ко всем инструментам ПК (код, терминал, генерация картинок, окна).</li>
            <li><b>Гость (<code>TELEGRAM_GUEST_IDS</code>):</b> Безопасный режим чата — терминал, файлы, Git и управление окнами заблокированы в ядре.</li>
        </ul>

        <h3>🎙️ Шаг 4. Голос, файлы и команды</h3>
        <ul>
            <li><b>Голосовые сообщения:</b> Локальный <b>Whisper (tiny int8)</b> переводит речь в текст и ставит задачу агенту.</li>
            <li><b>Фото и документы:</b> Отправьте фото (<code>.jpg/.png</code>), документ (<code>.pdf/.docx</code>) или таблицу (<code>.xlsx/.csv</code>) — файл сохранится в <code>AI_Generated</code>.</li>
            <li><b>Служебные команды:</b> <code>/start</code> — проверка связи и роли; <code>/status</code> — статус занятости и длина очереди задач.</li>
        </ul>
        """
        self._open_cyber_help_window("Справка: Настройка Telegram-бота", html_text, width=840, height=620)


    def show_about_dialog(self):
        """ℹ️ Информационное окно справки, адаптированное под Portable Edition"""
        from PyQt6.QtWidgets import QMessageBox, QSpacerItem, QGridLayout, QSizePolicy
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Справка — Cyber Core")
        msg.setText(
            "<h3>Cyber Core v1.7 (PORTABLE EDITION)</h3>"
            "<b>Разработчики:</b> ИИ GOOGLE и MIKOLA PINCHUK<br><br>"
            "Автономная портативная нейросетевая рабочая станция для разработки, генерации медиаконтента и автоматизации задач ОС.<br><br>"
            "<b>Основные подсистемы и обновления:</b><br>"
            "• 🤖 <b>Локальный ИИ:</b> Безальтернативная оркестрация через встроенное ядро llama-server с полной поддержкой текстовых и мультимодальных (Vision) моделей GGUF.<br>"
            "• 💻 <b>Умная песочница:</b> Изолированный запуск Python-скриптов с real-time перехватом вывода и модулем автоисправления ошибок Self-Healing.<br>"
            "• 🎨 <b>Генерация графики:</b> Встроенный контур Stable Diffusion для локального синтеза текстур, концепт-артов и инженерных схем.<br>"
            "• 🌐 <b>Многоконтурный RAG:</b> Интеллектуальный поиск по локальной базе знаний ChromaDB и нативный веб-поиск в реальном времени.<br>"
            "• 🎙 <b>Мультимедиа-ядро:</b> Офлайн распознавание речи Whisper, озвучка Kokoro OpenVINO и покадровая раскадровка видео.<br><br>"
            "<i>Все права защищены. Версия 1.6 Portable. Работает 100% конфиденциально без интернета и сторонних серверов.</i>"
        )
        
        msg.setStyleSheet("""
            QMessageBox { background-color: #0d0f12; min-width: 780px; }
            QLabel { color: #00ffcc; font-size: 13px; line-height: 1.5; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; padding: 6px 25px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; border: 1px solid #00b395; }
        """)
        
        layout = msg.layout()
        if layout and isinstance(layout, QGridLayout):
            spacer = QSpacerItem(750, 0, QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Ignored)
            layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())

        msg.exec()

    def show_server_flags_help_dialog(self):
        """🚀 Полное окно документации по флагам запуска llama-server (Intel Arc / Vulkan / VRAM)"""
        from PyQt6.QtWidgets import QMessageBox, QSpacerItem, QGridLayout, QSizePolicy

        msg = QMessageBox(self)
        msg.setWindowTitle("Руководство: Флаги запуска ядра llama-server")

        help_text = (
            "<h2>🚀 Справочник флагов запуска llama-server (Intel Arc 140V / Vulkan)</h2>"
            "Эти параметры прописываются в файле <code>Start Ai CC.bat</code> и управляют распределением "
            "памяти и вычислений между видеокартой Intel Arc, процессором и оперативной памятью.<br><br>"

            "<h3>🧠 1. Основные модели и компьютерное зрение (Vision)</h3>"
            "• <code>-m \"путь/к/модели.gguf\"</code> — путь к файлу основной языковой нейросети (LLM).<br>"
            "• <code>--mmproj \"путь/к/mmproj.gguf\"</code> — подключает проектор зрения для распознавания картинок.<br>"
            "• <code>--no-mmproj-offload</code> — оставляет проектор зрения на процессоре (CPU), освобождая ~1.2 ГБ VRAM "
            "и защищая драйвер Intel Arc от сброса по таймауту (<code>ErrorDeviceLost</code>) на больших фото.<br>"
            "• <code>--image-min-tokens 512</code> — количество визуальных токенов на картинку. Оптимум: <b>512</b>.<br><br>"

            "<h3>⚡ 2. Распределение памяти между GPU (Intel Arc) и CPU</h3>"
            "• <code>-ngl N</code> (<code>--n-gpu-layers</code>) — число слоёв модели на видеокарте (<code>0</code> — только CPU, <code>99</code> — все слои на GPU).<br>"
            "• <code>--fit on</code> — встроенный автоподборщик памяти: сам замеряет свободную VRAM и подбирает число слоёв.<br>"
            "• <code>--fit-ctx N</code> — ограничивает максимальный контекст для автоподборщика по значению ползунка.<br>"
            "• <code>--fit-target 1024</code> — оставляет <b>1024 МБ</b> (1 ГБ) видеопамяти в резерве для Windows и интерфейса CyberCore.<br>"
            "• <code>--no-kv-offload</code> — держит кэш диалога в оперативной памяти (RAM) вместо видеопамяти.<br><br>"

            "<h3>🗜️ 3. Контекст, слоты и сжатие видеопамяти</h3>"
            "• <code>-c N</code> (<code>--ctx-size</code>) — общий размер памяти контекста в токенах.<br>"
            "• <code>-np 1</code> (<code>--parallel</code>) — 1 активный слот запросов вместо 4 (экономит <b>1.5–2 ГБ VRAM</b>).<br>"
            "• <code>--cache-type-k q4_0</code> и <code>--cache-type-v q4_0</code> — сжимает KV-кэш до 4 бит, уменьшая расход VRAM в <b>3–4 раза</b>.<br>"
            "• <code>-fa [on|off|auto]</code> (<code>--flash-attn</code>) — управление ускоренным вниманием Flash Attention.<br><br>"

            "<h3>🌐 4. Потоки CPU, длина ответа и сеть</h3>"
            "• <code>-t N</code> — количество потоков процессора для вспомогательных расчётов и кодирования фото.<br>"
            "• <code>-n N</code> — максимальная длина одного ответа нейросети в токенах.<br>"
            "• <code>--host 127.0.0.1 --port 8080</code> — привязка сервера строго к локальному ПК на порту 8080."
        )

        msg.setText(help_text)
        msg.setStyleSheet("""
            QMessageBox { background-color: #0d0f12; min-width: 800px; }
            QLabel { color: #e3e8ef; font-size: 13px; line-height: 1.5; }
            h2 { color: #00ffcc; font-size: 16px; font-weight: bold; margin-bottom: 10px; }
            h3 { color: #00b395; font-size: 14px; font-weight: bold; margin-top: 14px; margin-bottom: 4px; }
            code { background-color: #13171c; color: #ffaa00; padding: 1px 4px; border-radius: 3px; font-family: monospace; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; padding: 6px 25px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; border: 1px solid #00b395; }
        """)

        layout = msg.layout()
        if layout and isinstance(layout, QGridLayout):
            spacer = QSpacerItem(770, 0, QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Ignored)
            layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())

        msg.exec()

        
    def show_sliders_help_dialog(self):
        """⚙️ Полное окно документации параметров и чекбоксов правой панели"""
        html_text = """
        <h2>⚙️ Настройка параметров и чекбоксов ИИ (CyberCore v1.7)</h2>
        Ползунки и переключатели на правой панели управляют запуском <code>llama-server</code> и генерацией токенов.<br>

        <h3>🌡️ 1. Температура и сэмплирование</h3>
        <ul>
            <li><b>Temp (0.0 – 1.5):</b> Креативность. Для кода и строгого JSON ставьте <b>0.1 – 0.3</b>; для текстов — <b>0.7 – 1.0</b>.</li>
            <li><b>Top_P (0.1 – 1.0) и Top_K (1 – 100):</b> Отсекают слова-мусор. Оптимум: <code>Top_P = 0.9</code>, <code>Top_K = 40</code>.</li>
            <li><b>Mirostat (0, 1, 2):</b> Автостабилизатор текста. При использовании <code>Temp / Top_P</code> держите в <code>0</code>.</li>
        </ul>

        <h3>🚫 2. Штрафы за повторы</h3>
        <ul>
            <li><b>Штраф повторов (1.0 – 1.5):</b> Защита от зацикливания. Оптимум: <code>1.05 – 1.1</code> (для Qwen3 с рассуждениями — <code>1.0</code>).</li>
            <li><b>Штраф частоты и тем (0.0 – 2.0):</b> Разнообразие лексики для статей. Для кода оставляйте <code>0.0</code>.</li>
        </ul>

        <h3>🧠 3. Память контекста, лимит вывода и шаги агента</h3>
        <ul>
            <li><b>Контекст чата (1024 – 262 144):</b> При заполнении на <b>85%</b> срабатывает <b>Swap-подкачка</b> с сохранением плана и списка изученных файлов.</li>
            <li><b>Лимит вывода (1024 – 32 768):</b> Макс. длина одного ответа. Если код оборвался — нажмите <b>«⏭️ Далее»</b>.</li>
            <li><b>Макс шагов Агента (5 – 500):</b> Лимит итераций цикла <b>Auto AI</b> (25–50 для скриптов, 100–250 для проектов).</li>
            <li><b>Потоки CPU (1 – 16) и Слоты -np (1 – 4):</b> Держите <b>Слоты (-np) = 1</b>, чтобы экономить до 2 ГБ VRAM.</li>
        </ul>

        <h3>☑️ 4. Чекбоксы правой панели</h3>
        <ul>
            <li><b>🗜️ Сжатие KV-кэша (Q8_0):</b> Запускает сервер с <code>-ctk q8_0 -ctv q8_0 -fa on</code>, экономя до <b>50% VRAM</b> на длинном контексте.</li>
            <li><b>💾 KV-кэш в RAM (--no-kv-offload):</b> Переносит кэш диалога из видеопамяти в ОЗУ ПК.</li>
            <li><b>🔊 Озвучивать ответы:</b> Озвучка ответов в обычном чате с пропуском программного кода и JSON.</li>
            <li><b>🧠 Режим рассуждений (&lt;think&gt;):</b> Включает глубокий анализ для Qwen3 / Gemma 4. Прошлые <code>&lt;think&gt;</code> автоматически вырезаются из истории.</li>
        </ul>
        """
        self._open_cyber_help_window("Справка: Ползунки и чекбоксы ИИ", html_text, width=840, height=620)


    def create_new_chat_session(self):
        """Создание новой вкладки диалога с ИИ"""
        new_id = self.session_list_widget.count() + 1
        name = f"Чат {new_id}"
        self.chat_sessions[name] = []
        self.chat_html_history[name] = "<i>Система: Начало нового диалога.</i><br><br>"
        
        # Фикс: жестко привязываем создаваемый чат к уже активной в комбобоксе модели
        self.chat_individual_settings[name] = {
            "model": self.model_selector.currentText(),
            "temp": self.slider_temp.value(), 
            "topp": self.slider_topp.value(), 
            "topk": self.slider_topk.value(), 
            "miro": self.slider_miro.value(), 
            "penalty": self.slider_penalty.value(),
            "freq": self.slider_freq_penalty.value(), 
            "pres": self.slider_pres_penalty.value(), 
            "ctx": self.slider_ctx.value(), 
            "predict": self.slider_predict.value(), 
            "threads": self.slider_threads.value()
        }
        
        self.session_list_widget.addItem(name)
        self.save_session_to_db(name)
        self.session_list_widget.setCurrentRow(new_id - 1)

    def import_gguf_model(self):
        """🤖 Портативный импорт GGUF: копирует веса и проекторы в локальную папку Model"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите основной файл модели GGUF", "", "ИИ Модели (*.gguf)")
        if not file_path: 
            return
            
        native_path = os.path.normpath(file_path)
        src_dir = os.path.dirname(native_path)
        model_filename = os.path.basename(native_path)
        
        # Определяем целевую портативную папку для переноса весов
        project_root = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.normpath(os.path.join(project_root, "Model", "LLAMA CCP", "Model"))
        os.makedirs(target_dir, exist_ok=True)
        
        final_dest_path = os.path.join(target_dir, model_filename)

        # Автоматический поиск файла проектора зрения (mmproj) в исходной папке
        mmproj_src_path = None
        mmproj_filename = None
        try:
            for f in os.listdir(src_dir):
                if f.lower().endswith(".gguf") and ("mmproj" in f.lower() or "projector" in f.lower()):
                    mmproj_src_path = os.path.normpath(os.path.join(src_dir, f))
                    mmproj_filename = f
                    break
        except Exception: 
            pass

        self.chat_area.append(f"<i>Система: Копирование модели {model_filename} в портативное хранилище... Пожалуйста, подождите.</i><br>")
        QApplication.processEvents()
        def run_copy_thread():
            import shutil
            try:
                # 1. Копируем основной файл весов нейросети
                shutil.copy2(native_path, final_dest_path)
                
                # 2. Если рядом обнаружен проектор зрения, переносим и его
                if mmproj_src_path and os.path.exists(mmproj_src_path):
                    mmproj_dest_path = os.path.join(target_dir, mmproj_filename)
                    shutil.copy2(mmproj_src_path, mmproj_dest_path)
                    img_msg = f" и проектор мультимодального зрения {mmproj_filename}"
                else:
                    img_msg = ""

                # Сигнализируем в чат об успехе операции из потока через встроенный планировщик
                def on_success():
                    self.chat_area.append(f"<b>🟢 Успех: Модель {model_filename}{img_msg} успешно импортирована в портативное ядро!</b><br>")
                    self.load_installed_models()
                QTimer.singleShot(10, on_success)

            except Exception as ex_copy:
                def on_fail():
                    self.chat_area.append(f"<b style='color:red;'>🔴 Ошибка импорта файлов: {str(ex_copy)}</b><br>")
                QTimer.singleShot(10, on_fail)

        # Запускаем фоновый поток для предотвращения микро-фризов Qt-интерфейса
        import threading
        threading.Thread(target=run_copy_thread, daemon=True).start()
        
        def on_process_finished(exit_code, exit_status):
            if os.path.exists(temp_modelfile_path): 
                try: os.remove(temp_modelfile_path)
                except Exception: pass
            
            if exit_code == 0:
                if has_vision:
                    self.chat_area.append(f"<b>🟢 Успех: Мультимодальная модель {final_model_name} успешно импортирована!</b><br>")
                    if final_model_name not in self.vision_models:
                        self.vision_models.append(final_model_name)
                else:
                    self.chat_area.append(f"<b>🟢 Успех: Текстовая модель {final_model_name} успешно импортирована!</b><br>")
                self.load_installed_models()
            else:
                raw_errors = self.import_process.readAllStandardError().data().decode('utf-8', errors='ignore')
                clean_errors = " ".join(re.sub(r'\[\??[0-9]*[a-zA-Z]|â [	 -ã]', '', raw_errors).split())
                if "gathering model components" in clean_errors.lower():
                    self.chat_area.append(f"<b>🟢 Модель {final_model_name} успешно импортирована!</b><br>")
                    self.load_installed_models()
                else:
                    self.chat_area.append(f"<b style='color:red;'>🔴 Ошибка Ollama:</b> {clean_errors if clean_errors.strip() else 'Процесс прерван'}<br>")
                    
        self.import_process.finished.connect(on_process_finished)
        self.import_process.start(ollama_executable, ["create", final_model_name, "-f", temp_modelfile_path])
        return

    def init_ui(self):
        """Монолитный метод сборки интерфейса с выравниванием панелей и интеграцией SD (Portable)"""
        main_widget = QWidget()
        self.central_widget = main_widget
        self.central_widget.setObjectName("central_widget")
        self.setCentralWidget(main_widget)
        
        hbox_layout = QHBoxLayout(main_widget)
        hbox_layout.setContentsMargins(10, 10, 10, 10)
        hbox_layout.setSpacing(0) 

        left_composite_layout = QHBoxLayout()
        left_composite_layout.setContentsMargins(0, 0, 0, 0)
        left_composite_layout.setSpacing(0)

        # 1. ЛЕВАЯ ПАНЕЛЬ (ИСТОРИЯ ЧАТОВ И ДЕРЕВО ФАЙЛОВ)
        self.session_sidebar = QGroupBox("Панель управления")
        self.session_sidebar.setFixedWidth(230) 
        sidebar_vbox = QVBoxLayout(self.session_sidebar)
        sidebar_vbox.setContentsMargins(8, 12, 8, 8)

        sidebar_vbox.addWidget(QLabel("📂 Сессии диалогов:"))
        self.session_list_widget = QListWidget()
        for k in self.chat_sessions.keys(): 
            self.session_list_widget.addItem(k)
        self.session_list_widget.setCurrentRow(0)
        self.session_list_widget.currentTextChanged.connect(self.switch_chat_session)
        self.session_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list_widget.customContextMenuRequested.connect(self.open_chat_context_menu)
        self.session_list_widget.setFixedHeight(180) 
        sidebar_vbox.addWidget(self.session_list_widget)
        
        self.btn_new_chat = QPushButton("➕ Новый диалог")
        self.btn_new_chat.clicked.connect(self.create_new_chat_session)
        sidebar_vbox.addWidget(self.btn_new_chat)
        
        sidebar_vbox.addSpacing(10)
        sidebar_vbox.addWidget(QLabel("💻 Воркспейс (AI_Generated):"))
        
        self.file_model = QFileSystemModel()
        workspace_path = os.path.join(os.getcwd(), "AI_Generated")
        os.makedirs(workspace_path, exist_ok=True)
        self.file_model.setRootPath(workspace_path)
        
        self.file_tree_view = QTreeView()
        self.file_tree_view.setModel(self.file_model)
        self.file_tree_view.setRootIndex(self.file_model.index(workspace_path))
        self.file_tree_view.setColumnHidden(1, True)
        self.file_tree_view.setColumnHidden(2, True)
        self.file_tree_view.setColumnHidden(3, True)
        self.file_tree_view.setHeaderHidden(True) 
        
        self.file_tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree_view.customContextMenuRequested.connect(self.open_file_tree_context_menu)
        self.file_tree_view.doubleClicked.connect(self.on_file_tree_double_clicked)
        sidebar_vbox.addWidget(self.file_tree_view)
        
        left_composite_layout.addWidget(self.session_sidebar)

        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setFixedWidth(10) 
        self.btn_toggle_sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.btn_toggle_sidebar.clicked.connect(self.toggle_sidebar_visibility)
        left_composite_layout.addWidget(self.btn_toggle_sidebar)
        hbox_layout.addLayout(left_composite_layout)

        # 2. ЦЕНТРАЛЬНАЯ ПАНЕЛЬ
        self.center_container = QGroupBox("Рабочее пространство Cyber Core")
        center_vbox = QVBoxLayout(self.center_container)
        center_vbox.setContentsMargins(8, 12, 8, 8)

        top_bar_layout = QHBoxLayout()
        self.status_label = QLabel("Проверка сервера...")
        top_bar_layout.addWidget(self.status_label)
        top_bar_layout.addStretch()

        top_bar_layout.addWidget(QLabel("🧠 Модель ИИ:"))
        self.model_selector = QComboBox() 
        self.model_selector.setMinimumWidth(280)
        self.model_selector.currentTextChanged.connect(self.on_model_changed)
        top_bar_layout.addWidget(self.model_selector)
        center_vbox.addLayout(top_bar_layout)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.splitter.addWidget(self.chat_area)
        

        # ПРЕДПРОСМОТР МЕДИАФАЙЛОВ ПЕРЕД ОТПРАВКОЙ
        self.preview_widget = QWidget()
        self.preview_layout = QHBoxLayout(self.preview_widget)
        self.preview_layout.setContentsMargins(5, 2, 5, 2)
        self.lbl_preview_icon = QLabel()
        self.lbl_preview_icon.setFixedSize(40, 40)
        self.lbl_preview_icon.setScaledContents(True)
        self.lbl_preview_text = QLabel("Файл прикреплен")
        self.lbl_preview_text.setStyleSheet("color: #00ffcc; font-size: 11px;")
        self.btn_clear_media = QPushButton("❌")
        self.btn_clear_media.setFixedSize(20, 20)
        self.btn_clear_media.setStyleSheet("background: transparent; border: none; color: red;")
        self.btn_clear_media.clicked.connect(self.clear_attached_media)
        self.preview_layout.addWidget(self.lbl_preview_icon)
        self.preview_layout.addWidget(self.lbl_preview_text)
        self.preview_layout.addWidget(self.btn_clear_media)
        self.preview_layout.addStretch()
        self.preview_widget.hide()

        # Вкладки bottom_tabs
        self.bottom_tabs = QTabWidget()
        self.prompt_tab_widget = QWidget()
        prompt_tab_layout = QVBoxLayout(self.prompt_tab_widget)
        prompt_tab_layout.setContentsMargins(0, 4, 0, 0)
        prompt_tab_layout.addWidget(self.preview_widget)
        self.input_field = SmartLineEdit()
        self.input_field.enter_pressed.connect(self.send_message)
        prompt_tab_layout.addWidget(self.input_field)
        self.bottom_tabs.addTab(self.prompt_tab_widget, "💬 Запрос ИИ")

        self.code_tab_widget = QWidget()
        code_tab_layout = QVBoxLayout(self.code_tab_widget)
        code_tab_layout.setContentsMargins(0, 4, 0, 0)
        self.code_editor_field = QTextEdit()
        self.code_editor_field.setPlaceholderText("# Сгенерированный код появится здесь автоматически...")
        self.code_editor_field.setFixedHeight(150)
        self.code_editor_field.setFontFamily("Consolas")
        code_tab_layout.addWidget(self.code_editor_field)
        self.bottom_tabs.addTab(self.code_tab_widget, "💻 Редактор кода")
        # =====================================================================
        # === ИНТЕГРАЦИЯ РАСШИРЕННОГО БЛОКА УПРАВЛЕНИЯ STABLE DIFFUSION INTEL ===
        # =====================================================================
        self.diffusion_tab_widget = QWidget()
        diff_layout = QVBoxLayout(self.diffusion_tab_widget)
        diff_layout.setContentsMargins(10, 5, 10, 5)
        
        # Ряд 1: Текстовое поле для Негативного промпта
        neg_layout = QHBoxLayout()
        neg_layout.addWidget(QLabel("🚫 Негативный запрос:"))
        self.negative_prompt_field = QLineEdit()
        self.negative_prompt_field.setPlaceholderText("blur, bad anatomy, ugly, low quality, deformed, extra fingers, text, watermark")
        neg_layout.addWidget(self.negative_prompt_field)
        diff_layout.addLayout(neg_layout)
        
        form_grid = QHBoxLayout()
        
        # 1. Выбор модели
        # --- ЖЕЛЕЗНЫЙ ДИНАМИЧЕСКИЙ СКАНИРОВЩИК SAFETENSORS И CKPT ВЕСОВ ДЛЯ PYTORCH ---
        vbox_sd_model_layout = QVBoxLayout()
        vbox_sd_model_layout.addWidget(QLabel("🎨 Модель Диффузии (.safetensors / .ckpt):"))
        
        self.safetensors_selector = QComboBox()
        self.safetensors_selector.setObjectName("safetensors_selector")
        
        # Сканируем физическую папку на наличие файлов весов .safetensors и .ckpt
        models_dir = r"D:\AI_CLI\NEW AI AGENT\AI_Expert_Models\Image_Gen"
        detected_models = []
        
        if os.path.exists(models_dir):
            for item in os.listdir(models_dir):
                item_path = os.path.join(models_dir, item)
                # РАСШИРЕННЫЙ ФИЛЬТР: собираем и новые .safetensors, и старые .ckpt веса!
                if os.path.isfile(item_path) and (item.lower().endswith(".safetensors") or item.lower().endswith(".ckpt")):
                    detected_models.append(item)
                    
        # Фоллбэк-заглушка на случай, если папка пуста
        if not detected_models:
            detected_models = ["photon_v1.safetensors", "v1-5-pruned-emaonly.safetensors"]
            
        self.safetensors_selector.addItems(detected_models)
        
        # Автоматическое восстановление последней выбранной модели из SQLite БД
        try:
            self.db_cursor.execute("SELECT val FROM ui_settings WHERE key = 'selected_sd_model_file_name'")
            saved_sd_row = self.db_cursor.fetchone()
            if saved_sd_row:
                saved_sd_file = str(saved_sd_row[0]).strip()
                found_sd_index = self.safetensors_selector.findText(saved_sd_file)
                if found_sd_index != -1:
                    self.safetensors_selector.setCurrentIndex(found_sd_index)
        except Exception:
            pass
            
        # Запоминаем выбор конкретного файла весов в базу данных при каждом клике
        self.safetensors_selector.currentTextChanged.connect(
            lambda text: self.save_ui_setting("selected_sd_model_file_name", text)
        )
        
        vbox_sd_model_layout.addWidget(self.safetensors_selector)
        form_grid.addLayout(vbox_sd_model_layout)
        # ---------------------------------------------------------------------------------
      
        
        # 2. Выбор разрешения
        vbox_r = QVBoxLayout()
        vbox_r.addWidget(QLabel("📐 Размер:"))
        self.size_selector = QComboBox()
        self.size_selector.addItems(["512x512", "768x768", "512x768", "768x512"])
        vbox_r.addWidget(self.size_selector)
        form_grid.addLayout(vbox_r)
        
        # 3. Выбор шагов
        vbox_s = QVBoxLayout()
        vbox_s.addWidget(QLabel("⏳ Шаги (Steps):"))
        self.steps_selector = QComboBox()
        self.steps_selector.addItems(["20", "30", "50"])
        vbox_s.addWidget(self.steps_selector)
        form_grid.addLayout(vbox_s)
        
        # 4. Ввод Креативности (CFG Scale)
        vbox_c = QVBoxLayout()
        vbox_c.addWidget(QLabel("🎯 Креативность (CFG):"))
        self.cfg_selector = QComboBox()
        self.cfg_selector.addItems(["7.5", "5.0", "1.0", "10.0"])
        vbox_c.addWidget(self.cfg_selector)
        form_grid.addLayout(vbox_c)
        
        # 5. Ввод ручного Seed
        vbox_sd = QVBoxLayout()
        vbox_sd.addWidget(QLabel("🎲 Зерно (Seed):"))
        self.seed_field = QLineEdit("-1")
        self.seed_field.setPlaceholderText("-1 для рандома")
        self.seed_field.setFixedWidth(80)
        vbox_sd.addWidget(self.seed_field)
        form_grid.addLayout(vbox_sd)
        
        # 6. Управляющая кнопка генерации на Intel Arc
        vbox_b = QVBoxLayout()
        vbox_b.addWidget(QLabel("🚀 Ускорение Xe2:"))
        self.btn_generate_local_image = QPushButton("🎨 Генерировать на Intel Arc")
        self.btn_generate_local_image.setStyleSheet("background-color: #005c4e; color: #00ffcc; font-weight: bold;")
        self.btn_generate_local_image.clicked.connect(self.trigger_local_image_generation)
        vbox_b.addWidget(self.btn_generate_local_image)
        form_grid.addLayout(vbox_b)
        
        diff_layout.addLayout(form_grid)
        diff_layout.addStretch()
        
        self.bottom_tabs.addTab(self.diffusion_tab_widget, "🎨 Диффузия SD")
        # =====================================================================

        self.input_container = QWidget()
        input_container_layout = QVBoxLayout(self.input_container)
        input_container_layout.setContentsMargins(0, 0, 0, 0)
        input_container_layout.addWidget(self.bottom_tabs)
        features_layout = QHBoxLayout()
        
        self.attach_btn = QPushButton("👁 Cyber Vision")
        self.attach_btn.setMinimumWidth(110)  
        self.attach_btn.setToolTip("Интеллектуальный ИИ-анализ графики + Офлайн OCR-распознавание EasyOCR")
        self.attach_btn.clicked.connect(self.attach_media_file)
        features_layout.addWidget(self.attach_btn)

        self.btn_attach_file = QPushButton("📄 Файл")
        self.btn_attach_file.clicked.connect(self.attach_local_file)
        features_layout.addWidget(self.btn_attach_file)

        self.btn_save_py_file = QPushButton("💾 Сохранить")
        self.btn_save_py_file.clicked.connect(self.save_code_from_editor)
        features_layout.addWidget(self.btn_save_py_file)

        self.btn_continue_gen = QPushButton("⏭️ Далее")
        self.btn_continue_gen.clicked.connect(self.continue_bot_generation)
        features_layout.addWidget(self.btn_continue_gen)

        self.btn_view_agent_log = QPushButton("📜 Лог Агента")
        self.btn_view_agent_log.clicked.connect(self.load_agent_swap_log_to_editor)
        features_layout.addWidget(self.btn_view_agent_log)
        
        self.btn_run_sandbox = QPushButton("🚀 Старт")
        self.btn_run_sandbox.clicked.connect(self.run_code_in_sandbox)
        features_layout.addWidget(self.btn_run_sandbox)
        
        self.btn_copy_code = QPushButton("📋 Буфер")
        self.btn_copy_code.clicked.connect(self.copy_last_code_block)
        features_layout.addWidget(self.btn_copy_code)

        self.btn_auto_ai = QPushButton("🤖 Auto AI")
        self.btn_auto_ai.clicked.connect(self.start_autonomous_agent_loop)
        features_layout.addWidget(self.btn_auto_ai)

        self.send_btn = QPushButton("⚡ Отправить")
        self.send_btn.clicked.connect(self.send_message)
        features_layout.addWidget(self.send_btn)
        
        input_container_layout.addLayout(features_layout)
        self.splitter.addWidget(self.input_container)
        
        self.splitter.setSizes([500, 220]) 
        
        center_vbox.addWidget(self.splitter)
        hbox_layout.addWidget(self.center_container, stretch=3)

        hbox_layout.addSpacing(10)
        self.init_right_sidebar(hbox_layout)


    def load_agent_swap_log_to_editor(self):
        """📜 Считывает дисковый файл подкачки памяти агента и выводит во вкладку-редактор"""
        log_file_path = os.path.join(os.getcwd(), "AI_Generated", "agent_context_swap.log")
        if not os.path.exists(log_file_path):
            self.chat_area.append("<br><b style='color:orange;'>⚠️ Система: Дисковый файл подкачки памяти еще не создавался.</b><br>")
            return
        try:
            with open(log_file_path, "r", encoding="utf-8", errors="ignore") as lf:
                log_content = lf.read()
            if log_content.strip():
                self.code_editor_field.setPlainText(log_content.strip())
                self.bottom_tabs.setCurrentIndex(1)
                self.chat_area.append("<br><i style='color:#00ffcc;'>📜 [Система]: Лог дискового кэша памяти агента загружен в окно редактора!</i><br>")
            else:
                self.chat_area.append("<br><b style='color:orange;'>Система: Файл лога подкачки памяти пуст.</b><br>")
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>🔴 Ошибка чтения лог-файла памяти: {str(e)}</b><br>")

    def attach_media_file(self):
        """📂 Метод кнопки CyberVision: загрузка файла, ИИ-аналитика и мгновенный запуск EasyOCR"""
        result = QFileDialog.getOpenFileName(self, "Выберите медиафайл для CyberVision", "", "Медиа файлы (*.png *.jpg *.jpeg *.webp *.mp4 *.avi *.mkv)")
        
        # КРИТИЧЕСКИЙ ФИКС: Корректно извлекаем чистую строку пути из кортежа PyQt
        if not result or not result[0]: 
            return
        file_path = os.path.normpath(result[0].strip())
            
        if not os.path.exists(file_path): return
        
        self.attached_media_path = file_path
        ext = os.path.splitext(file_path)[1].lower().strip()
        
        workspace_path = os.path.join(os.getcwd(), "AI_Generated")
        os.makedirs(workspace_path, exist_ok=True)

        if ext in ['.png', '.jpg', '.jpeg', '.webp']:
            self.lbl_preview_icon.setPixmap(QPixmap(file_path))
            self.lbl_preview_text.setText(f"Сканирование: {os.path.basename(file_path)}")
            self.preview_widget.show()
            
            # --- ЗАПУСК ЛОКАЛЬНОГО ИЗОЛИРОВАННОГО EasyOCR ПОТОКА (ПОЛНЫЙ ОФЛАЙН) ---
            self.chat_area.append(f"<br><i style='color:#00ffcc;'>⏳ [EasyOCR]: Запуск быстрого распознавания текста для {os.path.basename(file_path)}...</i>")
            
            from media_processor import OCRWorker
            self.ocr_thread = OCRWorker([file_path], workspace_path)

            
            def on_ocr_single_done(filename, report, content):
                self.chat_area.append(f"<i style='color:#00ffcc;'>  [CyberVision OCR]: {report}</i>")
                if content.strip():
                    self.chat_area.append(f"<pre style='background:#13171c; color:#a8ffb2; padding:5px; border-left: 3px solid #00ffcc;'>{content[:300]}...</pre>")
            
            self.ocr_thread.file_processed.connect(on_ocr_single_done)
            self.ocr_thread.start()
            
            # Автоматически подготавливаем ИИ промпт в поле ввода для отправки
            self.input_field.setPlainText(f"Проанализируй картинку '{os.path.basename(file_path)}' и подробно опиши, что на ней изображено.")
            
        else:
            self.lbl_preview_icon.setText("🎬")
            self.lbl_preview_text.setText(f"Видеофайл: {os.path.basename(file_path)}")
            self.preview_widget.show()
            self.input_field.setPlainText(f"Проанализируй раскадровку этого видеофайла.")

    def clear_attached_media(self):
        """❌ Сброс прикрепленного файла"""
        self.attached_media_path = None
        self.lbl_preview_icon.clear()
        self.preview_widget.hide()

    def init_right_sidebar(self, hbox_layout):
        """Панель управления сессией со всеми ползунками конфигурации ИИ"""
        sidebar_group = QGroupBox("Управление сессией")
        sidebar_group.setFixedWidth(280)
        sidebar_layout = QVBoxLayout(sidebar_group)
        sidebar_layout.setContentsMargins(8, 12, 8, 8)
        
        self.btn_voice = QPushButton("🎙️ Голосовой ввод")
        self.btn_voice.setCheckable(True)
        self.btn_voice.clicked.connect(self.toggle_voice_recording)
        sidebar_layout.addWidget(self.btn_voice)
        
        self.btn_clear_chat = QPushButton("🗑️ Очистить память")
        self.btn_clear_chat.clicked.connect(self.clear_chat_context)
        sidebar_layout.addWidget(self.btn_clear_chat)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_temp_val = QLabel("0.7")
        self.slider_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_temp.setRange(0, 15); self.slider_temp.setValue(7)
        self.slider_temp.valueChanged.connect(lambda v: (self.lbl_temp_val.setText(str(v/10.0)), self.save_ui_setting("temp", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Temp:"), self.lbl_temp_val); form_layout.addRow(self.slider_temp)
        
        self.lbl_topp_val = QLabel("0.9")
        self.slider_topp = QSlider(Qt.Orientation.Horizontal)
        self.slider_topp.setRange(1, 10); self.slider_topp.setValue(9)
        self.slider_topp.valueChanged.connect(lambda v: (self.lbl_topp_val.setText(str(v/10.0)), self.save_ui_setting("topp", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Top_P:"), self.lbl_topp_val); form_layout.addRow(self.slider_topp)

        self.lbl_topk_val = QLabel("40")
        self.slider_topk = QSlider(Qt.Orientation.Horizontal)
        self.slider_topk.setRange(1, 100); self.slider_topk.setValue(40)
        self.slider_topk.valueChanged.connect(lambda v: (self.lbl_topk_val.setText(str(v)), self.save_ui_setting("topk", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Top_K:"), self.lbl_topk_val); form_layout.addRow(self.slider_topk)

        self.lbl_miro_val = QLabel("0")
        self.slider_miro = QSlider(Qt.Orientation.Horizontal)
        self.slider_miro.setRange(0, 2); self.slider_miro.setValue(0)
        self.slider_miro.valueChanged.connect(lambda v: (self.lbl_miro_val.setText(str(v)), self.save_ui_setting("miro", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Mirostat:"), self.lbl_miro_val); form_layout.addRow(self.slider_miro)

        self.lbl_penalty_val = QLabel("1.1")
        self.slider_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_penalty.setRange(10, 15); self.slider_penalty.setValue(11)
        self.slider_penalty.valueChanged.connect(lambda v: (self.lbl_penalty_val.setText(str(v/10.0)), self.save_ui_setting("penalty", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Штраф повторов:"), self.lbl_penalty_val); form_layout.addRow(self.slider_penalty)

        self.lbl_freq_val = QLabel("0.0")
        self.slider_freq_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_freq_penalty.setRange(0, 20); self.slider_freq_penalty.setValue(0)
        self.slider_freq_penalty.valueChanged.connect(lambda v: (self.lbl_freq_val.setText(str(v/10.0)), self.save_ui_setting("freq", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Штраф частоты:"), self.lbl_freq_val); form_layout.addRow(self.slider_freq_penalty)

        self.lbl_pres_val = QLabel("0.0")
        self.slider_pres_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_pres_penalty.setRange(0, 20); self.slider_pres_penalty.setValue(0)
        self.slider_pres_penalty.valueChanged.connect(lambda v: (self.lbl_pres_val.setText(str(v/10.0)), self.save_ui_setting("pres", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Штраф тем:"), self.lbl_pres_val); form_layout.addRow(self.slider_pres_penalty)

        self.lbl_ctx_val = QLabel("65536")
        self.slider_ctx = QSlider(Qt.Orientation.Horizontal)
        self.slider_ctx.setRange(1, 10); self.slider_ctx.setValue(7)
        self.slider_ctx.valueChanged.connect(lambda v: (self.lbl_ctx_val.setText(str(self.ctx_steps.get(v, 65536))), self.save_ui_setting("ctx", v), self.save_session_to_db(self.current_session), self.update_token_counter()))
        form_layout.addRow(QLabel("Контекст чата:"), self.lbl_ctx_val); form_layout.addRow(self.slider_ctx)

        self.lbl_predict_val = QLabel("4096")
        self.slider_predict = QSlider(Qt.Orientation.Horizontal)
        self.slider_predict.setRange(1, 6); self.slider_predict.setValue(3)
        self.slider_predict.valueChanged.connect(lambda v: (self.lbl_predict_val.setText(str(self.predict_steps.get(v, 4096))), self.save_ui_setting("predict", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Лимит вывода:"), self.lbl_predict_val); form_layout.addRow(self.slider_predict)

        self.lbl_max_steps_val = QLabel("100")
        self.slider_max_steps = QSlider(Qt.Orientation.Horizontal)
        self.slider_max_steps.setRange(5, 500); self.slider_max_steps.setValue(100)
        self.slider_max_steps.valueChanged.connect(lambda v: (self.lbl_max_steps_val.setText(str(v)), self.save_ui_setting("max_steps", v)))
        form_layout.addRow(QLabel("Макс шагов Агента:"), self.lbl_max_steps_val); form_layout.addRow(self.slider_max_steps)

        self.lbl_threads_val = QLabel("4")
        self.slider_threads = QSlider(Qt.Orientation.Horizontal)
        self.slider_threads.setRange(1, 16); self.slider_threads.setValue(4)
        self.slider_threads.valueChanged.connect(lambda v: (self.lbl_threads_val.setText(str(v)), self.save_ui_setting("threads", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Потоки CPU:"), self.lbl_threads_val); form_layout.addRow(self.slider_threads)

        self.lbl_np_val = QLabel("1")
        self.slider_np = QSlider(Qt.Orientation.Horizontal)
        self.slider_np.setRange(1, 4); self.slider_np.setValue(1)
        self.slider_np.valueChanged.connect(lambda v: (self.lbl_np_val.setText(str(v)), self.save_ui_setting("np_slots", v)))
        form_layout.addRow(QLabel("Слоты (-np):"), self.lbl_np_val); form_layout.addRow(self.slider_np)

        # === ВСЕ ЧЕКБОКСЫ ПО ПОРЯДКУ ПОСЛЕ ПОЛЗУНКОВ ===
        self.cb_kv_compress = QCheckBox("🗜️ Сжатие KV-кэша (Q8_0)")
        self.cb_kv_compress.setToolTip("Сжимает кэш контекста до 8 бит (-ctk q8_0 -ctv q8_0), экономя до 50% VRAM.")
        self.cb_kv_compress.stateChanged.connect(lambda v: self.save_ui_setting("kv_compress", 1 if v else 0))
        form_layout.addRow(self.cb_kv_compress)

        self.cb_no_kv_offload = QCheckBox("💾 KV-кэш в RAM (--no-kv-offload)")
        self.cb_no_kv_offload.stateChanged.connect(lambda v: self.save_ui_setting("no_kv_offload", 1 if v else 0))
        form_layout.addRow(self.cb_no_kv_offload)

        self.cb_speech_on = QCheckBox("🔊 Озвучивать ответы")
        self.cb_speech_on.stateChanged.connect(lambda v: self.save_ui_setting("speech_on", 1 if v else 0))
        form_layout.addRow(self.cb_speech_on)

        self.cb_thinking = QCheckBox("🧠 Режим рассуждений (<think>)")
        self.cb_thinking.setToolTip("Включает глубокое обдумывание для Qwen3 / Gemma 4. Увеличивает время ответа.")
        self.cb_thinking.stateChanged.connect(lambda v: self.save_ui_setting("enable_thinking", 1 if v else 0))
        form_layout.addRow(self.cb_thinking)

        sidebar_layout.addWidget(form_widget)

        self.lbl_token_usage = QLabel("Занято: 0 / 8192 токенов (0%)")
        self.lbl_generation_speed = QLabel("Скорость ИИ: 0.0 tok/sec")
        sidebar_layout.addWidget(self.lbl_token_usage)
        sidebar_layout.addWidget(self.lbl_generation_speed)

        self.lbl_sys_cpu = QLabel("Загрузка CPU: 0.0%")
        self.lbl_sys_ram = QLabel("Использование RAM: 0.0%")
        self.lbl_sys_gpu = QLabel("Загрузка GPU (Intel Arc): 0.0%")

        sidebar_layout.addWidget(self.lbl_sys_cpu)
        sidebar_layout.addWidget(self.lbl_sys_ram)
        sidebar_layout.addWidget(self.lbl_sys_gpu)


        sidebar_layout.addStretch()
        hbox_layout.addWidget(sidebar_group)
    def switch_chat_session(self, session_name):
        """🔄 Переключение между чатами с восстановлением индивидуальной модели и настроек"""
        if not session_name or session_name not in self.chat_sessions: 
            return
            
        self.current_session = session_name
        self.chat_area.setHtml(self.chat_html_history.get(session_name, ""))
        self.lbl_generation_speed.setText("Скорость ИИ: 0.0 tok/sec")
        
        # КРИТИЧЕСКИЙ ФИКС: Восстанавливаем сохраненную историю в активный буфер payload
        self.chat_history = self.chat_sessions.get(session_name, [])

        # Вытягиваем индивидуальные настройки этого чата
        chat_settings = self.chat_individual_settings.get(session_name, {})
        saved_model = chat_settings.get("model", "")

        if saved_model:
            # Блокируем сигналы, чтобы автомат не перезаписал модель в БД во время переключения
            self.model_selector.blockSignals(True)
            found_index = self.model_selector.findText(str(saved_model).strip())
            if found_index != -1:
                self.model_selector.setCurrentIndex(found_index)
                self.current_model = str(saved_model).strip()
            self.model_selector.blockSignals(False)
            
        # Обновляем ползунки (температура, контекст и т.д.) под этот конкретный чат
        self.load_saved_settings() 
        # Пересчитываем токенный вес новой активной сессии
        self.update_token_counter()
    def update_generation_speed(self, tok_sec, total_tokens):
        """📈 Отображение скорости генерации и номера текущего шага (токена) ИИ"""
        try:
            # 1. Обновляем текстовый индикатор скорости на правой панели
            self.lbl_generation_speed.setText(f"Скорость ИИ: {tok_sec:.1f} tok/sec")
            
            # 2. ВОЗВРАЩАЕМ СЧЕТЧИК ШАГОВ: Выводим номер текущего токена (шага) в верхний статус-бар
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(f"⚡ Генерация: Шаг {total_tokens} (вывод токенов)...")
                
        except Exception as e:
            print(f"Варнинг счетчика скорости и шагов: {e}")
            
    def send_message(self):
        """💬 Обработчик отправки сообщений пользователем (Текст + Файлы + Защита от зависаний)"""
        # 1. Контур экстренной остановки: если ИИ генерирует текст — кнопка работает как Стоп-Кран
        if self.worker and self.worker.isRunning():
            self.worker.stop_generation()
            return
            
        # 2. Контур остановки агента: если запущен цикл Auto AI — кнопка останавливает его
        if hasattr(self, 'agent_thread') and self.agent_thread.isRunning():
            self.stop_autonomous_agent_loop()
            return

        # 3. Валидация ввода
        query = self.input_field.toPlainText().strip()
        if not query: 
            return

        # 4. Слияние текстового контекста загруженных документов (.txt, .py, .pdf, .docx)
        if hasattr(self, 'attached_file_context') and self.attached_file_context.strip():
            query = f"[Данные из прикрепленного файла]:\n{self.attached_file_context}\n\nЗадача пользователя: {query}"
            self.attached_file_context = ""
            # Сбрасываем внешний вид кнопки прикрепления в исходное состояние
            self.btn_attach_file.setText("📄 Файл")
            self.btn_attach_file.setStyleSheet("")

        # 5. Визуализация запроса пользователя в окне чата и очистка поля ввода
        self.chat_area.append(f"<b>Вы:</b> {query}")
        self.input_field.clear()

        # 6. Безальтернативный вызов локального портативного бэкенда ядра (llama-server)
        self.execute_portable_backend_call(query)

    def on_model_changed(self, model_name):
        """🤖 Вызывается при ручной смене модели пользователем в выпадающем списке"""
        # 1. Жесткий фильтр ложных вызовов Qt при перерисовках интерфейса
        if not model_name or not str(model_name).strip() or str(model_name).strip() in ["", "-1", "None"]: 
            return
            
        from portable_backend import PortableLlamaEngine

        # 2. Чистая универсальная нормализация путей
        clean_m = str(model_name).strip().replace("\\", "/")
        clean_m = clean_m.replace("Model/LLAMA CCP/Model/", "").replace("Model/LLAMA CCP/", "")
        if clean_m.startswith("Model/"):
            clean_m = clean_m[6:]
        
        # Защита от циклического перезапуска одной и той же модели
        if hasattr(self, 'current_model') and self.current_model == clean_m:
            if PortableLlamaEngine(clean_m)._check_server_alive():
                self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
                self.model_selector.setEnabled(True)
                self.model_selector.blockSignals(False)
                return

        # ЗАМОРАЖИВАЕМ КЛИКИ НА ВРЕМЯ КОРРЕКТНОЙ СМЕНЫ ЯДРА В ОС
        self.model_selector.setEnabled(False)
        self.model_selector.blockSignals(True)
        self.status_label.setText("⏳ Выгрузка памяти...")

        # 3. Принудительно тушим текущий поток ИИ-ответа, если он занят
        if self.worker and self.worker.isRunning():
            self.worker.stop_generation()
            self.worker.wait()

        self.current_model = clean_m
        self.chat_area.append(f"<br><b style='color:#ffaa00;'>🔄 [Горячая замена]: Переключаюсь на {os.path.basename(self.current_model)}...</b>")
        QApplication.processEvents()

        # 4. ЖЕСТКОЕ ЖЕЛЕЗНОЕ УБИЙСТВО ПРОЦЕССА НА УРОВНЕ WINDOWS CMD
        try:
            import subprocess
            if os.name == 'nt':
                subprocess.run("taskkill /f /im llama-server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("taskkill /f /im llama.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run("pkill -9 llama-server", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
            
        time.sleep(1.0) # Пауза для полной очистки ОЗУ/VRAM операционной системой

        # 5. Фоновый асинхронный запуск
        def async_model_boot():
            try:
                ai_options = self.get_ai_options()
                engine = PortableLlamaEngine(self.current_model, ai_options)
                
                # Запускаем батник
                success = engine.start_server_if_needed()
                
                # Мягкое уведомление об успехе (вызовется, только если поток доживет)
                if success:
                    def on_success_msg():
                        self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
                        self.chat_area.append(f"<br><b style='color:#00ffcc;'>✅ [CyberCore]: Новое локальное ядро успешно развернуто!</b><br>")
                        if hasattr(self, 'current_session') and self.current_session in self.chat_individual_settings:
                            self.chat_individual_settings[self.current_session]["model"] = self.current_model
                        self.update_token_counter()
                        self.save_ui_setting("selected_model_name", self.current_model)
                        self.save_session_to_db(self.current_session)
                    QTimer.singleShot(10, on_success_msg)
            except Exception as e:
                print(f"Внутреннее исключение фонового бута: {e}")

        # 6. ГАРАНТИРОВАННЫЙ ТАЙМЕР РАЗБЛОКИРОВКИ (ВНЕШНИЙ КОНТУР ЗАЩИТЫ)
        # Этот таймер выполнится ЖЕЛЕЗНО через 3 секунды, даже если метод выше зависнет в бесконечном цикле!
        def force_unlock_interface():
            self.model_selector.setEnabled(True)
            self.model_selector.blockSignals(False)
            # Если к этому моменту сокет ожил — ставим зеленый статус
            if PortableLlamaEngine(self.current_model)._check_server_alive():
                self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
            else:
                self.status_label.setText("⚪ Движок: Инициализация в CMD")
            QApplication.processEvents()

        # Запускаем поток загрузки GGUF
        import threading
        threading.Thread(target=async_model_boot, daemon=True).start()

        # Запускаем безусловный разблокировщик интерфейса через 3000 мс (3 секунды)
        QTimer.singleShot(3000, force_unlock_interface)

    def execute_portable_backend_call(self, user_text):
        """Построение payload, запуск отладчика данных и вызов потока PortableLlamaEngine"""
        
        # 1. Извлечение и жесткая очистка имени активной модели
        if hasattr(self, 'current_model') and self.current_model:
            if isinstance(self.current_model, tuple):
                self.current_model = self.current_model[0] if len(self.current_model) > 0 else ""
                
            clean_m = str(self.current_model).replace("('", "").replace("',)", "").strip().replace("\\", "/")
            clean_m = clean_m.replace("Model/LLAMA CCP/Model/", "").replace("Model/LLAMA CCP/", "")
            if clean_m.startswith("Model/"):
                clean_m = clean_m[6:]
            self.current_model = clean_m

        if hasattr(self, 'current_session') and self.current_session:
            if isinstance(self.current_session, tuple):
                self.current_session = self.current_session[0] if len(self.current_session) > 0 else "Чат 1"
            self.current_session = str(self.current_session).replace("('", "").replace("',)", "").strip()

        agent_injection = (
            "\n[КРИТИЧЕСКИЙ РЕЖИМ АГЕНТА]: Ты ОБЯЗАН управлять ПК пользователя с помощью макросов.\n"
            "Доступные теги: [RUN_CMD: команда], [OPEN_URL: ссылка], [MAKE_DIR: ...], [CREATE_FILE: путь|текст].\n"
        )

        if not hasattr(self, 'chat_history') or self.chat_history is None:
            active_session = getattr(self, 'current_session', None)
            self.chat_history = self.chat_sessions.get(active_session, []) if active_session else []

        # Нативно крепим контекст файла как отдельное независимое сообщение в историю
        if hasattr(self, 'attached_file_context') and self.attached_file_context.strip():
            self.chat_history.append({
                "role": "user", 
                "content": f"[СИСТЕМНЫЙ ДОКУМЕНТ]: Контекст загруженного тобой файла:\n{self.attached_file_context.strip()}"
            })
            self.attached_file_context = ""
            self.btn_attach_file.setText("📄 Файл")
            self.btn_attach_file.setStyleSheet("")

        full_message_text = user_text
        if hasattr(self, 'agent_active_action') and self.agent_active_action.isChecked():
            full_message_text += agent_injection

        # 2. ИЗОЛИРОВАННАЯ ПОДГОТОВКА МЕДИА ЧЕРЕЗ РАБОЧИЙ КЛИЕНТ PROCESSOR
        images_to_send = []
        if hasattr(self, 'attached_media_path') and self.attached_media_path:
            images_to_send, media_directive = MediaProcessor.prepare_vision_context(self.attached_media_path)
            if images_to_send:
                full_message_text = media_directive + full_message_text
            self.clear_attached_media()

        # 3. ФОРМИРОВАНИЕ СТРУКТУРЫ: Если картинки есть — мы крепим их к структуре запроса
        if images_to_send:
            message_struct = {"role": "user", "content": full_message_text, "images": images_to_send}
        else:
            message_struct = {"role": "user", "content": full_message_text}
            
        if not hasattr(self, 'chat_history') or self.chat_history is None:
            active_session = getattr(self, 'current_session', None)
            self.chat_history = self.chat_sessions.get(active_session, []) if active_session else []

        self.chat_history.append(message_struct)
        ollama_options = self.get_ai_options()

        # === ТОТАЛЬНЫЙ ОТЛАДЧИК СЫРЫХ ДАННЫХ ИИ ===
        if getattr(self, 'raw_debug_on', False):
            try:
                debug_history = copy.deepcopy(self.chat_history)
                if debug_history and isinstance(debug_history, list) and "images" in debug_history[-1]:
                    debug_history[-1]["images"] = f"[{len(images_to_send)} Файлов закодировано в Base64]"
                
                debug_send_msg = (
                    f"<div style='color:#ffaa00; border: 1px dashed #ffaa00; padding: 6px; margin: 5px 0; background:#0d0f12;'>\n"
                    f"<b>[ОТЛАДЧИК ПАКЕТОВ ИИ] -> ОТПРАВКА В LLAMA-SERVER:</b><br>\n"
                    f"Активная модель GGUF: {self.current_model}<br>\n"
                    f"Параметры сессии (Options): {json.dumps(ollama_options)}<br>\n"
                    f"Полный сырой JSON истории (Промпт):<br>\n"
                    f"<pre style='color:#ffcc00; font-family:monospace; font-size:11px;'>{json.dumps(debug_history, ensure_ascii=False, indent=2)}</pre></div>"
                )
                self.chat_area.append(debug_send_msg)
            except Exception as e_debug:
                print(f"Ошибка вывода лога отладчика: {e_debug}")

        # 4. ИНИЦИАЛИЗАЦИЯ ТЕКСТОВЫХ БУФЕРОВ И УПРАВЛЕНИЯ СТРИМИНГОМ
        self.chat_area.append("<b style='color:#ff0055;'>Бот:</b> ")
        self.bot_response_buffer = ""
        self._speech_buffer = ""

        self.send_btn.setText("🛑 Стоп ИИ")
        self.send_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")

        # Запуск фонового потока ИИ с безальтернативным флагом is_portable_backend=True
        self.worker = AIWorker(
            model=str(self.current_model).strip(), 
            messages=self.chat_history, 
            options=ollama_options, 
            is_portable_backend=True
        )
        self.worker.response_received.connect(self.append_bot_chunk)
        self.worker.stats_updated.connect(self.update_generation_speed)
        self.worker.finished.connect(self.on_ai_generation_finished)
        self.worker.start()


    def on_ai_generation_finished(self):
        """🏁 Вызывается автоматически, когда ИИ закончил отправку ответа"""
        self.send_btn.setText("⚡ Отправить")
        
        # Возвращаем статус-бару стандартное рабочее состояние
        if hasattr(self, 'status_label') and self.status_label:
            self.status_label.setText("🟢 Сервер: Готов к работе")
            
        if self.bot_response_buffer.strip():
            self.chat_history.append({"role": "assistant", "content": self.bot_response_buffer})
            self.chat_html_history[self.current_session] = self.chat_area.toHtml()
            self.save_session_to_db(self.current_session)
    def continue_bot_generation(self):
        """⏭️ Продолжить генерацию, если ответ ИИ оборвался на полуслове"""
        if self.worker and self.worker.isRunning(): 
            return
        self.chat_area.append("<i><b>Вы:</b> Продолжай...</i>")
        # ПОРТАТИВНЫЙ ФОЛЛБЭК ВЗАМЕН OLLAMA CALL
        self.execute_portable_backend_call("Ты оборвал ответ. Напиши только продолжение.")

    def toggle_voice_recording(self, checked):
        if checked: self.voice_worker.start_recording()
        else: self.voice_worker.stop_and_process()

    def on_voice_text_received(self, text):
        if text: self.input_field.setText(text)

    def open_model_context_menu(self, position):
        """📂 Всплывающее меню по правой кнопке мыши для удаления выбранной ИИ-модели"""
        current_model_name = self.model_selector.currentText()
        if not current_model_name:
            return
            
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #13171c; border: 1px solid #005c4e; color: #00ffcc; padding: 2px; }
            QMenu::item:selected { background-color: #d9534f; color: #ffffff; }
        """)
        
        delete_action = QAction(f"🗑️ Удалить {current_model_name} с ПК", self)
        delete_action.triggered.connect(lambda: self.confirm_and_delete_gguf_model(current_model_name))
        menu.addAction(delete_action)
        
        menu.exec(self.model_selector.mapToGlobal(position))

    def confirm_and_delete_gguf_model(self, model_name):
        """🔴 Безопасное подтверждение и принудительное физическое удаление GGUF файла с диска"""
        from PyQt6.QtWidgets import QMessageBox
        from portable_backend import PortableLlamaEngine
        
        reply = QMessageBox.question(
            self, "Удаление модели ИИ",
            f"Вы уверены, что хотите полностью стереть файл модели '{model_name}' с диска?\nЭто действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Мягко тушим сервер перед удалением файла, чтобы снять блокировку дескрипторов
                engine = PortableLlamaEngine()
                engine.stop_server_process()
                time.sleep(0.5)

                # Вычисляем точный путь к файлу в портативной иерархии папок
                project_root = os.path.dirname(os.path.abspath(__file__))
                target_dir = os.path.normpath(os.path.join(project_root, "Model", "LLAMA CCP", "Model"))
                file_path = os.path.join(target_dir, model_name)

                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.chat_area.append(f"<br><b style='color:#ff0055;'>🔴 Система: Файл '{model_name}' полностью удален из локального хранилища!</b><br>")
                else:
                    self.chat_area.append(f"<br><b style='color:orange;'>⚠️ Система: Файл не найден по пути {file_path}. Возможно, он уже удален.</b><br>")
                
                # Мгновенно обновляем выпадающий список моделей на панели
                self.load_installed_models()
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:red;'>Система: Не удалось удалить файл с диска: {str(e)}</b><br>")


    def append_bot_chunk(self, text):
        """📥 Потоковый парсер ИИ с выводом в чат, автовыделением кода и фильтрацией TTS"""
        self.bot_response_buffer += text
        self._speech_buffer += text
        
        # 1. Рендеринг HTML в окне чата
        html_content = MarkdownHighlighter.to_html(self.bot_response_buffer)
        scrollbar = self.chat_area.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 20
        self.chat_area.setHtml(html_content)
        if at_bottom:
            self.chat_area.moveCursor(QTextCursor.MoveOperation.End)

        # Выделение блоков кода для вкладки редактора
        all_code_blocks = []
        markdown_matches = re.findall(r"```[a-zA-Z0-9_+-]*?\n([\s\S]*?)(?:```|\$)", self.bot_response_buffer)
        for block in markdown_matches:
            if block.strip():
                all_code_blocks.append(block.strip())

        if "[CREATE_FILE:" in self.bot_response_buffer:
            tag_parts = self.bot_response_buffer.split("[CREATE_FILE:", 1)
            if len(tag_parts) > 1:
                after_tag = tag_parts[1]
                if "|" in after_tag:
                    file_name_and_code = after_tag.split("|", 1)
                    if len(file_name_and_code) > 1:
                        raw_code_zone = file_name_and_code[1]
                        clean_code = re.sub(r"⚡\s*\[Агент\]:.*\$", "", raw_code_zone, flags=re.MULTILINE)
                        clean_code = re.sub(r"[\)|\]\s]*\$", "", clean_code)
                        if clean_code.strip():
                            all_code_blocks.append(clean_code.strip())

        if all_code_blocks:
            combined_code = "\n\n".join(all_code_blocks)
            if combined_code and combined_code != self.last_code_block:
                self.last_code_block = combined_code
                self.code_editor_field.setPlainText(self.last_code_block)

        # Обновление счетчика токенов на лету
        self.update_token_counter()

        # 2. Интеллектуальный фильтр текста для озвучки (TTS)
        if hasattr(self, 'cb_speech_on') and self.cb_speech_on.isChecked():
            # Если ИИ закончил предложение или перешел на новую строку
            if any(char in self._speech_buffer for char in ['.', '!', '?', '\n', ';']):
                raw_phrase = self._speech_buffer
                self._speech_buffer = "" 
                
                # Жёсткий фильтр: полностью игнорируем озвучку технического кода, спец-тегов и JSON скобок
                is_code = (
                    "```" in raw_phrase or 
                    "[CREATE_FILE:" in raw_phrase or 
                    "[RUN_CMD:" in raw_phrase or
                    "def " in raw_phrase or 
                    "import " in raw_phrase or
                    "{" in raw_phrase or 
                    "}" in raw_phrase or
                    "cmd" in raw_phrase
                )
                if is_code: 
                    return

                # Очищаем текст от Markdown разметки перед отправкой в очередь
                clean_sentence = re.sub(r'\[.*?\]|`.*?`|<[^>]*>|[*_#]', '', raw_phrase).strip()
                if len(clean_sentence) > 2 and any(c.isalpha() for c in clean_sentence):
                    # Безопасно складываем чистую фразу в очередь. Метод process_speech_queue сам подхватит её
                    self.speech_queue.put(clean_sentence)
                    self.process_speech_queue()


    def process_speech_queue(self):
        """🔊 Поочерёдное озвучивание фраз из очереди через системный синтезатор речи"""
        if not hasattr(self, 'speech_process') or not hasattr(self, 'speech_queue'):
            return
        if self.speech_process.state() != QProcess.ProcessState.NotRunning:
            return
        if self.speech_queue.empty():
            return

        sentence = self.speech_queue.get()
        if not sentence:
            return

        try:
            self.speech_process.finished.disconnect()
        except Exception:
            pass
        self.speech_process.finished.connect(lambda *_: self.process_speech_queue())

        if os.name == 'nt':
            safe_text = sentence.replace("'", "''").replace('"', ' ')
            ps_cmd = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Speak('{safe_text}')"
            )
            self.speech_process.start("powershell", ["-NoProfile", "-Command", ps_cmd])
        else:
            self.speech_process.start("espeak", [sentence])


    # Внутри класса AIClientApp в файле cyber_core_worker_v1.61.py:
    def start_autonomous_agent_loop(self):
        """Инициализация и запуск внешнего потока Мульти-Агента MoE (СТАБИЛЬНАЯ ОЧИЩЕННАЯ ВЕРСИЯ)"""
        task = self.input_field.toPlainText().strip()
        if not task: return
        self.input_field.clear()
        
        import platform
        import shutil
        os_type = platform.system()

        # 🔥 ПЕРЕХВАТ МЕДИАФАЙЛА ИЗ КНОПКИ CYBER VISION ДЛЯ АВТОНОМНОГО АГЕНТА
        media_b64_payload = []
        if hasattr(self, 'attached_media_path') and self.attached_media_path and os.path.exists(self.attached_media_path):
            try:
                ws_dir = os.path.join(os.getcwd(), "AI_Generated")
                os.makedirs(ws_dir, exist_ok=True)
                dest_media_path = os.path.join(ws_dir, os.path.basename(self.attached_media_path))
                if os.path.abspath(self.attached_media_path) != os.path.abspath(dest_media_path):
                    shutil.copy2(self.attached_media_path, dest_media_path)
                
                images_b64, _ = MediaProcessor.prepare_vision_context(dest_media_path)
                if images_b64:
                    media_b64_payload = images_b64
                task = f"[Прикреплённый файл в воркспейсе AI_Generated: {os.path.basename(dest_media_path)}]\n{task}"
            except Exception as ex_vis:
                print(f"⚠️ Ошибка передачи медиафайла в агент: {ex_vis}")
            finally:
                self.clear_attached_media()
        
        # Извлекаем чистые строки ДО инициализации потока
        audio_exp = str(self.audio_expert_selector.currentText()) if hasattr(self, 'audio_expert_selector') else "SAPI"
        image_exp = str(self.safetensors_selector.currentText()) if hasattr(self, 'safetensors_selector') else "photon_v1.safetensors"
        rag_exp = str(self.rag_expert_selector.currentText()) if hasattr(self, 'rag_expert_selector') else "BGE"
        
        experts_config = {
            "audio_expert": audio_exp,
            "image_expert": image_exp,
            "rag_expert": rag_exp
        }
        
        # Строим чистые опции для передачи в поток Агента
        agent_options = self.get_ai_options()
        agent_options["active_experts"] = experts_config
        agent_options["is_portable_backend_active"] = True
  
        # Создаем поток, передавая исключительно примитивные типы и прикреплённые медиаданные
        self.agent_thread = AutonomousAgentWorker(
            model=str(self.current_model).strip(), 
            initial_task=task, 
            options=agent_options,
            max_steps=int(self.slider_max_steps.value()), 
            media_b64_list=media_b64_payload,
            raw_debug_on=self.raw_debug_action.isChecked(), 
            os_environment=os_type,
            enable_thinking=bool(hasattr(self, 'cb_thinking') and self.cb_thinking.isChecked())
        )

        
        # Подключаем текстовые логи в чат
        self.agent_thread.step_processed.connect(lambda t, m, c: self.chat_area.append(m))
        self.agent_thread.agent_finished.connect(self.on_agent_loop_complete)
        self.agent_thread.stats_telemetry.connect(self.update_agent_telemetry)

        
        # Обновление воркспейса по безопасному таймеру
        def safe_workspace_refresh():
            try:
                self.file_model.setRootPath(os.path.join(os.getcwd(), "AI_Generated"))
                self.chat_area.moveCursor(QTextCursor.MoveOperation.End)
            except Exception:
                pass
            
        self.agent_thread.step_processed.connect(
            lambda t, m, c: QTimer.singleShot(30, safe_workspace_refresh) if t == "thoughts" or c in ["generate_image_diffusion", "vision_analyze_file"] else None
        )
        
        self.btn_auto_ai.setText("🛑 Стоп AI")
        self.btn_auto_ai.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
        
        try: self.btn_auto_ai.clicked.disconnect()
        except Exception: pass
        self.btn_auto_ai.clicked.connect(self.stop_autonomous_agent_loop)
        
        self.agent_thread.start()
         
    def update_agent_telemetry(self, used_tokens, max_ctx, speed_tps):
        """📊 Обновление счётчика контекста и скорости ИИ в реальном времени для Auto AI"""
        try:
            pct = min(100, int((used_tokens / max(1, max_ctx)) * 100))
            if hasattr(self, 'lbl_token_usage'):
                self.lbl_token_usage.setText(f"Занято: {used_tokens} / {max_ctx} токенов ({pct}%)")
            if hasattr(self, 'lbl_generation_speed'):
                self.lbl_generation_speed.setText(f"Скорость ИИ: {speed_tps:.1f} tok/sec")
        except Exception:
            pass

    def stop_autonomous_agent_loop(self):
        """Принудительная ручная остановка потока агента со сбросом кнопки"""
        if hasattr(self, 'agent_thread') and self.agent_thread.isRunning():
            self.agent_thread.stop_agent()
            self.chat_area.append("<br><b style='color:#d9534f;'>🛑 [CyberCore]: Сигнал принудительной остановки отправлен ИИ Агенту...</b><br>")
            
        # 🔥 МГНОВЕННЫЙ СБРОС КНОПКИ В ИСХОДНЫЙ ВИД
        self.btn_auto_ai.setText("🤖 Auto AI")
        self.btn_auto_ai.setStyleSheet("") # Возвращаем оригинальную киберпанк тему
        
        # Переподключаем событие клика обратно на запуск
        try:
            self.btn_auto_ai.clicked.disconnect()
        except Exception:
            pass
        self.btn_auto_ai.clicked.connect(self.start_autonomous_agent_loop)

    def on_agent_loop_complete(self, final_msg):
        """🏁 Автоматический вызов при завершении цикла Агента"""
        if hasattr(self, 'tg_bridge') and self.tg_bridge:
            try:
                self.tg_bridge.mark_task_finished()
            except Exception:
                pass

        self.chat_area.append(f"<br><b style='color:#5cb85c;'>🏁 {final_msg}</b><br>")
        
        self.btn_auto_ai.setText("🤖 Auto AI")
        self.btn_auto_ai.setStyleSheet("")
        
        try:
            self.btn_auto_ai.clicked.disconnect()
        except Exception:
            pass
        self.btn_auto_ai.clicked.connect(self.start_autonomous_agent_loop)
        
        try:
            if hasattr(self, 'agent_thread') and hasattr(self, 'current_session'):
                self.chat_sessions[self.current_session] = self.agent_thread.history
                self.chat_html_history[self.current_session] = self.chat_area.toHtml()
                self.save_session_to_db(self.current_session)
                self.update_token_counter()
        except Exception as e:
            print(f"Ошибка сохранения сессии агента: {e}")

    def on_telegram_command_received(self, tg_text):
        """📲 Безопасная обработка задачи, пришедшей с телефона через Telegram"""
        try:
            if hasattr(self, 'agent_thread') and self.agent_thread and self.agent_thread.isRunning():
                self.tg_bridge.send_reply("⏳ Агент сейчас занят выполнением предыдущей задачи. Дождитесь завершения.")
                return

            self.chat_area.append(f"<br><b style='color:#00ffcc;'>📲 [Команда из Telegram]:</b> {tg_text}<br>")
            self.input_field.setPlainText(str(tg_text))
            
            # Запускаем автономный цикл агента
            self.start_autonomous_agent_loop()

            # Подключаем отправку результата в Telegram, только если поток успешно создался
            if hasattr(self, 'agent_thread') and self.agent_thread:
                def send_final_to_tg(final_report):
                    try:
                        self.tg_bridge.send_reply(f"✅ {final_report}")
                    except Exception:
                        pass
                    try:
                        self.agent_thread.agent_finished.disconnect(send_final_to_tg)
                    except Exception:
                        pass

                self.agent_thread.agent_finished.connect(send_final_to_tg)
        except Exception as e:
            err_msg = f"❌ Сбой при запуске задачи из Telegram: {str(e)}"
            self.chat_area.append(f"<b style='color:red;'>{err_msg}</b><br>")
            if hasattr(self, 'tg_bridge'):
                self.tg_bridge.send_reply(err_msg)
                self.tg_bridge.mark_task_finished()



    def show_diffusion_help_dialog(self):
        """🎨 Окно документации по локальному контуру генерации картинок Stable Diffusion"""
        from PyQt6.QtWidgets import QMessageBox, QSpacerItem, QGridLayout, QSizePolicy
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Руководство: Локальная генерация графики")
        
        help_text = (
            "<h2>🎨 Контур нейросетевого рендеринга Stable Diffusion (v1.6)</h2>"
            "Cyber Core поддерживает полностью автономный инференс изображений, текстур и схем на "
            "вычислительных ядрах вашего ПК без обращения к облачным серверам.<br><br>"
            
            "<h3>📝 1. Мультиязычный перевод промптов (Лингвистический контур)</h3>"
            "• Модели диффузии (CLIP) понимают исключительно английский язык. В Cyber Core встроен "
            "автоматический транслятор: если вы пишете запрос на русском, система изолированно обращается "
            "к активной текстовой модели Ollama (например, Llama3) с нулевой температурой, переводит его "
            "и передает готовые токены в PyTorch-конвейер.<br>"
            "• Если в запросе обнаружены латинские символы, автоматический перевод отключается.<br><br>"
            
            "<h3>🚫 2. Негативный запрос (Negative Prompt)</h3>"
            "• Описывает объекты и артефакты, которых <b>не должно быть</b> на картинке. По умолчанию "
            "заданы стандартные фильтры деформаций (blur, bad anatomy, ugly). Вы можете расширять их, "
            "дописывая через запятую исключения (например: text, watermark, monochrome).<br><br>"
            
            "<h3>📐 3. Размер, Шаги (Steps) и Seed</h3>"
            "• <b>Размер (Разрешение):</b> Базовые веса оптимизированы под 512x512 или 768x768. Изменение "
            "соотношения сторон (например, 512x768) полезно для портретных или пейзажных концептов.<br>"
            "• <b>Шаги (20, 30, 50):</b> Количество проходов денойзинга (очистки шума в пиксели). Для CPU-инференса "
            "оптимально ставить 20-30 шагов для баланса скорости и детализации.<br>"
            "• <b>Зерно (Seed):</b> Уникальный математический инициализатор шума. Значение <code>-1</code> "
            "каждый раз генерирует случайный рисунок. Если вам понравилась композиция и вы хотите точечно "
            "изменить промпт, зафиксируйте числовой Seed из лога чата.<br><br>"
            
            "<h3>🎯 4. Креативность (CFG Scale): от 1.0 до 10.0</h3>"
            "• Управляет тем, насколько строго ИИ следует вашему текстовому промпту. "
            "Низкие значения дают абстрактные и смазанные результаты, высокие (9-10) — делают картинку контрастной "
            "и перенасыщенной. Рекомендуемый оптимум для Photon весов: <b>7.5</b>."
        )
        
        msg.setText(help_text)
        msg.setStyleSheet("""
            QMessageBox { background-color: #0d0f12; min-width: 780px; }
            QLabel { color: #e3e8ef; font-size: 13px; line-height: 1.5; }
            h2 { color: #00ffcc; font-size: 16px; font-weight: bold; margin-bottom: 10px; }
            h3 { color: #00b395; font-size: 14px; font-weight: bold; margin-top: 14px; margin-bottom: 4px; }
            code { background-color: #13171c; color: #ffaa00; padding: 1px 4px; border-radius: 3px; font-family: monospace; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; padding: 6px 25px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; border: 1px solid #00b395; }
        """)
        
        layout = msg.layout()
        if layout and isinstance(layout, QGridLayout):
            spacer = QSpacerItem(750, 0, QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Ignored)
            layout.addItem(spacer, layout.rowCount(), 0, 1, layout.columnCount())

        msg.exec()

    def show_all_tools_help_dialog(self):
        """🛠️ Полный актуальный каталог всех 45 инструментов автономного агента CyberCore"""
        html_text = """
        <h2>🛠️ Каталог инструментов автономного агента CyberCore (v1.7)</h2>
        В режиме <b>🤖 Auto AI</b> нейросети доступно <b>45 встроенных инструментов</b> в воркспейсе <code>AI_Generated</code>.<br>

        <h3>📁 1. Файловая система и поиск (10 инструментов)</h3>
        <ul>
            <li><code>write_file</code> / <code>patch_file</code> — Создание файла (с бэкапом <code>.bak</code>) и точечная замена строк (для файлов &gt; 40 строк).</li>
            <li><code>read_file</code> / <code>read_file_lines</code> — Чтение файла целиком или указанного диапазона строк.</li>
            <li><code>move_file</code> / <code>delete_file_or_folder</code> — Перемещение, переименование и удаление объектов.</li>
            <li><code>list_dir</code> / <code>check_file_exists</code> — Дерево файлов воркспейса и проверка наличия файла.</li>
            <li><code>file_search_glob</code> / <code>search_in_files</code> — Поиск файлов по маске (<code>*.py</code>) и поиск текста/Regex внутри кода.</li>
        </ul>

        <h3>💻 2. Разработка, AST, Git и терминал (6 инструментов)</h3>
        <ul>
            <li><code>run_terminal_command</code> — Запуск команд ОС с автоперехватом <code>STDOUT/STDERR</code> и фоновым стартом серверов.</li>
            <li><code>run_python_isolated</code> — Изолированный запуск Python-кода для расчётов и массовой сортировки файлов.</li>
            <li><code>python_ast_analyzer</code> — Карта структуры Python-файла (классы, функции, методы, номера строк) без чтения всего кода.</li>
            <li><code>install_package</code> / <code>get_code_documentation</code> — Установка пакетов <code>pip</code> и чтение встроенных docstring.</li>
            <li><code>git_control</code> — Версионность в воркспейсе (<code>init</code>, <code>status</code>, <code>commit</code>, <code>diff</code>, <code>log</code>, <code>rollback</code>).</li>
        </ul>

        <h3>🗄️ 3. Базы данных, таблицы, документы и RAG (7 инструментов)</h3>
        <ul>
            <li><code>db_execute_query</code> — SQL-запросы к <b>SQLite</b> (а также контур PostgreSQL, MySQL, MongoDB, Redis).</li>
            <li><code>excel_csv_read</code> / <code>excel_csv_write</code> — Чтение и запись таблиц <code>.xlsx</code>, <code>.xls</code> и <code>.csv</code>.</li>
            <li><code>extract_document_text</code> — Прямое извлечение текста из <b>PDF</b> и <b>Word (.docx)</b>.</li>
            <li><code>rag_index_text</code> / <code>rag_index_file</code> / <code>rag_search</code> — Индексация текста или целых файлов в <b>ChromaDB</b> и семантический поиск.</li>
        </ul>

        <h3>🌐 4. Интернет, API и Headless-браузер (6 инструментов)</h3>
        <ul>
            <li><code>web_search</code> / <code>fetch_web_page_text</code> — Поиск в сети и очистка веб-страниц от HTML-тегов.</li>
            <li><code>browser_headless_render</code> — Рендеринг JS/React/Vue сайтов в скрытом <b>Chromium (Playwright)</b> со скриншотом.</li>
            <li><code>http_api_request</code> / <code>network_download_file</code> / <code>network_diagnostics</code> — REST API клиент, скачивание файлов и проверка портов/DNS.</li>
        </ul>

        <h3>🎨 5. Графика, зрение и аналитика (5 инструментов)</h3>
        <ul>
            <li><code>generate_image_diffusion</code> — Локальная генерация картинок (<b>Stable Diffusion</b>) с автовыгрузкой и возвратом LLM.</li>
            <li><code>vision_analyze_file</code> / <code>take_screen_shot</code> / <code>get_image_metadata</code> — Визуальный анализ фото, снимки экрана и EXIF.</li>
            <li><code>create_chart</code> — Построение графиков (<code>bar</code>, <code>line</code>, <code>pie</code>) с выводом прямо в чат.</li>
        </ul>

        <h3>🖥️ 6. Управление ОС, окнами, архивами и Telegram (11 инструментов)</h3>
        <ul>
            <li><code>gui_control</code> / <code>window_control</code> — Управление мышью, клавиатурой (<code>hotkey</code>) и окнами ОС.</li>
            <li><code>get_process_list</code> / <code>kill_process_by_pid</code> — Просмотр процессов ОС и завершение зависших задач по PID.</li>
            <li><code>clipboard_get_text</code> / <code>clipboard_set_text</code> — Работа с системным буфером обмена.</li>
            <li><code>archive_pack</code> / <code>archive_unpack</code> — Упаковка в ZIP (с исключением ChromaDB) и распаковка архивов.</li>
            <li><code>read_env_variable</code> / <code>sys_get_disk_space</code> / <code>send_telegram_message</code> — Переменные среды, место на диске и отправка в Telegram.</li>
        </ul>
        """
        self._open_cyber_help_window("Каталог инструментов — CyberCore v1.7", html_text, width=860, height=660)

    def get_ai_options(self):
        """Сборка актуальных математических весов генерации со всех ползунков интерфейса"""
        return {
            "temperature": float(self.slider_temp.value() / 10.0),
            "top_p": float(self.slider_topp.value() / 10.0),
            "top_k": int(self.slider_topk.value()),
            "mirostat": int(self.slider_miro.value()),
            "repeat_penalty": float(self.slider_penalty.value() / 10.0),
            "frequency_penalty": float(self.slider_freq_penalty.value() / 10.0),
            "presence_penalty": float(self.slider_pres_penalty.value() / 10.0),
            "num_ctx": int(self.ctx_steps.get(self.slider_ctx.value(), 4096)),
            "num_predict": int(self.predict_steps.get(self.slider_predict.value(), 4096)),
            "num_thread": int(self.slider_threads.value()),
            "parallel_slots": int(self.slider_np.value()) if hasattr(self, 'slider_np') else 1,
            "no_kv_offload": 1 if (hasattr(self, 'cb_no_kv_offload') and self.cb_no_kv_offload.isChecked()) else 0,
            "kv_compress": 1 if (hasattr(self, 'cb_kv_compress') and self.cb_kv_compress.isChecked()) else 0,
            "enable_thinking": bool(hasattr(self, 'cb_thinking') and self.cb_thinking.isChecked())
        }



    def toggle_raw_debug_mode(self, checked):
        """Включение/выключение отображения сырых пакетов ИИ в окне чата"""
        self.raw_debug_on = checked
        self.save_ui_setting("raw_debug_enabled", 1 if checked else 0)
        status = "включен" if checked else "выключен"
        self.chat_area.append(f"<br><i style='color:#00ffcc;'>[Отладчик]: Режим вывода сырых пакетов {status}.</i><br>")

    def trigger_local_image_generation(self):
        """🎨 Пошаговый алгоритм линейного вытеснения памяти (СТАБИЛЬНЫЙ И БЕЗОПАСНЫЙ КОНТУР QT)"""
        print("\n🔍 [DEBUG SD]: Вход в метод trigger_local_image_generation")
        
        user_prompt = self.input_field.toPlainText().strip()
        if not user_prompt:
            self.chat_area.append("<br><b style='color:orange;'>⚠️ [Система]: Введите описание картинки в поле запроса!</b><br>")
            return
            
        self.btn_generate_local_image.setEnabled(False)
        self.btn_generate_local_image.setText("⏳ Идет пошаговый инференс...")
        
        # 🔥 ЖЕСТКАЯ ЗАМОРОЗКА ПУТИ ИЗ СЕЛЕКТОРОВ (ЗАЩИТА ОТ ПОТЕРИ ИМЕНИ ПОДПАПКИ)
        frozen_text_model_path = str(self.model_selector.currentText()).strip().replace("\\", "/")
        frozen_text_model_path = frozen_text_model_path.replace("Model/LLAMA CCP/Model/", "").replace("Model/LLAMA CCP/", "")
        if frozen_text_model_path.startswith("Model/"):
            frozen_text_model_path = frozen_text_model_path[6:]
            
        self.current_model = frozen_text_model_path

        # Сбор параметров Stable Diffusion
        size_str = self.size_selector.currentText()
        width, height = map(int, size_str.split("x"))
        steps = int(self.steps_selector.currentText())
        cfg = float(self.cfg_selector.currentText())
        
        import random
        seed_text = self.seed_field.text().strip()
        seed = int(seed_text) if seed_text.isdigit() and int(seed_text) > 0 else random.randint(1, 100000000)
        
        selected_sd_file = self.safetensors_selector.currentText()
        model_dir_path = os.path.normpath(os.path.join(os.getcwd(), "Model", "Image_Gen", selected_sd_file))
        final_output_path = os.path.normpath(os.path.join(os.getcwd(), "AI_Generated", f"render_{seed}.png"))
        negative_prompt = self.negative_prompt_field.text().strip()
        ai_options = self.get_ai_options()

        # === ШАГ 1: ЛИНГВИСТИЧЕСКИЙ КОНТУР (ПЕРЕВОД ПРОМПТА) ===
        self.chat_area.append("<br><b style='color:#00ffcc;'>Шаг 1/5: Лингвистический контур. Запрос перевода текста...</b>")
        QApplication.processEvents()
        
        try:
            from image_generation_expert import ImageGenerationExpert
            translated_prompt = ImageGenerationExpert.translate_prompt_via_ollama(
                user_prompt, frozen_text_model_path, is_portable=True
            )
            self.chat_area.append(f"<b>ИИ выдал перевод:</b> <i style='color:#00ffcc;'>\"{translated_prompt}\"</i>")
        except Exception as e_trans:
            translated_prompt = user_prompt
            self.chat_area.append(f"<br><b style='color:orange;'>⚠️ [Предупреждение]: Сбой автоперевода, использую оригинал: {e_trans}</b>")
        
        QApplication.processEvents()

        # === ШАГ 2: ОЧИСТКА ПАМЯТИ (ВЫГРУЗКА ИЗ ОЗУ ЧЕРЕЗ TASKKILL) ===
        self.chat_area.append("<br><b style='color:#00ffcc;'>Шаг 2/5: Очистка памяти. Выгружаю текстовое ядро из ОЗУ...</b>")
        QApplication.processEvents()
        
        try:
            if os.name == 'nt':
                subprocess.run("taskkill /f /im llama-server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("taskkill /f /im llama.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
            
        time.sleep(1.5) # Даем Windows время полностью закрыть порты и освободить ОЗУ

        # === ШАГ 3: ПОДГОТОВКА И ЗАПУСК ГРАФИЧЕСКОГО КОНТУРА ЧЕРЕЗ QTHREAD ===
        self.chat_area.append("<br><b style='color:#00ffcc;'>Шаг 3/5: Графический контур. Загрузка Stable Diffusion на CPU...</b>")
        QApplication.processEvents()

        # Функция обратного вызова, которая сработает СТРОГО ПОСЛЕ ТОГО, как картинка полностью готова!
        def on_sequential_image_ready(status, file_path, log_msg):
            self.btn_generate_local_image.setEnabled(True)
            self.btn_generate_local_image.setText("🎨 Генерировать на Intel Arc")
            
            if status and os.path.exists(file_path):
                self.chat_area.append("<br><b style='color:#00ffcc;'>Шаг 4/5: Визуализация. Отрисовка сгенерированного файла...</b>")
                html_ready_path = file_path.replace('\\', '/')
                html_preview = f'<br><img src="file:///{html_ready_path}" width="450" style="border:1px solid #005c4e; border-radius:6px; margin:5px 0;"><br>'
                self.chat_area.append(html_preview)
                self.chat_area.append(f"📂 Файл сохранен: <code>{os.path.basename(file_path)}</code>")
                QApplication.processEvents()
                
                # ВОТ ТЕПЕРЬ, СТРОГО ПОСЛЕ КАРТИНКИ, ИНИЦИАЛИЗИРУЕМ ШАГ 5/5
                self.chat_area.append("<br><b style='color:#00ffcc;'>Шаг 5/5: Восстановление ресурсов. Возвращаю выбранную модель ИИ в ОЗУ...</b>")
                self.status_label.setText("⏳ Загрузка GGUF...")
                QApplication.processEvents()
                
                try:
                    from portable_backend import PortableLlamaEngine
                    engine_restore = PortableLlamaEngine(frozen_text_model_path, ai_options)
                    if engine_restore.start_server_if_needed():
                        self.status_label.setText("🟢 Движок: Портативный (llama.cpp)")
                        self.chat_area.append("<br><b style='color:#00ffcc;'>✅ [Ресурсы]: Локальная модель успешно реанимирована!</b><br>")
                except Exception as ex_boot:
                    print(f"❌ Сбой рестарта GGUF: {ex_boot}")
                    self.status_label.setText("🔴 Сбой реанимации ядра")
            else:
                self.chat_area.append(f"<br><b style='color:red;'>❌ [Сбой графического конвейера]: {log_msg}</b><br>")
            
            self.chat_area.moveCursor(QTextCursor.MoveOperation.End)

        from image_generation_expert import LocalDiffusionWorker
        self.diffusion_runner = LocalDiffusionWorker(
            model_dir=model_dir_path, prompt=translated_prompt, 
            negative_prompt=negative_prompt,
            width=width, height=height, steps=steps, cfg=cfg, seed=seed, 
            output_path=final_output_path, ollama_model=self.current_model, is_portable=True
        )
        
        # Привязываем завершение потока к нашему последовательному коллбэку
        self.diffusion_runner.generation_finished.connect(on_sequential_image_ready)
        
        # ЗАПУСКАЕМ ВОРКЕР (Хвост-призрак полностью удален, метод чисто завершается на этой строке)
        self.diffusion_runner.start()

    def on_local_image_ready(self, status, file_path, log_msg):
        """🏁 Обработка результатов инференса и отрисовка картинки в HTML-чат"""
        self.btn_generate_local_image.setEnabled(True)
        self.btn_generate_local_image.setText("🎨 Генерировать на Intel Arc")
        
        if status and os.path.exists(file_path):
            from chart_processor import ChartProcessor
            html_preview = ChartProcessor.file_to_html_img(file_path, width=450)
            
            self.chat_area.append(f"<br><b style='color:#00ffcc;'>✅ [Intel Arc GPU]: Generation Complete. Промпт переведен как:</b> <i>\"{log_msg}\"</i>")
            self.chat_area.append(html_preview)
            self.chat_area.append(f"📂 Файл сохранен: <code>{os.path.basename(file_path)}</code><br>")
        else:
            self.chat_area.append(f"<br><b style='color:red;'>❌ [Сбой Intel OpenVINO]:</b> Ошибка выполнения графического конвейера:<br><pre>{log_msg}</pre><br>")
            
        self.chat_area.moveCursor(QTextCursor.MoveOperation.End)

    
    def apply_cyberpunk_theme(self):
        """🎨 Мягкий киберпанк-стиль: яркость рамок снижена, выделение чатов и файлов приглушено"""
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0f12; }
            QWidget { background-color: #0d0f12; color: #00b395; font-family: 'Segoe UI', Arial; }
            QGroupBox { border: 1px solid #005c4e; border-radius: 6px; margin-top: 0px; font-weight: bold; color: #00b395; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: -4px; padding: 0 5px; background-color: #0d0f12; }
            QTextEdit { background-color: #13171c; border: none; border-radius: 4px; color: #ffffff; font-size: 13px; }
            
            /* 📂 МЯГКИЙ СТИЛЬ ДЛЯ СПИСКА ЧАТОВ И ДЕРЕВА ФАЙЛОВ */
            QListWidget, QTreeView { 
                background-color: #13171c; 
                border: none; 
                border-radius: 4px; 
                color: #8fa0b0; /* Приглушенный серо-синий цвет для обычного текста */
            }
            /* Снижаем яркость и агрессивность выделения строк */
            QListWidget::item:selected, QTreeView::item:selected { 
                background-color: #0c2b24; /* Глубокий темно-изумрудный фон вместо яркого */
                color: #00ffcc; /* Спокойный бирюзовый текст для активного элемента */
                border-radius: 3px;
            }
            QListWidget::item:hover, QTreeView::item:hover { 
                background-color: #1a232a; /* Едва заметный серый оттенок при наведении мыши */
                color: #ffffff;
            }
            
            QLineEdit, QComboBox { background-color: #13171c; border: 1px solid #005c4e; border-radius: 4px; color: #00ffcc; padding: 3px; }
            QTabWidget::pane { border: 1px solid #005c4e; background: #13171c; border-radius: 4px; top: -1px; }
            QTabBar::tab { background: #1a1f26; border: 1px solid #005c4e; border-bottom: none; color: #00b395; padding: 5px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; font-size: 11px; font-weight: bold; }
            QTabBar::tab:selected { background: #13171c; color: #00ffcc; border-bottom: 1px solid #13171c; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; border-radius: 4px; color: #00ffcc; font-weight: bold; padding: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; }
            QSlider::groove:horizontal { border: 1px solid #222; height: 6px; background: #13171c; border-radius: 3px; }
            QSlider::handle:horizontal { background: #00b395; width: 14px; margin: -4px 0; border-radius: 7px; }
            QLabel, QCheckBox { color: #00b395; font-size: 11px; }
        """)
        # Стилизация нашей шторки в цвет фона (без изменений)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton { 
                background-color: #0d0f12; 
                border: none; 
                color: #005c4e; 
                font-weight: bold; 
                font-size: 8px; 
                padding: 0px;
            } 
            QPushButton:hover { color: #00ffcc; background-color: #13171c; }
        """)
if __name__ == "__main__":
    import traceback
    
    # Сверхнадежный глобальный логгер критических падений приложения
    def crash_exception_hook(exctype, value, tb):
        error_msg = "".join(traceback.format_exception(exctype, value, tb))
        
        # 1. Записываем трейсбек падения в физический файл на жесткий диск ПК
        with open("crash_report.log", "w", encoding="utf-8") as f:
            f.write("=== КРИТИЧЕСКИЙ СБОЙ СИСТЕМЫ CYBERCORE ===\n")
            f.write(f"Время: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(error_msg)
            
        # 2. Дублируем вывод в стандартный поток ошибок
        sys.__excepthook__(exctype, value, tb)
        
        # 3. Пытаемся показать аварийное окно пользователю, если GUI еще жив
        try:
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("CyberCore — Аварийное завершение")
            msg.setText("Обнаружен критический сбой подсистемы Python/Qt!\nЛог сохранен в файл: crash_report.log")
            msg.setDetailedText(error_msg)
            msg.exec()
        except Exception:
            pass
            
        sys.exit(1)

    # Регистрируем логгер в операционной системе
    sys.excepthook = crash_exception_hook

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    client = AIClientApp()
    client.show()
    sys.exit(app.exec())

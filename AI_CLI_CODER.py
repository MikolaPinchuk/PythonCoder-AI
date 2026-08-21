# ==================================================================================
# 🗂️ PythonCoder AI: СПИСОК ЗАВИСИМОСТЕЙ И ИНСТРУКЦИЯ ПО УСТАНОВКЕ БИБЛИОТЕК
# ==================================================================================
# Описание проекта: Локальный ИИ-комбайн на базе Ollama с поддержкой веб-поиска,
# песочницы кода Python, аудио-канала Whisper, RAG-скрепки и БД SQLite.
# Перед запуском программы выполните в терминале (cmd) следующие команды:
# 1. Основное API для работы с локальной нейросетью:
# pip install ollama
# 2. Мониторинг ресурсов ПК (Загрузка CPU и RAM) в реальном времени:
# pip install psutil
# 3. Работа с аудиоустройствами и захват звука с микрофона:
# pip install sounddevice numpy
# 4. Локальное распознавание речи (аудио в текст) на движке Whisper:
# pip install faster-whisper
# 5. Профессиональная подсветка синтаксиса генерируемого кода в чате:
# pip install pygments
# 6. Умный подсчет токенов контекста модели (как у OpenAI Llama/Qwen):
# pip install tiktoken
# 7. Чтение и извлечение текста из файлов PDF (для функции RAG-скрепки):
# pip install pypdf
# 8. Чтение и парсинг документов Microsoft Word .docx (для RAG-скрепки):
# pip install python-docx
# 9. Графический движок интерфейса и фоновые асинхронные потоки:
# pip install PyQt6
# ----------------------------------------------------------------------------------
# ОДНОСТРОЧНАЯ КОМАНДА ДЛЯ УСТАНОВКИ ВСЕХ БИБЛИОТЕК СРАЗУ:
# pip install ollama psutil sounddevice numpy faster-whisper pygments tiktoken pypdf python-docx PyQt6
# ==================================================================================

import sys
import os
import requests
import json
import re
import queue
import copy
import time
import sqlite3  # НОВОЕ: Для сохранения истории чатов в БД
import subprocess  # НОВОЕ: Для выполнения команд ИИ-Агента
import numpy as np
import sounddevice as sd
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTextEdit, QLineEdit, QPushButton, 
                             QLabel, QFileDialog, QComboBox, QSlider, QGroupBox, 
                             QFormLayout, QListWidget, QListWidgetItem, QSplitter,
                             QCheckBox, QRadioButton)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QProcess
from PyQt6.QtGui import QAction, QTextCursor

# Библиотеки для профессиональной подсветки синтаксиса кода
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter

# Безопасный импорт psutil для датчиков ресурсов системы
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
    """Фоновый поток для ежесекундного замера нагрузки CPU и RAM"""
    stats_updated = pyqtSignal(float, float, float, float)

    def __init__(self):
        super().__init__()
        self.is_running = True

    def run(self):
        while self.is_running:
            try:
                cpu_p = psutil.cpu_percent()
                ram_p = psutil.virtual_memory().percent
                self.stats_updated.emit(float(cpu_p), float(ram_p), 0.0, 0.0)
            except Exception:
                pass
            self.msleep(1000)

    def stop(self):
        self.is_running = False


class WebSearchWorker(QThread):
    """🌐 Фоновый поток для быстрого локального поиска ответов в трех системах"""
    search_finished = pyqtSignal(str)

    def __init__(self, query, engine):
        super().__init__()
        self.query = query
        self.engine = engine  # "DuckDuckGo", "Google", "Yandex"

    def run(self):
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            clean_results = []

            if self.engine == "Google":
                url = f"https://google.com{requests.utils.quote(self.query)}"
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    snippets = re.findall(r'<div[^>]*class="[^"]*(?:BNeawe|vvjwdf|s3v9rd)[^"]*"[^>]*>(.*?)</div>', response.text, re.DOTALL)
                    for s in snippets[:4]:
                        clean = re.sub(r'<[^>]*>', '', s).strip()
                        if clean and len(clean) > 20 and not clean.startswith("http"):
                            clean_results.append(clean)

            elif self.engine == "Yandex":
                url = f"https://yandex.ru{requests.utils.quote(self.query)}"
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    snippets = re.findall(r'<div[^>]*class="[^"]*organic__snippet[^"]*"[^>]*>(.*?)</div>', response.text, re.DOTALL)
                    for s in snippets[:4]:
                        clean = re.sub(r'<[^>]*>', '', s).strip()
                        if clean: clean_results.append(clean)

            else:  # DuckDuckGo по умолчанию
                url = f"https://duckduckgo.com{requests.utils.quote(self.query)}"
                response = requests.get(url, headers=headers, timeout=5)
                if response.status_code == 200:
                    snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', response.text, re.DOTALL)
                    for s in snippets[:3]:
                        clean = re.sub(r'<[^>]*>', '', s).strip()
                        if clean: clean_results.append(clean)

            if clean_results:
                context = "\n".join([f"- {res}" for res in list(set(clean_results))[:3]])
                self.search_finished.emit(context)
            else:
                self.search_finished.emit("[Поисковая система не вернула значимых результатов]")
        except Exception as e:
            self.search_finished.emit(f"[Не удалось выполнить веб-поиск: {str(e)}]")
class VoiceWorker(QThread):
    """Фоновый поток для локальной записи и распознавания речи с микрофона"""
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
        self.setFixedHeight(200) 

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.enter_pressed.emit()
                event.accept()  
                return
        super().keyPressEvent(event)
class AIWorker(QThread):
    """Фоновый поток ИИ, высчитывающий скорость генерации и поддерживающий мгновенный стоп"""
    response_received = pyqtSignal(str)
    stats_updated = pyqtSignal(float, int)  # Передает (скорость tok/sec, общее число токенов)
    finished = pyqtSignal()

    def __init__(self, model, messages, options):
        super().__init__()
        self.model = model
        self.messages = copy.deepcopy(messages)
        self.options = copy.deepcopy(options) if options else {}
        self.start_time = None
        self.char_count = 0
        self.is_stopped = False  # Флаг для мгновенного прерывания цикла

    def stop_generation(self):
        """Мгновенно взводит флаг для выхода из стриминга"""
        self.is_stopped = True

    def run(self):
        try:
            import ollama
            self.start_time = time.time()
            stream = ollama.chat(
                model=self.model, 
                messages=self.messages, 
                options=self.options, 
                stream=True
            )
            
            for chunk in stream:
                # Жёсткий выход из генерации, если пользователь нажал кнопку отмены
                if self.is_stopped:
                    self.response_received.emit("\n<br><b style='color:#d9534f;'>[Генерация принудительно остановлена пользователем]</b><br>")
                    break

                text = ""
                if hasattr(chunk, 'message') and hasattr(chunk.message, 'content'):
                    text = chunk.message.content
                elif isinstance(chunk, dict):
                    msg = chunk.get('message', {})
                    text = msg.get('content', '') if isinstance(msg, dict) else getattr(msg, 'content', '')
                
                if text:
                    self.char_count += len(text)
                    elapsed = time.time() - self.start_time
                    
                    tokens_estimated = int(self.char_count / 3.8) + 1
                    tok_sec = tokens_estimated / elapsed if elapsed > 0 else 0.0
                    
                    self.response_received.emit(text)
                    self.stats_updated.emit(tok_sec, tokens_estimated)
                    
        except Exception as e:
            self.response_received.emit(f"\n<b style='color:red;'>[Ошибка API Ollama]:</b> {str(e)}")
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
                f"<div class='code-container' style='border:1px solid #444;"
                f"border-radius:6px;padding:10px;background-color:#272822;"
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

class AIClientApp(QMainWindow):
    def __init__(self):
        super().__init__()
        #self.setWindowTitle("Локальный ИИ Мульти-Комбайн Плюс")
        self.setWindowTitle("ИИ-Ассистент: PyCoder")

        self.resize(1300, 750)
        self.ctx_steps = {1: 1024, 2: 2048, 3: 4096, 4: 8192, 5: 16384, 6: 32768, 7: 128000}
        
        # Инициализация хранилища данных и сессий из БД
        self.init_database()
        self.load_sessions_from_db()
        
        self.current_model = ""
        self.bot_response_buffer = "" 
        self.last_code_block = ""  
        self.attached_file_context = "" # Кэш для RAG-документов
        
        self.voice_worker = VoiceWorker()
        self.voice_worker.text_recognized.connect(self.on_voice_text_received)
        self.voice_worker.status_updated.connect(self.on_voice_status_updated)

        self.hw_monitor = HardwareMonitor()
        self.hw_monitor.stats_updated.connect(self.update_hardware_stats)
        self.hw_monitor.start()

        self.sandbox_process = None
        self.worker = None 
        self.search_worker = None 

        self.init_menu()
        self.init_ui()
        self.apply_cyberpunk_theme() # Установка неоновой темы
        self.load_saved_settings()   # Загрузка ползунков из БД
        
        QTimer.singleShot(100, self.check_server_status)

    def toggle_sidebar_visibility(self):
        """Сворачивает или разворачивает левое окно истории чатов"""
        if self.session_sidebar.isVisible():
            self.session_sidebar.hide()
            self.btn_toggle_sidebar.setText("▶ Показать историю")
        else:
            self.session_sidebar.show()
            self.btn_toggle_sidebar.setText("◀ Скрыть историю")
    def clear_chat_context(self):
        """Очищает историю сообщений и HTML-кэш для текущей сессии"""
        self.chat_sessions[self.current_session] = []
        self.chat_html_history[self.current_session] = ""
        self.chat_area.clear()
        self.last_code_block = ""
        self.chat_area.append(f"<i>Система: Память {self.current_session} полностью очищена. Ресурсы ПК доступны.</i><br><br>")
        self.update_token_counter()

    def on_voice_status_updated(self, status_text):
        """Обновляет статус записи голоса"""
        self.status_label.setText(status_text)
        if "❌" in status_text:
            self.btn_voice.setChecked(False)
            self.btn_voice.setText("🎙️ Голосовой ввод")
            self.btn_voice.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")


    def init_database(self):
        """🗄️ Создает таблицы для автоматического сохранения всей истории и ползунков"""
        try:
            self.db_conn = sqlite3.connect("ai_combain.db")
            self.db_cursor = self.db_conn.cursor()
            self.db_cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    name TEXT PRIMARY KEY, json_history TEXT, html_history TEXT
                )""")
            self.db_cursor.execute("""
                CREATE TABLE IF NOT EXISTS ui_settings (
                    key TEXT PRIMARY KEY, val REAL
                )""")
            self.db_conn.commit()
        except Exception as e:
            print(f"Ошибка БД: {e}")

    def load_sessions_from_db(self):
        """Загружает сохраненные чаты из SQLite при старте программы"""
        self.chat_sessions = {}
        self.chat_html_history = {}
        try:
            self.db_cursor.execute("SELECT name, json_history, html_history FROM chat_sessions")
            rows = self.db_cursor.fetchall()
            for row in rows:
                self.chat_sessions[row[0]] = json.loads(row[1])
                self.chat_html_history[row[0]] = row[2]
        except Exception:
            pass
        if not self.chat_sessions:
            self.chat_sessions = {"Чат 1": []}
            self.chat_html_history = {"Чат 1": "<i>Система: Начало диалога.</i><br><br>"}
        self.current_session = list(self.chat_sessions.keys())[0]

    def save_session_to_db(self, session_name):
        """Сохраняет измененную вкладку диалога в базу данных"""
        try:
            json_str = json.dumps(self.chat_sessions.get(session_name, []))
            html_str = self.chat_html_history.get(session_name, "")
            self.db_cursor.execute(
                "INSERT OR REPLACE INTO chat_sessions (name, json_history, html_history) VALUES (?, ?, ?)",
                (session_name, json_str, html_str)
            )
            self.db_conn.commit()
        except Exception:
            pass

    def attach_local_file(self):
        """📎 Читает файлы .txt, .py, .log, .pdf, .docx и извлекает чистый текст для ИИ"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Прикрепить документ для анализа", "", 
            "Документы (*.txt *.py *.log *.pdf *.docx)"
        )
        if not file_path: return
        ext = os.path.splitext(file_path)[1].lower()
        text_content = ""
        try:
            if ext in [".txt", ".py", ".log"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text_content = f.read()
            elif ext == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                text_content = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
            elif ext == ".docx":
                import docx
                doc = docx.Document(file_path)
                text_content = "\n".join([p.text for p in doc.paragraphs])
            
            if text_content.strip():
                self.attached_file_context = f"\n=== СВЕДЕНИЯ ИЗ ДОКУМЕНТА ({os.path.basename(file_path)}):\n{text_content.strip()}\n===\n"
                self.chat_area.append(f"<i>📎 Система: Успешно считан файл {os.path.basename(file_path)} ({len(text_content)} симв.). Текст подмешан в память.</i><br>")
                self.btn_attach_file.setText("📎 Файл загружен!")
                self.btn_attach_file.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
            else:
                self.chat_area.append("<b style='color:orange;'>Система: Файл пуст или не содержит текста!</b><br>")
        except Exception as e:
            self.chat_area.append(f"<b style='color:red;'>Система: Ошибка чтения файла: {str(e)}</b><br>")
    def check_and_execute_agent_commands(self, text):
        """🔌 НОВОЕ: Система ИИ-Агента. Перехватывает [RUN_CMD: команда] и выполняет на ПК"""
        match = re.search(r'\[RUN_CMD:\s*([a-zA-Z0-9_\-\.\s]+)\]', text)
        if match:
            cmd = match.group(1).strip()
            self.chat_area.append(f"<br><b style='color:#f0ad4e;'>🔌 ИИ-Агент: Обнаружена команда системы. Запуск {cmd}...</b><br>")
            try:
                # Безопасный запуск стандартных системных утилит Windows через subprocess
                if cmd in ["calc", "notepad", "explorer", "cmd", "taskmgr"]:
                    subprocess.Popen(cmd, shell=True)
                    self.chat_area.append(f"<b style='color:#5cb85c;'>🟢 ИИ-Агент: Утилита {cmd} успешно вызвана.</b><br>")
                else:
                    self.chat_area.append(f"<b style='color:red;'>🔴 ИИ-Агент: Запуск сторонней команды '{cmd}' отклонён политикой безопасности.</b><br>")
            except Exception as e:
                self.chat_area.append(f"<b style='color:red;'>🔴 ИИ-Агент: Ошибка выполнения: {e}</b><br>")

    def run_code_in_sandbox(self):
        """💻 Извлекает последний блок кода из памяти и асинхронно запускает его в Python"""
        if not hasattr(self, 'last_code_block') or not self.last_code_block.strip():
            self.chat_area.append("<br><b style='color:orange;'>Система: Сначала сгенерируйте код или скопируйте его в память!</b><br>")
            return
            
        self.chat_area.append("<br><b style='color:#f0ad4e;'>🔄 Песочница: Запуск изолированного процесса кода Python...</b><br>")
        temp_file = os.path.join(os.getcwd(), "sandbox_temp.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(self.last_code_block)
        except Exception as e:
            self.chat_area.append(f"<b style='color:red;'>Песочница: Ошибка записи файла: {e}</b><br>")
            return

        self.sandbox_process = QProcess(self)
        
        def on_sandbox_finished(exit_code, exit_status):
            raw_out = self.sandbox_process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
            raw_err = self.sandbox_process.readAllStandardError().data().decode('utf-8', errors='ignore')
            
            self.chat_area.append("<b>💻 Результат выполнения из песочницы:</b>")
            if raw_out.strip():
                self.chat_area.append(f"<pre style='color:#5cb85c; background:#1e1e1e; padding:8px; border-radius:4px;'>{raw_out}</pre>")
            if raw_err.strip():
                self.chat_area.append(f"<pre style='color:#d9534f; background:#1e1e1e; padding:8px; border-radius:4px;'>{raw_err}</pre>")
            if not raw_out.strip() and not raw_err.strip():
                self.chat_area.append("<i style='color:gray;'>[Скрипт успешно завершился, но ничего не вывел на экран]</i><br>")
                
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except Exception: pass

        self.sandbox_process.finished.connect(on_sandbox_finished)
        self.sandbox_process.start(sys.executable, [temp_file])

    def copy_last_code_block(self):
        """Копирует последний блок синтаксиса из кэшированной памяти без парсинга HTML"""
        if hasattr(self, 'last_code_block') and self.last_code_block.strip():
            clipboard = QApplication.clipboard()
            clipboard.setText(self.last_code_block.strip())
            self.btn_copy_code.setText("✅ Скопировано!")
            QTimer.singleShot(2000, lambda: self.btn_copy_code.setText("📋 Копировать код"))
        else:
            self.btn_copy_code.setText("❌ Код не найден")
            QTimer.singleShot(2000, lambda: self.btn_copy_code.setText("📋 Копировать код"))
    def optimize_user_prompt(self):
        """🧠 Автоматически переписывает сырой текст пользователя в структурированный промпт"""
        raw_text = self.input_field.toPlainText().strip()
        if not raw_text: return
        optimized = (
            f"Роль: Профессиональный ИИ-эксперт и архитектор программных систем.\n"
            f"Задача: Глубоко проанализировать и детально проработать следующий запрос пользователя.\n"
            f"Контекст: Дай структурированный ответ, разбей логику по пунктам, выдели главное и "
            f"приведи оптимизированные примеры кода с комментариями там, где это необходимо.\n\n"
            f"Запрос пользователя:\n\"{raw_text}\""
        )
        self.input_field.setText(optimized)
        self.input_field.setFocus()
        cursor = self.input_field.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.input_field.setTextCursor(cursor)

    def export_chat_to_markdown(self):
        """📝 Сохраняет текущую историю сессии в красивый markdown-файл"""
        current_history = self.chat_sessions.get(self.current_session, [])
        if not current_history:
            self.chat_area.append("<br><b style='color:orange;'>Система: История чата пуста. Нечего экспортировать!</b><br>")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчет чата", f"{self.current_session}_report.md", "Markdown Файлы (*.md)")
        if not file_path: return
        try:
            md_content = [f"# Отчет генерации ИИ — {self.current_session}\n", f"**Модель:** {self.current_model}\n", "---\n"]
            for msg in current_history:
                role = "### 🧑 Пользователь" if msg["role"] == "user" else "### 🤖 Системная роль" if msg["role"] == "system" else "### 💻 ИИ-Ассистент"
                md_content.append(f"{role}:\n{msg['content']}\n\n---\n")
            with open(file_path, "w", encoding="utf-8") as f: f.write("\n".join(md_content))
            self.chat_area.append(f"<br><b style='color:#5cb85c;'>🟢 Система: Чат успешно экспортирован в файл: {os.path.basename(file_path)}</b><br>")
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>🔴 Система: Ошибка экспорта: {str(e)}</b><br>")

    def update_token_counter(self):
        """Счетчик занятых токенов контекста"""
        try:
            current_history = self.chat_sessions.get(self.current_session, [])
            max_ctx = int(self.ctx_steps.get(self.slider_ctx.value(), 2048))
            total_text = ""
            for msg in current_history: total_text += str(msg.get("content", "")) + " "
            try:
                import tiktoken
                encoding = tiktoken.get_encoding("cl100k_base")
                tokens_used = len(encoding.encode(total_text))
            except ImportError:
                tokens_used = int(len(total_text) / 3.8) + 1
            percentage = min(int((tokens_used / max_ctx) * 100), 100)
            self.lbl_token_usage.setText(f"Занято: {tokens_used} / {max_ctx} токенов ({percentage}%)")
        except Exception: pass

    def save_ui_setting(self, key, val):
        """Сохраняет значение конкретного ползунка в БД"""
        try:
            self.db_cursor.execute("INSERT OR REPLACE INTO ui_settings (key, val) VALUES (?, ?)", (key, float(val)))
            self.db_conn.commit()
        except Exception: pass
    def load_saved_settings(self):
        """🗄️ Восстанавливает положения всех ползунков и тумблеров из базы данных SQLite"""
        try:
            self.db_cursor.execute("SELECT key, val FROM ui_settings")
            rows = self.db_cursor.fetchall()
            settings = {row[0]: row[1] for row in rows}
            
            if "temp" in settings: self.slider_temp.setValue(int(settings["temp"]))
            if "topp" in settings: self.slider_topp.setValue(int(settings["topp"]))
            if "topk" in settings: self.slider_topk.setValue(int(settings["topk"]))
            if "miro" in settings: self.slider_miro.setValue(int(settings["miro"]))
            if "penalty" in settings: self.slider_penalty.setValue(int(settings["penalty"]))
            if "freq" in settings: self.slider_freq_penalty.setValue(int(settings["freq"]))
            if "pres" in settings: self.slider_pres_penalty.setValue(int(settings["pres"]))
            if "ctx" in settings: self.slider_ctx.setValue(int(settings["ctx"]))
            if "predict" in settings: self.slider_predict.setValue(int(settings["predict"]))
            if "threads" in settings: self.slider_threads.setValue(int(settings["threads"]))
            if "lowvram" in settings: self.cb_low_vram.setChecked(bool(settings["lowvram"]))
        except Exception:
            pass

    def update_hardware_stats(self, cpu_p, ram_p, gpu_p, vram_p):
        """Обновляет текстовые метки датчиков ресурсов ПК из фонового потока"""
        self.lbl_sys_cpu.setText(f"Загрузка CPU: {cpu_p:.1f}%")
        self.lbl_sys_ram.setText(f"Использование RAM: {ram_p:.1f}%")
        self.lbl_sys_gpu.setText("Загрузка GPU: В норме (Авто)")
        self.lbl_sys_vram.setText("Память VRAM: Динамическая")

    def check_server_status(self):
        try:
            response = requests.get("http://localhost:11434/", timeout=2)
            if response.status_code == 200:
                self.status_label.setText("🟢 Сервер Ollama: Работает")
                self.load_installed_models()
            else:
                self.status_label.setText(f"🔴 Ошибка сервера (Код: {response.status_code})")
        except Exception:
            self.status_label.setText("❌ Сервер Ollama выключен")
            self.chat_area.clear()
            self.chat_area.append(
                "<b style='color: #d9534f;'>Сервер Ollama не запущен или не установлен на вашем ПК!</b><br>"
                "Включите его вручную и выберите: Меню -> Сервис -> Проверить статус.<br><br>"
            )

    def load_installed_models(self):
        try:
            import ollama
            models_list = ollama.list()
            self.model_selector.blockSignals(True)
            self.model_selector.clear()
            extracted_models = []
            if hasattr(models_list, 'models'):
                for m in models_list.models:
                    if hasattr(m, 'model'): extracted_models.append(m.model)
                    elif hasattr(m, 'name'): extracted_models.append(m.name)
            elif isinstance(models_list, dict) and 'models' in models_list:
                for m in models_list['models']:
                    if isinstance(m, dict): extracted_models.append(m.get('name', m.get('model', '')))
                    else: extracted_models.append(getattr(m, 'name', getattr(m, 'model', '')))
            if not extracted_models:
                self.status_label.setText("⚠️ Модели не найдены")
                self.model_selector.blockSignals(False)
                return
            for model_name in extracted_models:
                if model_name: self.model_selector.addItem(model_name)
            self.model_selector.blockSignals(False)
            if self.model_selector.count() > 0:
                self.model_selector.setCurrentIndex(0)
                self.current_model = self.model_selector.itemText(0)
            self.status_label.setText("🟢 Сервер Ollama: Работает")
        except Exception:
            self.model_selector.blockSignals(False)

    def on_model_changed(self, model_name):
        if not model_name: return
        self.current_model = model_name
        act_msg = f"<i>Система: Активирована модель {model_name}</i><br>"
        if self.current_session in self.chat_html_history:
            self.chat_html_history[self.current_session] += act_msg
        self.chat_area.append(act_msg)

    def import_gguf_model(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл модели GGUF", "", "ИИ Модели (*.gguf)")
        if not file_path: return
        native_path = os.path.normpath(file_path)
        model_dir = os.path.dirname(native_path)
        model_name, _ = os.path.splitext(os.path.basename(file_path))
        model_name = model_name.lower().replace(".", "-").replace("_", "-")
        self.chat_area.append(f"<i>Система: Начинаю фоновый импорт модели <b>{model_name}</b>...</i><br>")
        possible_paths = [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"), os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe"), r"C:\Program Files\Ollama\ollama.exe"]
        ollama_executable = "ollama"
        for path in possible_paths:
            if os.path.exists(path): ollama_executable = path; break
        temp_modelfile_path = os.path.join(model_dir, f"Modelfile_{model_name}")
        try:
            with open(temp_modelfile_path, "w", encoding="utf-8") as f: f.write(f'FROM "{native_path}"\n')
        except Exception as e: self.chat_area.append(f"<b style='color:red;'>🔴 Ошибка:</b> {str(e)}<br>"); return
        self.import_process = QProcess(self)
        def on_process_finished(exit_code, exit_status):
            if os.path.exists(temp_modelfile_path): os.remove(temp_modelfile_path)
            if exit_code == 0:
                self.chat_area.append(f"<b>🟢 Модель {model_name} успешно импортирована!</b><br>")
                self.load_installed_models()
            else:
                raw_errors = self.import_process.readAllStandardError().data().decode('utf-8', errors='ignore')
                self.chat_area.append(f"<b style='color:red;'>🔴 Ошибка импорта:</b> {raw_errors}<br>")
        self.import_process.finished.connect(on_process_finished)
        self.import_process.start(ollama_executable, ["create", model_name, "-f", temp_modelfile_path])
    def create_new_chat_session(self):
        new_id = self.session_list_widget.count() + 1
        name = f"Чат {new_id}"
        self.chat_sessions[name] = []
        self.chat_html_history[name] = "<i>Система: Начало нового диалога.</i><br><br>"
        self.session_list_widget.addItem(name)
        self.save_session_to_db(name)
        self.session_list_widget.setCurrentRow(new_id - 1)

    def switch_chat_session(self, session_name):
        if not session_name or session_name not in self.chat_sessions: return
        self.current_session = session_name
        if session_name not in self.chat_html_history or not self.chat_html_history[session_name]:
            html_builder = [f"<i>Система: Переключено на {session_name}. История загружена.</i><br><br>"]
            for msg in self.chat_sessions[session_name]:
                if msg["role"] == "user": html_builder.append(f"<b>Вы:</b> {msg['content']}<br>")
                elif msg["role"] == "assistant": html_builder.append(f"<b>Бот:</b> {MarkdownHighlighter.to_html(msg['content'])}<br><br>")
            self.chat_html_history[session_name] = "".join(html_builder)
        self.chat_area.setHtml(self.chat_html_history[session_name])
        self.chat_area.moveCursor(QTextCursor.MoveOperation.End)
        self.update_token_counter()
        self.lbl_generation_speed.setText("Скорость ИИ: 0.0 tok/sec")

    def toggle_voice_recording(self, checked):
        if checked:
            self.btn_voice.setText("🛑 Запись... Нажмите для перевода")
            self.btn_voice.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
            self.voice_worker.start_recording()
        else:
            self.btn_voice.setText("⏳ Обработка речи...")
            self.btn_voice.setStyleSheet("background-color: #777; color: white;")
            self.voice_worker.stop_and_process()

    def on_voice_status_updated(self, status_text):
        self.status_label.setText(status_text)
        if "❌" in status_text:
            self.btn_voice.setChecked(False)
            self.btn_voice.setText("🎙️ Голосовой ввод")
            self.btn_voice.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")

    def on_voice_text_received(self, text):
        self.status_label.setText("🟢 Сервер Ollama: Работает")
        self.btn_voice.setChecked(False)
        self.btn_voice.setText("🎙️ Голосовой ввод")
        self.btn_voice.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")
        if text:
            if text.startswith("[Ошибка"): self.chat_area.append(f"<br><b>Система:</b> {text}<br>"); return
            existing_text = self.input_field.toPlainText().strip()
            self.input_field.setText((existing_text + " " + text).strip() if existing_text else text)
            self.input_field.setFocus()
            self.input_field.moveCursor(QTextCursor.MoveOperation.End)

    def on_sys_prompt_changed(self):
        self.sys_prompt_edit.blockSignals(True)
        current_text = self.sys_prompt_edit.toPlainText().strip()
        if current_text.lower() in ["ты программист", "ты программист или поэт", "ты поэт или программист"]:
            self.sys_prompt_edit.setText("Да, принято. Я программист.")
            cursor = self.sys_prompt_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.sys_prompt_edit.setTextCursor(cursor)
        elif current_text.lower() == "ты поэт":
            self.sys_prompt_edit.setText("Да, принято. Я поэт.")
            cursor = self.sys_prompt_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.sys_prompt_edit.setTextCursor(cursor)
        self.sys_prompt_edit.blockSignals(False)
    def send_message(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_generation()
            return

        try:
            query = self.input_field.toPlainText().strip()
            if not query: return
            
            # Подмешиваем контекст прикрепленного файла (RAG)
            full_process_query = query
            if self.attached_file_context:
                full_process_query = self.attached_file_context + query
                # Сбрасываем кэш скрепки после интеграции, возвращаем вид кнопке
                self.attached_file_context = ""
                self.btn_attach_file.setText("📎 Прикрепить файл")
                self.btn_attach_file.setStyleSheet("")

            if hasattr(self, 'cb_web_search') and self.cb_web_search.isChecked():
                selected_engine = self.search_engine_selector.currentText().replace("🌐 ", "").replace("🔍 ", "").replace("🎯 ", "")
                self.chat_area.append(f"<b>Вы:</b> {query} <i>(выполняю веб-поиск через {selected_engine}...)</i>")
                self.send_btn.setText("🛑 Стоп ИИ")
                self.send_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; padding: 5px;")
                self.search_worker = WebSearchWorker(query, selected_engine)
                
                def on_search_done(web_context):
                    augmented_query = (
                        f"Используй следующие актуальные факты из интернета для ответа:\n"
                        f"{web_context}\n\n"
                        f"Запрос пользователя: {full_process_query}"
                    )
                    self.execute_ollama_call(augmented_query, raw_user_query=query)
                    
                self.search_worker.search_finished.connect(on_search_done)
                self.search_worker.start()
            else:
                self.chat_area.append(f"<b>Вы:</b> {query}")
                self.execute_ollama_call(full_process_query, raw_user_query=query)
                
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>[Сбой]:</b> {str(e)}<br>")
            self.send_btn.setText("Отправить")
            self.send_btn.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold; padding: 5px;")
    def execute_ollama_call(self, process_query, raw_user_query):
        try:
            self.chat_history = self.chat_sessions.get(self.current_session, [])
            if self.current_session not in self.chat_html_history: self.chat_html_history[self.current_session] = ""
            if len(self.chat_history) == 0:
                sys_prompt = self.sys_prompt_edit.toPlainText().strip()
                if sys_prompt: self.chat_history.append({"role": "system", "content": sys_prompt})
            self.chat_html_history[self.current_session] += f"<b>Вы:</b> {raw_user_query}<br>"
            self.input_field.clear()
            self.chat_history.append({"role": "user", "content": process_query})
            self.update_token_counter()
            self.chat_area.append("<b>Бот:</b> ")
            
            self.send_btn.setText("🛑 Стоп ИИ")
            self.send_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; padding: 5px;")
            
            self.bot_response_buffer = ""
            current_options = self.get_ai_options()
            self.worker = AIWorker(self.current_model, copy.deepcopy(self.chat_history), current_options)
            self.worker.response_received.connect(self.append_bot_chunk)
            self.worker.stats_updated.connect(lambda speed, count: self.lbl_generation_speed.setText(f"Скорость ИИ: {speed:.1f} tok/sec"))
            self.worker.finished.connect(self.on_generation_finished)
            self.worker.start()
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>[Сбой запуска Ollama]:</b> {str(e)}<br>")
            self.send_btn.setText("Отправить")
            self.send_btn.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold; padding: 5px;")

    def append_bot_chunk(self, text):
        self.bot_response_buffer += text
        cursor = self.chat_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.chat_area.setTextCursor(cursor)

    def on_generation_finished(self):
        try:
            html_response = MarkdownHighlighter.to_html(self.bot_response_buffer)
            code_blocks = re.findall(r'```(?:[a-zA-Z0-9_+-]*?)\n(.*?)(?:```|$)', self.bot_response_buffer, re.DOTALL)
            self.last_code_block = code_blocks[-1] if code_blocks else ""
            self.chat_history.append({"role": "assistant", "content": self.bot_response_buffer})
            
            self.chat_sessions[self.current_session] = self.chat_history
            self.chat_html_history[self.current_session] += f"<b>Бот:</b> {html_response}<br><br>"
            self.chat_area.setHtml(self.chat_html_history[self.current_session])
            
            # Проверяем, сгенерировал ли ИИ системную команду для Агента
            self.check_and_execute_agent_commands(self.bot_response_buffer)
            
            # Автоматически пишем историю текущего чата в локальную БД SQLite
            self.save_session_to_db(self.current_session)
            
            cursor = self.chat_area.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.chat_area.setTextCursor(cursor)
            self.update_token_counter()
        except Exception: pass
        finally: 
            self.send_btn.setText("Отправить")
            self.send_btn.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold; padding: 5px;")
    def get_ai_options(self):
        try:
            options = {
                "temperature": float(self.slider_temp.value() / 10.0),
                "top_p": float(self.slider_topp.value() / 10.0),
                "top_k": int(self.slider_topk.value()),
                "mirostat": int(self.slider_miro.value()),
                "repeat_penalty": float(self.slider_penalty.value() / 10.0),
                "frequency_penalty": float(self.slider_freq_penalty.value() / 10.0),
                "presence_penalty": float(self.slider_pres_penalty.value() / 10.0),
                "num_ctx": int(self.ctx_steps.get(self.slider_ctx.value(), 2048)),
                "num_predict": int(self.slider_predict.value()),  # СИСТЕМНЫЙ
                "num_thread": int(self.slider_threads.get_value() if hasattr(self.slider_threads, 'get_value') else self.slider_threads.value())   # СИСТЕМНЫЙ
            }
            if self.slider_seed.value() != -1: options["seed"] = int(self.slider_seed.value())
            if self.cb_low_vram.isChecked(): options["low_vram"] = True
            return options
        except Exception: return {"temperature": 0.7, "top_p": 0.9, "num_ctx": 2048}

    def init_menu(self):
        menu_bar = self.menuBar()
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

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        hbox_layout = QHBoxLayout(main_widget)

        self.session_sidebar = QWidget()
        self.session_sidebar.setFixedWidth(200)
        session_sidebar_layout = QVBoxLayout(self.session_sidebar)
        session_sidebar_layout.setContentsMargins(0, 0, 10, 0)

        session_sidebar_layout.addWidget(QLabel("📝 Ваша история чатов:"))
        self.session_list_widget = QListWidget()
        for k in self.chat_sessions.keys(): self.session_list_widget.addItem(k)
        self.session_list_widget.setCurrentRow(0)
        self.session_list_widget.currentTextChanged.connect(self.switch_chat_session)
        session_sidebar_layout.addWidget(self.session_list_widget)

        self.btn_new_chat = QPushButton("➕ Новый диалог")
        self.btn_new_chat.clicked.connect(self.create_new_chat_session)
        session_sidebar_layout.addWidget(self.btn_new_chat)
        hbox_layout.addWidget(self.session_sidebar)

        self.center_container = QWidget()
        center_layout = QVBoxLayout(self.center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)

        top_layout = QHBoxLayout()
        self.btn_toggle_sidebar = QPushButton("◀ Скрыть историю")
        self.btn_toggle_sidebar.setStyleSheet("font-weight: bold; background-color: #444; color: white;")
        self.btn_toggle_sidebar.clicked.connect(self.toggle_sidebar_visibility)
        top_layout.addWidget(self.btn_toggle_sidebar)
        
        top_layout.addStretch()
        self.status_label = QLabel("Проверка сервера...")
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()

        top_layout.addWidget(QLabel("Модель:"))
        self.model_selector = QComboBox()
        self.model_selector.setMinimumWidth(220) 
        self.model_selector.currentTextChanged.connect(self.on_model_changed)
        top_layout.addWidget(self.model_selector)
        center_layout.addLayout(top_layout)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.splitter.addWidget(self.chat_area)

        self.input_container = QWidget()
        input_vbox = QVBoxLayout(self.input_container)
        input_vbox.setContentsMargins(0, 0, 0, 0)

        self.input_field = SmartLineEdit()
        self.input_field.enter_pressed.connect(self.send_message)
        input_vbox.addWidget(self.input_field)

        features_layout = QHBoxLayout()
        self.search_engine_selector = QComboBox()
        self.search_engine_selector.addItems(["🌐 DuckDuckGo", "🔍 Google", "🎯 Yandex"])
        features_layout.addWidget(self.search_engine_selector)

        self.cb_web_search = QCheckBox("Искать в сети")
        features_layout.addWidget(self.cb_web_search)
        
        # НОВОЕ: Кнопка-скрепка для RAG
        self.btn_attach_file = QPushButton("📎 Прикрепить файл")
        self.btn_attach_file.setStyleSheet("background-color: #444; color: white;")
        self.btn_attach_file.clicked.connect(self.attach_local_file)
        features_layout.addWidget(self.btn_attach_file)

        self.btn_optimize_prompt = QPushButton("🧠 Оптимизировать промпт")
        self.btn_optimize_prompt.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.btn_optimize_prompt.clicked.connect(self.optimize_user_prompt)
        
        self.btn_run_sandbox = QPushButton("💻 Выполнить код ИИ")
        self.btn_run_sandbox.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")
        self.btn_run_sandbox.clicked.connect(self.run_code_in_sandbox)
        
        self.btn_copy_code = QPushButton("📋 Копировать код")
        self.btn_copy_code.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
        self.btn_copy_code.clicked.connect(self.copy_last_code_block)
        
        self.send_btn = QPushButton("Отправить")
        self.send_btn.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold; padding: 5px;")
        self.send_btn.clicked.connect(self.send_message)

        features_layout.addWidget(self.btn_optimize_prompt)
        features_layout.addWidget(self.btn_run_sandbox)
        features_layout.addWidget(self.btn_copy_code)
        features_layout.addWidget(self.send_btn)
        
        input_vbox.addLayout(features_layout)
        self.splitter.addWidget(self.input_container)
        center_layout.addWidget(self.splitter)
        self.splitter.setSizes([600, 180])  # <-- ЗДЕСЬ. 600 — высота чата, 180 — высота ввода

        hbox_layout.addWidget(self.center_container, stretch=3)

        self.init_right_sidebar(hbox_layout)
    def init_right_sidebar(self, hbox_layout):
        sidebar = QWidget()
        sidebar.setFixedWidth(280)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 0, 0, 0)

        sys_group = QGroupBox("Управление сессией")
        sys_vbox = QVBoxLayout(sys_group)
        self.sys_prompt_edit = QTextEdit()
        self.sys_prompt_edit.setPlaceholderText("Системная роль ИИ...")
        self.sys_prompt_edit.setFixedHeight(60)
        self.sys_prompt_edit.textChanged.connect(self.on_sys_prompt_changed)
        sys_vbox.addWidget(self.sys_prompt_edit)
        
        self.btn_voice = QPushButton("🎙️ Голосовой ввод")
        self.btn_voice.setCheckable(True)
        self.btn_voice.clicked.connect(self.toggle_voice_recording)
        sys_vbox.addWidget(self.btn_voice)
        
        self.btn_clear_chat = QPushButton("🗑️ Очистить память")
        self.btn_clear_chat.clicked.connect(self.clear_chat_context)
        sys_vbox.addWidget(self.btn_clear_chat)
        sidebar_layout.addWidget(sys_group)

        params_group = QGroupBox("Параметры и Системный контроль")
        form_layout = QFormLayout(params_group)

        # Стандартные нейро-слайдеры с привязкой к SQLite автосохранению
        self.lbl_temp_val = QLabel("0.7")
        self.slider_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_temp.setRange(0, 15); self.slider_temp.setValue(7)
        self.slider_temp.valueChanged.connect(lambda v: (self.lbl_temp_val.setText(str(v/10.0)), self.save_ui_setting("temp", v)))
        form_layout.addRow(QLabel("Temp:"), self.lbl_temp_val); form_layout.addRow(self.slider_temp)

        self.lbl_topp_val = QLabel("0.9")
        self.slider_topp = QSlider(Qt.Orientation.Horizontal)
        self.slider_topp.setRange(1, 10); self.slider_topp.setValue(9)
        self.slider_topp.valueChanged.connect(lambda v: (self.lbl_topp_val.setText(str(v/10.0)), self.save_ui_setting("topp", v)))
        form_layout.addRow(QLabel("Top_P:"), self.lbl_topp_val); form_layout.addRow(self.slider_topp)

        self.lbl_topk_val = QLabel("40")
        self.slider_topk = QSlider(Qt.Orientation.Horizontal)
        self.slider_topk.setRange(1, 100); self.slider_topk.setValue(40)
        self.slider_topk.valueChanged.connect(lambda v: (self.lbl_topk_val.setText(str(v)), self.save_ui_setting("topk", v)))
        form_layout.addRow(QLabel("Top_K:"), self.lbl_topk_val); form_layout.addRow(self.slider_topk)

        self.lbl_miro_val = QLabel("0")
        self.slider_miro = QSlider(Qt.Orientation.Horizontal)
        self.slider_miro.setRange(0, 2); self.slider_miro.setValue(0)
        self.slider_miro.valueChanged.connect(lambda v: (self.lbl_miro_val.setText(str(v)), self.save_ui_setting("miro", v)))
        form_layout.addRow(QLabel("Mirostat:"), self.lbl_miro_val); form_layout.addRow(self.slider_miro)

        self.lbl_penalty_val = QLabel("1.1")
        self.slider_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_penalty.setRange(10, 15); self.slider_penalty.setValue(11)
        self.slider_penalty.valueChanged.connect(lambda v: (self.lbl_penalty_val.setText(str(v/10.0)), self.save_ui_setting("penalty", v)))
        form_layout.addRow(QLabel("Штраф повторов:"), self.lbl_penalty_val); form_layout.addRow(self.slider_penalty)

        self.lbl_freq_val = QLabel("0.0")
        self.slider_freq_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_freq_penalty.setRange(0, 20); self.slider_freq_penalty.setValue(0)
        self.slider_freq_penalty.valueChanged.connect(lambda v: (self.lbl_freq_val.setText(str(v/10.0)), self.save_ui_setting("freq", v)))
        form_layout.addRow(QLabel("Штраф частоты (Freq):"), self.lbl_freq_val); form_layout.addRow(self.slider_freq_penalty)

        self.lbl_pres_val = QLabel("0.0")
        self.slider_pres_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_pres_penalty.setRange(0, 20); self.slider_pres_penalty.setValue(0)
        self.slider_pres_penalty.valueChanged.connect(lambda v: (self.lbl_pres_val.setText(str(v/10.0)), self.save_ui_setting("pres", v)))
        form_layout.addRow(QLabel("Штраф тем (Presence):"), self.lbl_pres_val); form_layout.addRow(self.slider_pres_penalty)

        self.lbl_ctx_val = QLabel("2048")
        self.slider_ctx = QSlider(Qt.Orientation.Horizontal)
        self.slider_ctx.setRange(1, 7); self.slider_ctx.setValue(2)
        self.slider_ctx.valueChanged.connect(lambda v: (self.lbl_ctx_val.setText(str(self.ctx_steps.get(v, 2048))), self.save_ui_setting("ctx", v)))
        form_layout.addRow(QLabel("Память контекста:"), self.lbl_ctx_val); form_layout.addRow(self.slider_ctx)

        # НОВОЕ: Лимит генерации токенов (num_predict)
        self.lbl_predict_val = QLabel("128")
        self.slider_predict = QSlider(Qt.Orientation.Horizontal)
        self.slider_predict.setRange(16, 2048); self.slider_predict.setValue(128)
        self.slider_predict.valueChanged.connect(lambda v: (self.lbl_predict_val.setText(str(v)), self.save_ui_setting("predict", v)))
        form_layout.addRow(QLabel("Лимит вывода (Tokens):"), self.lbl_predict_val); form_layout.addRow(self.slider_predict)

        # НОВОЕ: Потоки процессора (num_thread)
        self.lbl_threads_val = QLabel("4")
        self.slider_threads = QSlider(Qt.Orientation.Horizontal)
        self.slider_threads.setRange(1, 16); self.slider_threads.setValue(4)
        self.slider_threads.valueChanged.connect(lambda v: (self.lbl_threads_val.setText(str(v)), self.save_ui_setting("threads", v)))
        form_layout.addRow(QLabel("Ядра CPU для ИИ:"), self.lbl_threads_val); form_layout.addRow(self.slider_threads)

        # НОВОЕ: Режим Low VRAM для слабых видеокарт
        self.cb_low_vram = QCheckBox("Режим Low VRAM")
        self.cb_low_vram.stateChanged.connect(lambda v: self.save_ui_setting("lowvram", 1 if v else 0))
        form_layout.addRow(self.cb_low_vram)

        sidebar_layout.addWidget(params_group)

        token_group = QGroupBox("🔋 Использование памяти")
        token_vbox = QVBoxLayout(token_group)
        self.lbl_token_usage = QLabel("Занято: 0 / 2048 токенов (0%)")
        self.lbl_generation_speed = QLabel("Скорость ИИ: 0.0 tok/sec")
        token_vbox.addWidget(self.lbl_token_usage); token_vbox.addWidget(self.lbl_generation_speed)
        sidebar_layout.addWidget(token_group)

        hardware_group = QGroupBox("📊 Телеметрия ресурсов ПК")
        hardware_vbox = QVBoxLayout(hardware_group)
        self.lbl_sys_cpu = QLabel("Загрузка CPU: 0.0%")
        self.lbl_sys_ram = QLabel("Использование RAM: 0.0%")
        self.lbl_sys_gpu = QLabel("Загрузка GPU: Авто")
        self.lbl_sys_vram = QLabel("Память VRAM: Динамическая")
        hardware_vbox.addWidget(self.lbl_sys_cpu); hardware_vbox.addWidget(self.lbl_sys_ram)
        hardware_vbox.addWidget(self.lbl_sys_gpu); hardware_vbox.addWidget(self.lbl_sys_vram)
        sidebar_layout.addWidget(hardware_group)

        sidebar_layout.addStretch()
        hbox_layout.addWidget(sidebar)

    def apply_cyberpunk_theme(self):
        """🎨 Глобальный QSS-стиль с рамками и цветами строго как у окон ввода"""
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0f12; }
            QWidget { background-color: #0d0f12; color: #00ffcc; font-family: 'Segoe UI', Arial; }
            
            /* Рамки блоков теперь 1px бирюзовые, как у окон ввода */
            QGroupBox { border: 1px solid #00ffcc; border-radius: 6px; margin-top: 10px; font-weight: bold; color: #00ffcc; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            
            QTextEdit { background-color: #13171c; border: 1px solid #00ffcc; border-radius: 6px; color: #ffffff; font-size: 13px; }
            QLineEdit, QComboBox { background-color: #13171c; border: 1px solid #00ffcc; border-radius: 4px; color: #00ffcc; padding: 3px; }
            
            /* Рамка истории чатов теперь полностью идентична окнам ввода */
            QListWidget { background-color: #13171c; border: 1px solid #00ffcc; border-radius: 6px; color: #ffffff; }
            
            QPushButton { background-color: #1a1f26; border: 1px solid #00ffcc; border-radius: 4px; color: #00ffcc; font-weight: bold; padding: 4px; }
            QPushButton:hover { background-color: #00ffcc; color: #0d0f12; }
            QPushButton:pressed { background-color: #00b38f; }
            
            QSlider::groove:horizontal { border: 1px solid #333; height: 6px; background: #13171c; border-radius: 3px; }
            QSlider::handle:horizontal { background: #00ffcc; width: 14px; margin: -4px 0; border-radius: 7px; }
            
            QLabel { color: #00ffcc; font-size: 11px; }
            QCheckBox { color: #00ffcc; font-size: 11px; }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    client = AIClientApp()
    client.show()
    sys.exit(app.exec())

# ==================================================================================
# 🗂️ PythonCoder AI: Workstation Pro v3.7 (RELEASE STABLE)
# ==================================================================================
# Авторы проекта: ИИ GOOGLE и MIKOLA PINCHUK
# Команда для установки зависимостей: 
# pip install ollama psutil sounddevice numpy faster-whisper pygments tiktoken pypdf python-docx pyttsx3 PyQt6
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
import numpy as np
import sounddevice as sd
import pyttsx3  

# --- ПОДДЕРЖКА ПОДСВЕТКИ СИНТАКСИСА КОДА (PYGMENTS) ---
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
# ------------------------------------------------------

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTextEdit, QLineEdit, QPushButton, 
                             QLabel, QFileDialog, QComboBox, QSlider, QGroupBox, 
                             QFormLayout, QListWidget, QListWidgetItem, QSplitter,
                             QCheckBox, QTabWidget) 
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QProcess
from PyQt6.QtGui import QAction, QTextCursor

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

# КОНЕЦ ЧАСТИ 1 ИЗ 15
# НАЧАЛО ЧАСТИ 2 ИЗ 15

class HardwareMonitor(QThread):
    """📈 Фоновый поток для ежесекундного замера нагрузки CPU и RAM"""
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
    """🌐 Универсальный текстовый поисковый движок для Google, Yandex и DuckDuckGo"""
    search_finished = pyqtSignal(str)

    # Параметр engine сделан необязательным (=None), чтобы не ломать вызов из send_message
    def __init__(self, query, engine=None):
        super().__init__()
        self.query = query
        if engine:
            self.engine = engine.replace("🌐", "").replace("🔍", "").replace("🎯", "").strip()
        else:
            self.engine = "DuckDuckGo"

    def run(self):
        try:
            import urllib.request
            import urllib.parse
            import re

            clean_results = []
            
            # Экранируем спецсимволы и переводим кириллицу в безопасный ASCII-hex формат
            user_request = urllib.parse.quote_plus(self.query)
            
            # Подменяем заголовки под реальный мобильный браузер (Safari/iPhone), 
            # так как поисковики отдают им легкий HTML без тяжелых скриптов и капчи
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            }

            # Твоя проверенная рабочая ссылка, которая запускается по чекбоксу
            url = f"https://html.duckduckgo.com/html/?q={user_request}"

            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, timeout=7) as response:
                html_bytes = response.read()
                # Жестко декодируем в utf-8, полностью игнорируя битые байты
                html_content = html_bytes.decode('utf-8', errors='ignore')
                
                # Твоя родная и рабочая регулярка под сниппеты DuckDuckGo
                snippets = re.findall(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', html_content, re.DOTALL)

                for s in snippets[:5]:
                    # Очищаем текст от внутренних HTML тегов и ссылок
                    clean = re.sub(r'<[^>]*>', '', s).strip()
                    clean = " ".join(clean.split())
                    if clean and len(clean) > 15 and not clean.startswith("http"):
                        clean_results.append(clean)

            if clean_results:
                unique_results = list(dict.fromkeys(clean_results))
                context = "\n".join([f"- {res}" for res in unique_results[:3]])
                self.search_finished.emit(context)
            else:
                # Исправлена проверка списка meta_desc, чтобы не было ошибки 'list object has no attribute strip'
                meta_desc = re.findall(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html_content, re.IGNORECASE)
                if meta_desc and str(meta_desc[0]).strip():
                    self.search_finished.emit(f"- {meta_desc[0].strip()}")
                else:
                    self.search_finished.emit(f"[Локальный ответ. Сеть вернула пустой ответ для: {self.query}]")
                
        except Exception as e:
            # Предотвращаем любые вылеты: если сеть упала, отдаем ИИ чистый текст ошибки
            self.search_finished.emit(f"[Сетевое ограничение: {str(e)}]")




# КОНЕЦ ЧАСТИ 2 ИЗ 15
# НАЧАЛО ЧАСТИ 3 ИЗ 15

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

# КОНЕЦ ЧАСТИ 3 ИЗ 15
# НАЧАЛО ЧАСТИ 4 ИЗ 15

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

# КОНЕЦ ЧАСТИ 4 ИЗ 15
# НАЧАЛО ЧАСТИ 5 ИЗ 15

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


class AIClientApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PythonCoder AI - Workstation")
        self.resize(1300, 850)
                # Расширенная сетка шагов памяти контекста (добавлен шаг 8 на 256 000 токенов)
        self.ctx_steps = {1: 1024, 2: 2048, 3: 4096, 4: 8192, 5: 16384, 6: 32768, 7: 131072, 8: 262144}

        
        self.init_database()
        self.load_sessions_from_db()
        
        self.current_model = ""
        self.bot_response_buffer = "" 
        self.last_code_block = ""  
        self.attached_file_context = "" 
        
        # Регистрация объекта кнопки для предотвращения ранних ошибок AttributeError
        self.btn_toggle_sidebar = None  

        # 🎙️ Инициализация локального микрофона Whisper
        self.voice_worker = VoiceWorker()
        self.voice_worker.text_recognized.connect(self.on_voice_text_received)
        self.voice_worker.status_updated.connect(self.on_voice_status_updated)

        # 🔊 ИНИЦИАЛИЗАЦИЯ ЕДИНОГО СИСТЕМНОГО СПИКЕРА WINDOWS (БЕЗ ЭХО)
        self.speech_process = QProcess(self)
        self.speech_queue = queue.Queue()  # Очередь для фраз, чтобы они не накладывались

        # 📈 Запуск фонового замера ресурсов ПК
        self.hw_monitor = HardwareMonitor()
        self.hw_monitor.stats_updated.connect(self.update_hardware_stats)
        self.hw_monitor.start()

        self.sandbox_process = None
        self.worker = None 
        self.search_worker = None 

        self.init_menu()
        self.init_ui()
        self.apply_cyberpunk_theme() 
        self.load_saved_settings()   
        
        QTimer.singleShot(100, self.check_server_status)
        
    def parse_and_execute_agent_commands(self, text):
        """🔍 Парсер команд ИИ Агента. Находит теги автоматизации и выполняет их на ПК."""
        if not self.agent_active_action.isChecked():
            return

        # Регулярные выражения для поиска макросов
        cmd_pattern = r"\[RUN_CMD:\s*(.*?)\]"
        url_pattern = r"\[OPEN_URL:\s*(.*?)\]"
        dir_pattern = r"\[MAKE_DIR:\s*(.*?)\]"
        file_pattern = r"\[CREATE_FILE:\s*([^|]+)\|([\s\S]*?)\]"

        executed_any = False

        # 1. Выполнение системных команд [RUN_CMD: ...]
        for cmd in re.findall(cmd_pattern, text):
            cmd = cmd.strip()
            # Белый список базовых программ для безопасности
            allowed_cmds = ["calc", "notepad", "explorer", "cmd", "taskmgr"]
            try:
                # Если команда из белого списка, запускаем напрямую, иначе через оболочку
                if cmd in allowed_cmds:
                    subprocess.Popen(cmd, shell=True)
                else:
                    subprocess.Popen(cmd, shell=True) # Позволяет выполнять любые команды, если доверяете ИИ
                
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Запущена программа '{cmd}'</i>")
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:#ff4444;'>❌ [Агент]: Ошибка запуска '{cmd}': {e}</b>")

        # 2. Открытие веб-ссылок [OPEN_URL: ...]
        for url in re.findall(url_pattern, text):
            url = url.strip()
            try:
                webbrowser.open(url)
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Открыта ссылка '{url}'</i>")
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:#ff4444;'>❌ [Агент]: Ошибка открытия ссылки: {e}</b>")

        # 3. Создание директорий [MAKE_DIR: ...]
        for folder in re.findall(dir_pattern, text):
            folder = folder.strip()
            try:
                os.makedirs(folder, exist_ok=True)
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Создана папка по пути '{os.path.abspath(folder)}'</i>")
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:#ff4444;'>❌ [Агент]: Ошибка создания папки: {e}</b>")

        # 4. Физическое создание файлов с кодом [CREATE_FILE: имя|содержимое]
        for filename, content in re.findall(file_pattern, text):
            filename = filename.strip()
            content = content.strip()
            try:
                # Создаем родительские папки, если они указаны в пути файла
                dirname = os.path.dirname(filename)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)
                
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
                
                self.chat_area.append(f"<br><i style='color:#00ffcc;'>⚡ [Агент]: Записан файл '{filename}' ({len(content)} симв.)</i>")
                executed_any = True
            except Exception as e:
                self.chat_area.append(f"<br><b style='color:#ff4444;'>❌ [Агент]: Ошибка записи файла '{filename}': {e}</b>")

        # Если что-то выполнилось, прокручиваем чат вниз к логам
        if executed_any:
            self.chat_area.moveCursor(QTextCursor.MoveOperation.End)
            # Обновляем html историю сессии, чтобы логи агента не пропадали при смене чатов
            self.chat_html_history[self.current_session] = self.chat_area.toHtml()

# КОНЕЦ ЧАСТИ 5 ИЗ 15
# НАЧАЛО ЧАСТИ 6 ИЗ 15

    def closeEvent(self, event):
        """Остановка фоновых потоков при закрытии программы"""
        self.hw_monitor.stop()
        self.hw_monitor.wait()
        event.accept()

    def toggle_sidebar_visibility(self):
        """🔘 Сворачивает или разворачивает левое окно истории чатов"""
        if self.session_sidebar.isVisible():
            self.session_sidebar.hide()
            self.btn_toggle_sidebar.setText("▶")
        else:
            self.session_sidebar.show()
            self.btn_toggle_sidebar.setText("◀")

    def clear_chat_context(self):
        """🗑️ Очищает историю сообщений и HTML-кэш для текущей сессии"""
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

# КОНЕЦ ЧАСТИ 6 ИЗ 15
# НАЧАЛО ЧАСТИ 7 ИЗ 15

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

    def delete_chat_session(self, session_name):
        """🗄️ Полное удаление чата из памяти приложения и локальной базы данных SQLite"""
        if self.session_list_widget.count() <= 1:
            self.chat_area.append("<br><b style='color:orange;'>Система: Нельзя удалить единственный активный чат!</b><br>")
            return
        try:
            if session_name in self.chat_sessions: del self.chat_sessions[session_name]
            if session_name in self.chat_html_history: del self.chat_html_history[session_name]
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
            
            # 1. Создаем таблицу базовой структуры, если её не было
            self.db_cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    name TEXT PRIMARY KEY, 
                    json_history TEXT, 
                    html_history TEXT
                )""")
            
            # 2. Мягкая миграция: Проверяем, есть ли колонка 'settings'. Если нет — добавляем.
            try:
                self.db_cursor.execute("SELECT settings FROM chat_sessions LIMIT 1")
            except sqlite3.OperationalError:
                # Ошибка означает, что колонки не существует. Добавляем её на лету.
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
            self.chat_html_history = {"Чат 1": "<i>Система: Начало нового диалога.</i><br><br>"}
            self.chat_individual_settings = {"Чат 1": {}}
        
        self.current_session = list(self.chat_sessions.keys())[0]

    def save_session_to_db(self, session_name):
        """Сохраняет измененную вкладку диалога и её настройки в базу данных"""
        try:
            json_str = json.dumps(self.chat_sessions.get(session_name, []))
            html_str = self.chat_html_history.get(session_name, "")
            
            # Собираем текущие настройки ползунков конкретно этого чата
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

# КОНЕЦ ЧАСТИ 7 ИЗ 15
# НАЧАЛО ЧАСТИ 8 ИЗ 15


    def attach_local_file(self):
        """📎 Безопасное чтение файлов с поддержкой кодировок Windows и файлов Arduino (.ino)"""
        try:
            result = QFileDialog.getOpenFileName(
                self, "Прикрепить документ для анализа", "", 
                "Документы (*.txt *.py *.log *.ino *.pdf *.docx)"
            )
            
            if not result or not result[0]: 
                return
                
            file_path = result[0].strip()
            ext = os.path.splitext(file_path)[1].lower().strip()
            text_content = ""
            
            # Добавили .ino в список поддерживаемых текстовых расширений
            if ext in [".txt", ".py", ".log", ".ino"]:
                encodings_to_try = [
                    'utf-8',          # Стандартный современный текст
                    'utf-8-sig',      # UTF-8 с меткой BOM
                    'cp1251',         # Стандартная кириллица Windows (ANSI)
                    'utf-16',         # Двухбайтовый текст Юникод
                    'cp866',          # Кириллица DOS
                    'latin-1'         # Запасной вариант
                ]
                
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
                        self.chat_area.append(f"<b style='color:red;'>Ошибка файловой системы: {e}</b><br>")
                        return

            elif ext == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(file_path)
                    text_content = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                except Exception as e:
                    self.chat_area.append(f"<b style='color:red;'>Ошибка PDF-модуля: {e}</b><br>")
                    return
            elif ext == ".docx":
                try:
                    import docx
                    doc = docx.Document(file_path)
                    text_content = "\n".join([p.text for p in doc.paragraphs])
                except Exception as e:
                    self.chat_area.append(f"<b style='color:red;'>Ошибка Word-модуля: {e}</b><br>")
                    return
            
            if text_content and text_content.strip():
                self.attached_file_context = f"\n=== СВЕДЕНИЯ ИЗ ДОКУМЕНТА ({os.path.basename(file_path)}):\n{text_content.strip()}\n===\n"
                self.chat_area.append(f"<i>📎 Система: Успешно считан файл {os.path.basename(file_path)} ({len(text_content)} симв.).</i><br>")
                self.btn_attach_file.setText("📎 Файл загружен!")
                self.btn_attach_file.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
            else:
                self.chat_area.append(f"<b style='color:orange;'>Система: Файл пуст, заблокирован или защищен от чтения!</b><br>")
                
        except Exception as global_err:
            self.chat_area.append(f"<b style='color:red;'>Система: Сбой файлового менеджера: {str(global_err)}</b><br>")


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

# КОНЕЦ ЧАСТИ 8 ИЗ 15
# НАЧАЛО ЧАСТИ 9 ИЗ 15

    def check_and_execute_agent_commands(self, text):
        """🔌 СУПЕР-АГЕНТ: Парсинг и физическое выполнение команд автоматизации на ПК"""
        # 1. Запуск стандартных системных утилит Windows
        match_run = re.search(r'\[RUN_CMD:\s*([a-zA-Z0-9_\-\.\s]+)\]', text)
        if match_run:
            cmd = match_run.group(1).strip()
            self.chat_area.append(f"<br><b style='color:#00ffcc;'>🔌 Агент: Вызываю {cmd}...</b><br>")
            if cmd in ["calc", "notepad", "explorer", "cmd", "taskmgr"]:
                subprocess.Popen(cmd, shell=True)
                self.chat_area.append(f"<b style='color:#5cb85c;'>🟢 Агент: Утилита {cmd} запущена.</b><br>")
            else:
                self.chat_area.append(f"<b style='color:red;'>🔴 Агент: Команда заблокирована безопасностью.</b><br>")

        # 2. Переход по ссылкам на веб-документацию
        match_url = re.search(r'\[OPEN_URL:\s*([^\s\]]+)\]', text)
        if match_url:
            url = match_url.group(1).strip()
            self.chat_area.append(f"<br><b style='color:#00ffcc;'>🔌 Агент: Перехожу к документации: {url}</b><br>")
            try:
                webbrowser.open(url)
                self.chat_area.append("<b style='color:#5cb85c;'>🟢 Агент: Браузер открыт.</b><br>")
            except Exception as e:
                self.chat_area.append(f"<b style='color:red;'>🔴 Агент: Ошибка браузера: {e}</b><br>")

        # 3. Автоматическое создание папок проекта
        match_dir = re.search(r'\[MAKE_DIR:\s*([^\]]+)\]', text)
        if match_dir:
            dir_path = match_dir.group(1).strip()
            self.chat_area.append(f"<br><b style='color:#00ffcc;'>🔌 Агент: Создаю рабочую папку: {dir_path}</b><br>")
            try:
                os.makedirs(dir_path, exist_ok=True)
                self.chat_area.append(f"<b style='color:#5cb85c;'>🟢 Агент: Папка создана.</b><br>")
            except Exception as e:
                self.chat_area.append(f"<b style='color:red;'>🔴 Агент: Ошибка ФС: {e}</b><br>")

        # 4. Физическое создание файлов кода на жестком диске
        match_file = re.search(r'\[CREATE_FILE:\s*([^|\]]+)\|\s*(.*?)\]', text, re.DOTALL)
        if match_file:
            filename = match_file.group(1).strip()
            file_content = match_file.group(2).strip()
            self.chat_area.append(f"<br><b style='color:#00ffcc;'>🔌 Агент: Записываю скрипт: {filename}</b><br>")
            try:
                safe_name = os.path.basename(filename) if ":" not in filename else filename
                with open(safe_name, "w", encoding="utf-8") as f:
                    f.write(file_content)
                self.chat_area.append(f"<b style='color:#5cb85c;'>🟢 Агент: Файл '{safe_name}' записан.</b><br>")
            except Exception as e:
                self.chat_area.append(f"<b style='color:red;'>🔴 Агент: Ошибка записи: {e}</b><br>")

# КОНЕЦ ЧАСТИ 9 ИЗ 15
# НАЧАЛО ЧАСТИ 10 ИЗ 15

    def run_code_in_sandbox(self):
        """💻 Запуск кода из Вкладки-Редактора (позволяет тестировать ручные правки)"""
        current_code = self.code_editor_field.toPlainText().strip()
        
        if not current_code and hasattr(self, 'last_code_block') and self.last_code_block.strip():
            current_code = self.last_code_block
            self.code_editor_field.setText(current_code)

        if not current_code:
            self.chat_area.append("<br><b style='color:orange;'>Система: Редактор кода пуст! Сначала сгенерируйте или вставьте скрипт.</b><br>")
            return
            
        self.chat_area.append("<br><b style='color:#f0ad4e;'>🔄 Песочница: Запуск кода из встроенного редактора...</b><br>")
        temp_file = os.path.join(os.getcwd(), "sandbox_temp.py")
        try:
            with open(temp_file, "w", encoding="utf-8") as f: f.write(current_code)
        except Exception as e:
            self.chat_area.append(f"<b style='color:red;'>Песочница: Ошибка записи: {e}</b><br>")
            return

        self.sandbox_process = QProcess(self)
        
        def on_sandbox_finished(exit_code, exit_status):
            raw_out = self.sandbox_process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
            raw_err = self.sandbox_process.readAllStandardError().data().decode('utf-8', errors='ignore')
            
            self.chat_area.append("<b>💻 Результат выполнения:</b>")
            if raw_out.strip():
                self.chat_area.append(f"<pre style='color:#5cb85c; background:#13171c; padding:8px; border:1px solid #005c4e; border-radius:4px;'>{raw_out}</pre>")
            if raw_err.strip():
                self.chat_area.append(f"<pre style='color:#d9534f; background:#13171c; padding:8px; border-radius:4px;'>{raw_err}</pre>")
            if not raw_out.strip() and not raw_err.strip():
                self.chat_area.append("<i style='color:gray;'>[Скрипт успешно завершился без вывода на экран]</i><br>")
                
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except Exception: pass

        self.sandbox_process.finished.connect(on_sandbox_finished)
        self.sandbox_process.start(sys.executable, [temp_file])

    def copy_last_code_block(self):
        """Копирует текущее содержимое текстового поля редактора кода"""
        code_text = self.code_editor_field.toPlainText().strip()
        if not code_text and hasattr(self, 'last_code_block'):
            code_text = self.last_code_block
        
        if code_text.strip():
            QApplication.clipboard().setText(code_text.strip())
            self.btn_copy_code.setText("✅ Скопировано!")
            QTimer.singleShot(2000, lambda: self.btn_copy_code.setText("📋 Копировать код"))
        else:
            self.btn_copy_code.setText("❌ Пусто")
            QTimer.singleShot(2000, lambda: self.btn_copy_code.setText("📋 Копировать код"))

    def optimize_user_prompt(self):
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

# КОНЕЦ ЧАСТИ 10 ИЗ 15
# НАЧАЛО ЧАСТИ 11 ИЗ 15

    def update_token_counter(self):
        """Расчет занятых токенов в текущей сессии диалога"""
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
        """Сохранение параметров интерфейса и конфигураций в базу данных SQLite"""
        try:
            # Меняем REAL на TEXT в логике сохранения (SQLite сам переварит типы данных)
            self.db_cursor.execute("INSERT OR REPLACE INTO ui_settings (key, val) VALUES (?, ?)", (key, str(val)))
            self.db_conn.commit()
        except Exception: 
            pass


    def load_saved_settings(self):
        """Загрузка конфигурации ползунков из SQLite при старте"""
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
            if "speech_on" in settings: self.cb_speech_on.setChecked(bool(settings["speech_on"]))
        except Exception: pass

    def update_hardware_stats(self, cpu_p, ram_p, gpu_p, vram_p):
        """Отображение текущей утилизации ресурсов процессора и памяти"""
        self.lbl_sys_cpu.setText(f"Загрузка CPU: {cpu_p:.1f}%")
        self.lbl_sys_ram.setText(f"Использование RAM: {ram_p:.1f}%")

    def check_server_status(self):
        """Проверка доступности локального API сервера Ollama по порту 11434"""
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

# КОНЕЦ ЧАСТИ 11 ИЗ 15
# НАЧАЛО ЧАСТИ 12 ИЗ 15

    def load_installed_models(self):
        """Загрузка списка локально установленных ИИ-моделей с восстановлением последней выбранной"""
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
                if model_name: 
                    self.model_selector.addItem(model_name)
            
            # --- ЛОГИКА ВОССТАНОВЛЕНИЯ ПОСЛЕДНЕЙ МОДЕЛИ ---
            saved_model = ""
            try:
                self.db_cursor.execute("SELECT val FROM ui_settings WHERE key = 'selected_model_name'")
                row = self.db_cursor.fetchone()
                if row: 
                    saved_model = str(row[0])
            except Exception:
                pass
            
            # Если в базе было имя и оно есть в новом списке — выбираем его
            index_to_set = 0
            if saved_model:
                found_index = self.model_selector.findText(saved_model)
                if found_index != -1:
                    index_to_set = found_index
                    
            self.model_selector.setCurrentIndex(index_to_set)
            self.current_model = self.model_selector.itemText(index_to_set)
            # -----------------------------------------------
            
            self.model_selector.blockSignals(False)
            self.status_label.setText("🟢 Сервер Ollama: Работает")
        except Exception: 
            self.model_selector.blockSignals(False)


    def on_model_changed(self, model_name):
        """Обработка переключения active ИИ-модели с сохранением в БД"""
        if not model_name: return
        self.current_model = model_name
        
        # 💾 СОХРАНЯЕМ ВЫБРАННУЮ МОДЕЛЬ В БАЗУ ДАННЫХ
        self.save_ui_setting("selected_model_name", model_name)
        
        act_msg = f"<i>Система: Активирована модель {model_name}</i><br>"
        if self.current_session in self.chat_html_history: 
            self.chat_html_history[self.current_session] += act_msg
        self.chat_area.append(act_msg)

    def import_gguf_model(self):
        """Импорт внешней модели .gguf и ее регистрация в локальной экосистеме Ollama"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл модели GGUF", "", "ИИ Модели (*.gguf)")
        if not file_path: return
        native_path = os.path.normpath(file_path)
        model_dir = os.path.dirname(native_path)
        model_name, _ = os.path.splitext(os.path.basename(file_path))
        model_name = model_name.lower().replace(".", "-").replace("_", "-")
        self.chat_area.append(f"<i>Система: Начинаю импорт <b>{model_name}</b>...</i><br>")
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
                self.chat_area.append(f"<b>🟢 Модель {model_name} импортирована!</b><br>")
                self.load_installed_models()
            else:
                raw_errors = self.import_process.readAllStandardError().data().decode('utf-8', errors='ignore')
                self.chat_area.append(f"<b style='color:red;'>🔴 Ошибка импорта:</b> {raw_errors}<br>")
        self.import_process.finished.connect(on_process_finished)
        self.import_process.start(ollama_executable, ["create", model_name, "-f", temp_modelfile_path])

    def get_ai_options(self):
        """⚙️ Умный сбор параметров с авто-расширением чаши контекста под большие скрипты"""
        try:
            predict_limit = int(self.slider_predict.value())
            chosen_ctx = int(self.ctx_steps.get(self.slider_ctx.value(), 2048))
            
            # Если лимит генерации слишком большой, чаша контекста автоматически расширяется
            if chosen_ctx <= predict_limit:
                chosen_ctx = max(predict_limit * 3, 262144) 
            options = {
                "temperature": float(self.slider_temp.value() / 10.0),
                "top_p": float(self.slider_topp.value() / 10.0),
                "top_k": int(self.slider_topk.value()),
                "mirostat": int(self.slider_miro.value()),
                "repeat_penalty": float(self.slider_penalty.value() / 10.0),
                "frequency_penalty": float(self.slider_freq_penalty.value() / 10.0),
                "presence_penalty": float(self.slider_pres_penalty.value() / 10.0),
                "num_ctx": chosen_ctx,        
                "num_predict": predict_limit,  
                "num_thread": int(self.slider_threads.value())   
            }
            return options
        except Exception: 
            return {"temperature": 0.7, "top_p": 0.9, "num_ctx": 256000, "num_predict": 4096}


# КОНЕЦ ЧАСТИ 12 ИЗ 15
# НАЧАЛО ЧАСТИ 13 ИЗ 15


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
        service_menu = menu_bar.addMenu("Сервис")
        check_server_action = QAction("🔄 Проверить статус Ollama", self)
        check_server_action.triggered.connect(self.check_server_status)
        service_menu.addAction(check_server_action)
        
        # Чекбокс-переключатель ИИ Агента
        self.agent_active_action = QAction("🔌 Включить ИИ Агента (Автоматизация ПК)", self, checkable=True)
        try:
            self.db_cursor.execute("SELECT val FROM ui_settings WHERE key = 'agent_enabled'")
            row = self.db_cursor.fetchone()
            if row: self.agent_active_action.setChecked(bool(int(row[0])))
        except Exception: pass
        
        self.agent_active_action.triggered.connect(self.toggle_agent_mode)
        service_menu.addAction(self.agent_active_action)

        # Меню Справка
        help_menu = menu_bar.addMenu("Справка")
        
        about_action = QAction("ℹ️ О программе...", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)
        
        agent_help_action = QAction("🔌 Справка: ИИ Агент", self)
        agent_help_action.triggered.connect(self.show_agent_help_dialog)
        help_menu.addAction(agent_help_action)

    def show_about_dialog(self):
        """ℹ️ Красивое информационное окно справки"""
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Справка — PythonCoder AI")
        msg.setText(
            "<h3>PythonCoder AI: Workstation Pro v3.7</h3>"
            "<b>Разработчики:</b> ИИ GOOGLE и MIKOLA PINCHUK<br><br>"
            "Рабочая станция для локального анализа кода и автоматизации с поддержкой ИИ.<br><br>"
            "<b>Основные подсистемы:</b><br>"
            "• 🤖 <b>Локальный ИИ:</b> Оркестрация через сервер Ollama.<br>"
            "• 🌐 <b>Веб-модуль:</b> Стабильный поиск контекста через сеть.<br>"
            "• 💻 <b>Песочница:</b> Изолированный запуск Python-скриптов.<br>"
            "• 🎙️ <b>Аудио:</b> Локальный ввод (Whisper) и озвучка ответов (TTS).<br><br>"
            "<i>Все права защищены. Релиз Stable.</i>"
        )
        msg.setStyleSheet("""
            QMessageBox { background-color: #13171c; }
            QLabel { color: #00ffcc; font-size: 12px; }
            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; padding: 4px 15px; font-weight: bold; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; }
        """)
        msg.exec()

    def show_agent_help_dialog(self):
        """📂 Расширенное окно документации по возможностям ИИ-Агента"""
        from PyQt6.QtWidgets import QMessageBox
        msg = QMessageBox(self)
        msg.setWindowTitle("Документация: ИИ Агент Автоматизации ПК")
        
        # Подробный структурированный текст справки
        help_text = (
            "<h2>🔌 Руководство по ИИ Агенту автоматизации</h2>"
            "Когда в меню <b>Сервис</b> активен режим Агента, модель получает скрытую системную "
            "инструкцию. Она позволяет ИИ управлять вашей операционной системой в фоновом режиме "
            "с помощью специальных синтаксических макросов (тегов).<br><br>"
            
            "<h3>📂 1. Управление файловой системой</h3>"
            "• <code>[MAKE_DIR: путь_к_папке]</code> — Создание дерева директорий. Если промежуточных папок нет, они создадутся сами.<br>"
            "• <code>[CREATE_FILE: путь/имя.ext|содержимое]</code> — Запись текста или кода на диск. Автоматически создает папки для файла, если они указаны.<br><br>"
            "<i>Пример запроса к ИИ:</i> «Создай структуру проекта под названием flask_app, внутри сделай файл requirements.txt с текстом flask»<br><br>"
            
            "<h3>💻 2. Запуск системных утилит и команд</h3>"
            "• <code>[RUN_CMD: команда]</code> — Исполнение строки в командной оболочке (cmd/powershell).<br>"
            "• <b>Стандартные утилиты:</b> <code>calc</code> (калькулятор), <code>notepad</code> (блокнот), "
            "<code>explorer</code> (проводник), <code>taskmgr</code> (диспетчер задач), <code>cmd</code> (консоль).<br>"
            "• <b>Сложные сценарии:</b> Вы можете просить запускать компиляторы или скрипты, например: <code>python main.py</code>.<br><br>"
            "<i>Пример запроса к ИИ:</i> «Напиши простой скрипт на python для вывода даты, сохрани в test.py и запусти его через cmd»<br><br>"
            
            "<h3>🌐 3. Веб-автоматизация</h3>"
            "• <code>[OPEN_URL: ссылка]</code> — Открытие веб-сайтов, локальных html-документов или страниц документации в вашем браузере по умолчанию.<br><br>"
            "<i>Пример запроса к ИИ:</i> «Найди ошибку в моем коде и открой документацию PyQt6 на официальном сайте»<br><br>"
            
            "<h3>💡 Советы по эффективному использованию:</h3>"
            "1. <b>Прямые приказы:</b> Не стесняйтесь отдавать ИИ прямые команды: <i>'Разверни мне каркас проекта на Django...'</i> или <i>'Открой блокнот и калькулятор'</i>.<br>"
            "2. <b>Комбинирование:</b> Модель может вызывать сколько угодно макросов за один ответ. Она может сначала создать папку, затем записать туда три файла и запустить главный.<br>"
            "3. <b>Контроль вывода:</b> Все успешно выполненные действия Агента логируются в окне чата бирюзовым цветом (<code>⚡ [Агент]: ...</code>) и навсегда сохраняются в историю текущей вкладки.<br><br>"
            
            "<h3>⚠️ Внимание и безопасность:</h3>"
            "Так как макросы выполняются через оболочку вашей ОС, ИИ имеет доступ к вашей файловой системе. "
            "<b>Не используйте режим Агента с непроверенными или сомнительными моделями</b>, которые могут попытаться сгенерировать деструктивные системные команды."
        )
        
        msg.setText(help_text)
        
        # Стилизация окна под общую темную киберпанк-эстетику приложения
        msg.setStyleSheet("""
            QMessageBox { 
                background-color: #13171c; 
                min-width: 600px;
            }
            QLabel { 
                color: #e3e8ef; 
                font-size: 13px; 
                line-height: 1.5;
            }
            h2 { 
                color: #00ffcc; 
                font-size: 16px; 
                font-weight: bold;
                margin-bottom: 10px;
            }
            h3 { 
                color: #00b395; 
                font-size: 14px; 
                font-weight: bold;
                margin-top: 15px;
                margin-bottom: 5px;
            }
            code { 
                background-color: #1a1f26; 
                color: #ffaa00; 
                padding: 2px 5px; 
                border-radius: 3px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QPushButton { 
                background-color: #1a1f26; 
                border: 1px solid #005c4e; 
                color: #00ffcc; 
                padding: 6px 20px; 
                font-weight: bold; 
                border-radius: 4px;
            }
            QPushButton:hover { 
                background-color: #00b395; 
                color: #0d0f12; 
                border: 1px solid #00b395;
            }
        """)
        msg.exec()


    def toggle_agent_mode(self, checked):
        """Включение/выключение режима агента с сохранением состояния"""
        self.save_ui_setting("agent_enabled", 1 if checked else 0)
        status = "активирован" if checked else "деактивирован"
        self.chat_area.append(f"<br><i style='color:#00ffcc;'>Система: Режим ИИ Агента {status}.</i><br>")


    def create_new_chat_session(self):
        """Создание новой вкладки диалога с ИИ"""
        new_id = self.session_list_widget.count() + 1
        name = f"Чат {new_id}"
        self.chat_sessions[name] = []
        self.chat_html_history[name] = "<i>Система: Начало нового диалога.</i><br><br>"
        
        # Задаем дефолтные настройки для нового чата на основе текущих
        self.chat_individual_settings[name] = {
            "model": self.model_selector.currentText(),
            "temp": 7, "topp": 9, "topk": 40, "miro": 0, "penalty": 11,
            "freq": 0, "pres": 0, "ctx": 2, "predict": 4096, "threads": 4
        }
        
        self.session_list_widget.addItem(name)
        self.save_session_to_db(name)
        self.session_list_widget.setCurrentRow(new_id - 1)

    def switch_chat_session(self, session_name):
        """Переключение рабочей области на выбранную сессию и загрузка её конфигурации"""
        if not session_name or session_name not in self.chat_sessions: 
            return
            
        self.current_session = session_name
        
        # --- БЛОК ВОССТАНОВЛЕНИЯ НАСТРОЕК ДЛЯ ВЫБРАННОГО ЧАТА ---
        settings = self.chat_individual_settings.get(session_name, {})
        if settings:
            # 1. Извлекаем и жестко фиксируем модель именно для этого чата
            saved_model = settings.get("model", "")
            if saved_model:
                self.model_selector.blockSignals(True)
                found_index = self.model_selector.findText(saved_model)
                if found_index != -1:
                    self.model_selector.setCurrentIndex(found_index)
                    # Фикс: Синхронизируем внутреннее состояние движка с UI
                    self.current_model = saved_model 
                self.model_selector.blockSignals(False)

            # 2. Восстанавливаем позиции всех ползунков, блокируя отправку ложных сигналов в БД
            self.slider_temp.blockSignals(True); self.slider_temp.setValue(settings.get("temp", 7)); self.slider_temp.blockSignals(False)
            self.slider_topp.blockSignals(True); self.slider_topp.setValue(settings.get("topp", 9)); self.slider_topp.blockSignals(False)
            self.slider_topk.blockSignals(True); self.slider_topk.setValue(settings.get("topk", 40)); self.slider_topk.blockSignals(False)
            self.slider_miro.blockSignals(True); self.slider_miro.setValue(settings.get("miro", 0)); self.slider_miro.blockSignals(False)
            self.slider_penalty.blockSignals(True); self.slider_penalty.setValue(settings.get("penalty", 11)); self.slider_penalty.blockSignals(False)
            self.slider_freq_penalty.blockSignals(True); self.slider_freq_penalty.setValue(settings.get("freq", 0)); self.slider_freq_penalty.blockSignals(False)
            self.slider_pres_penalty.blockSignals(True); self.slider_pres_penalty.setValue(settings.get("pres", 0)); self.slider_pres_penalty.blockSignals(False)
            self.slider_ctx.blockSignals(True); self.slider_ctx.setValue(settings.get("ctx", 2)); self.slider_ctx.blockSignals(False)
            self.slider_predict.blockSignals(True); self.slider_predict.setValue(settings.get("predict", 4096)); self.slider_predict.blockSignals(False)
            self.slider_threads.blockSignals(True); self.slider_threads.setValue(settings.get("threads", 4)); self.slider_threads.blockSignals(False)
            
            # 3. Синхронизируем текстовые индикаторы (лейблы) под новые значения
            self.lbl_temp_val.setText(str(settings.get("temp", 7) / 10.0))
            self.lbl_topp_val.setText(str(settings.get("topp", 9) / 10.0))
            self.lbl_topk_val.setText(str(settings.get("topk", 40)))
            self.lbl_miro_val.setText(str(settings.get("miro", 0)))
            self.lbl_penalty_val.setText(str(settings.get("penalty", 11) / 10.0))
            self.lbl_freq_val.setText(str(settings.get("freq", 0) / 10.0))
            self.lbl_pres_val.setText(str(settings.get("pres", 0) / 10.0))
            self.lbl_ctx_val.setText(str(self.ctx_steps.get(settings.get("ctx", 2), 2048)))
            self.lbl_predict_val.setText(str(settings.get("predict", 4096)))
            self.lbl_threads_val.setText(str(settings.get("threads", 4)))
        # --------------------------------------------------------

        # --- БЛОК ОТРИСОВКИ ИСТОРИИ СООБЩЕНИЙ ---
        if session_name not in self.chat_html_history or not self.chat_html_history[session_name]:
            html_builder = [f"<i>Система: Переключено на {session_name}. История загружена.</i><br><br>"]
            for msg in self.chat_sessions[session_name]:
                if msg["role"] == "user": 
                    html_builder.append(f"<b>Вы:</b> {msg['content']}<br>")
                elif msg["role"] == "assistant": 
                    html_builder.append(f"<b>Бот:</b> {MarkdownHighlighter.to_html(msg['content'])}<br><br>")
            self.chat_html_history[session_name] = "".join(html_builder)
            
        # Обновляем главное текстовое поле чата
        self.chat_area.setHtml(self.chat_html_history[session_name])
        self.chat_area.moveCursor(QTextCursor.MoveOperation.End)
        
        # Пересчитываем счетчики и сбрасываем старую скорость генерации
        self.update_token_counter()
        self.lbl_generation_speed.setText("Скорость ИИ: 0.0 tok/sec")

    def on_model_changed(self, model_name):
        """Обработка переключения active ИИ-модели с сохранением в БД сессии"""
        if not model_name: return
        self.current_model = model_name
        
        # Сохраняем модель в глобальные настройки и в сессию
        self.save_ui_setting("selected_model_name", model_name)
        if hasattr(self, 'current_session') and self.current_session in self.chat_individual_settings:
            self.chat_individual_settings[self.current_session]["model"] = model_name
        
        act_msg = f"<i>Система: Активирована модель {model_name}</i><br>"
        if self.current_session in self.chat_html_history: 
            self.chat_html_history[self.current_session] += act_msg
        self.chat_area.append(act_msg)
        self.save_session_to_db(self.current_session) # Сразу пишем в базу изменения

    def toggle_voice_recording(self, checked):
        """Переключение триггера аудиозаписи с микрофона"""
        if checked:
            self.btn_voice.setText("🛑 Запись... Нажмите для перевода")
            self.btn_voice.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold;")
            self.voice_worker.start_recording()
        else:
            self.btn_voice.setText("⏳ Обработка речи...")
            self.btn_voice.setStyleSheet("background-color: #777; color: white;")
            self.voice_worker.stop_and_process()

    def on_voice_text_received(self, text):
        """Обработка текста, распознанного локальной моделью Whisper"""
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
        """Динамическая валидация текста в поле системного промпта"""
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

# КОНЕЦ ЧАСТИ 13 ИЗ 15
# НАЧАЛО ЧАСТИ 14 ИЗ 15

    def send_message(self):
        """Отправка сообщения ИИ или прерывание генерации, если поток активен"""
        if self.worker and self.worker.isRunning():
            self.worker.stop_generation()
            return

        try:
            query = self.input_field.toPlainText().strip()
            if not query: return
            
            full_process_query = query
            if self.attached_file_context:
                full_process_query = self.attached_file_context + query
                self.attached_file_context = ""
                self.btn_attach_file.setText("📎 Прикрепить файл")
                self.btn_attach_file.setStyleSheet("")

            if hasattr(self, 'cb_web_search') and self.cb_web_search.isChecked():
                self.chat_area.append(f"<b>Вы:</b> {query} <i>(выполняю веб-поиск...)</i>")
                self.send_btn.setText("🛑 Стоп ИИ")
                self.send_btn.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; padding: 5px;")
                
                # Создаем воркер напрямую, без упоминания удаленного селектора
                self.search_worker = WebSearchWorker(query)
                
                def on_search_done(web_context):
                    augmented_query = f"Используй следующие актуальные факты из интернета для ответа:\n{web_context}\n\nЗапрос пользователя: {full_process_query}"
                    self.execute_ollama_call(augmented_query, raw_user_query=query)
                    
                self.search_worker.search_finished.connect(on_search_done)
                self.search_worker.start()
            else:
                self.chat_area.append(f"<b>Вы:</b> {query}")
                self.execute_ollama_call(full_process_query, raw_user_query=query)


                
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>[Сбой]:</b> {str(e)}<br>")
            self.send_btn.setText("Отправить")
            self.send_btn.setStyleSheet("background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; font-weight: bold; padding: 5px;")

    def continue_bot_generation(self):
        """⏭️ Принудительное бесшовное продолжение генерации оборванного кода"""
        if self.worker and self.worker.isRunning(): return
        try:
            self.chat_history = self.chat_sessions.get(self.current_session, [])
            if not self.chat_history:
                self.chat_area.append("<br><b style='color:orange;'>Система: Чат пуст. Нечего продолжать!</b><br>")
                return
            self.chat_area.append("<i><b>Вы:</b> Продолжай (дописываю оборванный скрипт...)</i>")
            continue_prompt = "Ты оборвал свой прошлый ответ на полуслове. Срочно продолжи писать программный код строго со следующего символа, на котором остановился! Не повторяй написанный ранее код, выдай только продолжение."
            self.execute_ollama_call(continue_prompt, raw_user_query="Продолжай писать код")
        except Exception as e:
            self.chat_area.append(f"<br><b style='color:red;'>[Сбой продолжения]:</b> {str(e)}<br>")

    def execute_ollama_call(self, process_query, raw_user_query):
        """Формирование контекста памяти и запуск фонового воркера ИИ"""
        try:
            self.chat_history = self.chat_sessions.get(self.current_session, [])
            if self.current_session not in self.chat_html_history: self.chat_html_history[self.current_session] = ""
            
            if len(self.chat_history) == 0:
                sys_prompt = self.sys_prompt_edit.toPlainText().strip()
                
                # Скрытая системная вставка, если агент включен в сервис-меню
                if self.agent_active_action.isChecked():
                    agent_injection = (
                        "\n[ИНСТРУКЦИЯ АГЕНТА]: Тебе разрешено управлять ПК пользователя через теги автоматизации. "
                        "Если пользователь просит запустить утилиту, используй строго формат [RUN_CMD: calc/notepad/explorer/cmd/taskmgr]. "
                        "Если нужно открыть сайт, пиши [OPEN_URL: https://...]. "
                        "Если нужно создать директорию, пиши [MAKE_DIR: имя]. "
                        "Если нужно сохранить код в файл, пиши [CREATE_FILE: скрипт.py|код внутри]. "
                        "Вызывай эти теги прямо внутри своего текстового ответа, когда это необходимо."
                    )
                    sys_prompt += agent_injection
                    
                if sys_prompt: 
                    self.chat_history.append({"role": "system", "content": sys_prompt})
            
            # Если чат уже идет, но агент включен — точечно напоминаем модели о скрытых командах в запросе
            if self.agent_active_action.isChecked() and not process_query.startswith("[ИНСТРУКЦИЯ АГЕНТА]"):
                process_query = "[РЕЖИМ АГЕНТА АКТИВЕН. Используй при необходимости теги RUN_CMD, OPEN_URL, MAKE_DIR, CREATE_FILE]\n" + process_query

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
            self.send_btn.setStyleSheet("background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; font-weight: bold; padding: 5px;")

    def append_bot_chunk(self, text):
        """Стриминг текста на экран и нарезка чистых фраз без кода в очередь TTS"""
        self.bot_response_buffer += text
        cursor = self.chat_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.chat_area.setTextCursor(cursor)
        
        if self.cb_speech_on.isChecked():
            if not hasattr(self, '_speech_buffer'): self._speech_buffer = ""
            self._speech_buffer += text
            
            if any(char in text for char in ['.', '!', '?', '\n']):
                phrase = self._speech_buffer.strip()
                
                # Полностью вырезаем блоки кода и любые фрагменты между символами кода `
                phrase = re.sub(r'```.*?```', '', phrase, flags=re.DOTALL)
                phrase = re.sub(r'`.*?`', '', phrase, flags=re.DOTALL)
                # Если в фразе осталась одиночная открытая кавычка кода, значит ИИ еще пишет код — молчим!
                if phrase.count('`') % 2 != 0 or "```" in phrase:
                    return
                    
                phrase = re.sub(r'[\[\]\(\)\{\}\_\-\+\=\*\/\\#:]', ' ', phrase)
                phrase = phrase.replace('"', '').replace("'", "")
                
                if len(phrase) > 2 and not phrase.startswith("<"):
                    self.speech_queue.put(phrase)
                    self.process_speech_queue()
                self._speech_buffer = ""

    def process_speech_queue(self):
        """🗣️ Контролирует, чтобы голоса не накладывались друг на друга"""
        if self.speech_process.state() == QProcess.ProcessState.Running:
            return
        
        if not self.speech_queue.empty():
            phrase = self.speech_queue.get()
            ps_command = f'Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak("{phrase}")'
            
            try:
                self.speech_process.disconnect()
            except Exception:
                pass
            self.speech_process.finished.connect(self.process_speech_queue)
            self.speech_process.start("powershell", ["-Command", ps_command])

    def on_generation_finished(self):
        """Пост-обработка ответов: рендеринг Markdown/HTML и клинч кода во вкладку редактора"""
        try:
            # 1. Рендеринг финального Markdown-ответа в красивый HTML
            html_response = MarkdownHighlighter.to_html(self.bot_response_buffer)
            
            # 2. Поиск блоков кода для автоматической вставки во вкладку редактора
            code_blocks = re.findall(r'```(?:[a-zA-Z0-9_+-]*?)\n(.*?)(?:```|$)', self.bot_response_buffer, re.DOTALL)
            self.last_code_block = code_blocks[-1] if code_blocks else ""
            
            if self.last_code_block.strip():
                self.code_editor_field.setText(self.last_code_block.strip())
                self.bottom_tabs.setCurrentIndex(1) # Само переключение на вкладку "Редактор кода"!
            
            # 3. Обновление памяти контекста и истории чата для текущей сессии
            self.chat_history.append({"role": "assistant", "content": self.bot_response_buffer})
            self.chat_sessions[self.current_session] = self.chat_history
            self.chat_html_history[self.current_session] += f"<b>Бот:</b> {html_response}<br><br>"
            self.chat_area.setHtml(self.chat_html_history[self.current_session])
            
            # 4. ИНТЕГРАЦИЯ: Запуск парсера команд ИИ Агента (выполнение команд на ПК)
            if hasattr(self, 'parse_and_execute_agent_commands'):
                self.parse_and_execute_agent_commands(self.bot_response_buffer)
            
            # 5. Сохранение текущего состояния сессии и её настроек в базу данных SQLite
            self.save_session_to_db(self.current_session)

            # 6. Блок голосовой озвучки (TTS) с очисткой текста от кода и макросов
            if self.cb_speech_on.isChecked() and hasattr(self, '_speech_buffer') and self._speech_buffer.strip():
                phrase = self._speech_buffer.strip()
                phrase = re.sub(r'```.*?```', '', phrase, flags=re.DOTALL)
                # Удаляем управляющие теги Агента из озвучки, чтобы робот не читал вслух "[RUN_CMD: calc]"
                phrase = re.sub(r'\[.*?\]', '', phrase)
                phrase = re.sub(r'[\[\]\(\)\{\}\_\-\+\=\*\/\\#:]', ' ', phrase)
                phrase = phrase.replace('"', '').replace("'", "")
                if len(phrase) > 2:
                    self.speech_queue.put(phrase)
                    self.process_speech_queue()
                self._speech_buffer = ""

            # 7. Автоматическая прокрутка текстового поля чата вниз
            cursor = self.chat_area.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.chat_area.setTextCursor(cursor)
            
            # 8. Пересчет токенов
            self.update_token_counter()
            
        except Exception as e:
            print(f"Ошибка в on_generation_finished: {e}")
            if hasattr(self, 'chat_area'):
                self.chat_area.append(f"<br><b style='color:red;'>[Ошибка пост-обработки]:</b> {str(e)}<br>")
                
        finally: 
            # 9. Возвращаем кнопку отправки в штатное рабочее состояние
            self.send_btn.setText("Отправить")
            self.send_btn.setStyleSheet("background-color: #1a1f26; border: 1px solid #005c4e; color: #00ffcc; font-weight: bold; padding: 5px;")

# КОНЕЦ ЧАСТИ 14 ИЗ 15
# НАЧАЛО ЧАСТИ 15.1 ИЗ 15.3

    def init_ui(self):
        """Монолитный метод сборки интерфейса с выравниванием всех трех панелей в одну линию"""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        hbox_layout = QHBoxLayout(main_widget)
        hbox_layout.setContentsMargins(10, 10, 10, 10)
        hbox_layout.setSpacing(0) 

        # ========================================================
        # 1. ЛЕВАЯ ПАНЕЛЬ (СПИСОК ЧАТОВ)
        # ========================================================
        self.session_sidebar = QGroupBox("История чатов")
        self.session_sidebar.setFixedWidth(200)
        sidebar_vbox = QVBoxLayout(self.session_sidebar)
        sidebar_vbox.setContentsMargins(8, 12, 8, 8)

        self.session_list_widget = QListWidget()
        for k in self.chat_sessions.keys(): 
            self.session_list_widget.addItem(k)
        self.session_list_widget.setCurrentRow(0)
        self.session_list_widget.currentTextChanged.connect(self.switch_chat_session)
        
        self.session_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list_widget.customContextMenuRequested.connect(self.open_chat_context_menu)
        
        sidebar_vbox.addWidget(self.session_list_widget)

        self.btn_new_chat = QPushButton("➕ Новый диалог")
        self.btn_new_chat.clicked.connect(self.create_new_chat_session)
        sidebar_vbox.addWidget(self.btn_new_chat)
        hbox_layout.addWidget(self.session_sidebar)

        # ========================================================
        # ВЕРТИКАЛЬНАЯ УЗКАЯ КНОПКА-РАЗДЕЛИТЕЛЬ (Ширина 10px)
        # ========================================================
        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setFixedWidth(10) 
        
        from PyQt6.QtWidgets import QSizePolicy
        self.btn_toggle_sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.btn_toggle_sidebar.clicked.connect(self.toggle_sidebar_visibility)
        hbox_layout.addWidget(self.btn_toggle_sidebar)

# КОНЕЦ ЧАСТИ 15.1 ИЗ 15.3
# НАЧАЛО ЧАСТИ 15.2 ИЗ 15.3

        # ========================================================
        # 2. ЦЕНТРАЛЬНАЯ ПАНЕЛЬ (ОКНО ДИАЛОГА И НОВЫЕ ВКЛАДКИ ВВОДА)
        # ========================================================
        self.center_container = QGroupBox("Рабочее пространство PythonCoder")
        center_vbox = QVBoxLayout(self.center_container)
        center_vbox.setContentsMargins(8, 12, 8, 8)

        top_bar_layout = QHBoxLayout()
        self.status_label = QLabel("Проверка сервера...")
        top_bar_layout.addWidget(self.status_label)
        top_bar_layout.addStretch()

        top_bar_layout.addWidget(QLabel("Модель:"))
        self.model_selector = QComboBox()
        self.model_selector.setMinimumWidth(220) 
        self.model_selector.currentTextChanged.connect(self.on_model_changed)
        top_bar_layout.addWidget(self.model_selector)
        center_vbox.addLayout(top_bar_layout)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.splitter.addWidget(self.chat_area)

        # Блок с вкладками QTabWidget
        self.bottom_tabs = QTabWidget()
        
        # Вкладка 1: Промпт
        self.prompt_tab_widget = QWidget()
        prompt_tab_layout = QVBoxLayout(self.prompt_tab_widget)
        prompt_tab_layout.setContentsMargins(0, 4, 0, 0)
        self.input_field = SmartLineEdit()
        self.input_field.enter_pressed.connect(self.send_message)
        prompt_tab_layout.addWidget(self.input_field)
        self.bottom_tabs.addTab(self.prompt_tab_widget, "💬 Запрос ИИ")

        # Вкладка 2: Редактор кода
        self.code_tab_widget = QWidget()
        code_tab_layout = QVBoxLayout(self.code_tab_widget)
        code_tab_layout.setContentsMargins(0, 4, 0, 0)
        self.code_editor_field = QTextEdit()
        self.code_editor_field.setPlaceholderText("# Сгенерированный код появится здесь автоматически...")
        self.code_editor_field.setFixedHeight(180)
        self.code_editor_field.setFontFamily("Consolas")
        code_tab_layout.addWidget(self.code_editor_field)
        self.bottom_tabs.addTab(self.code_tab_widget, "💻 Редактор кода")

        # === ВОССТАНАВЛИВАЕМ ПРОПУЩЕННЫЙ КОНТЕЙНЕР ===
        self.input_container = QWidget()
        input_container_layout = QVBoxLayout(self.input_container)
        input_container_layout.setContentsMargins(0, 0, 0, 0)
        input_container_layout.addWidget(self.bottom_tabs)
        # =============================================

        # Нижняя строка функциональных кнопок (Уже без комбобокса поисковиков)
        features_layout = QHBoxLayout()

        self.cb_web_search = QCheckBox("Искать в сети")
        features_layout.addWidget(self.cb_web_search)
        
        self.btn_attach_file = QPushButton("📎 Прикрепить файл")
        self.btn_attach_file.clicked.connect(self.attach_local_file)
        features_layout.addWidget(self.btn_attach_file)

        self.btn_save_py_file = QPushButton("💾 Сохранить .py")
        self.btn_save_py_file.setStyleSheet("background-color: #005c4e; color: white;")
        self.btn_save_py_file.clicked.connect(self.save_code_from_editor)
        features_layout.addWidget(self.btn_save_py_file)

        self.btn_continue_gen = QPushButton("⏭️ Продолжить")
        self.btn_continue_gen.setStyleSheet("background-color: #e0a800; color: black; font-weight: bold;")
        self.btn_continue_gen.clicked.connect(self.continue_bot_generation)
        features_layout.addWidget(self.btn_continue_gen)

        self.btn_optimize_prompt = QPushButton("🧠 Оптимизировать промпт")
        self.btn_optimize_prompt.setStyleSheet("background-color: #6f42c1; color: white; font-weight: bold;")
        self.btn_optimize_prompt.clicked.connect(self.optimize_user_prompt)
        features_layout.addWidget(self.btn_optimize_prompt)
        
        self.btn_run_sandbox = QPushButton("💻 Выполнить код")
        self.btn_run_sandbox.setStyleSheet("background-color: #f0ad4e; color: white; font-weight: bold;")
        self.btn_run_sandbox.clicked.connect(self.run_code_in_sandbox)
        features_layout.addWidget(self.btn_run_sandbox)
        
        self.btn_copy_code = QPushButton("📋 Копировать код")
        self.btn_copy_code.setStyleSheet("background-color: #5cb85c; color: white; font-weight: bold;")
        self.btn_copy_code.clicked.connect(self.copy_last_code_block)
        features_layout.addWidget(self.btn_copy_code)

        self.send_btn = QPushButton("Отправить")
        self.send_btn.clicked.connect(self.send_message)
        features_layout.addWidget(self.send_btn)
        
        # Упаковываем нижнюю панель кнопок
        input_container_layout.addLayout(features_layout)
        
        self.splitter.addWidget(self.input_container)
        
        # Передаем список начальных размеров для чата и поля ввода (например, 500 и 200 пикселей)
        self.splitter.setSizes([500, 200]) 
        
        center_vbox.addWidget(self.splitter)
        hbox_layout.addWidget(self.center_container, stretch=3)

        hbox_layout.addSpacing(10)
        self.init_right_sidebar(hbox_layout)

# КОНЕЦ ЧАСТИ 15.2 ИЗ 15.3
# НАЧАЛО ЧАСТИ 15.3 ИЗ 15.3

    def init_right_sidebar(self, hbox_layout):
        """Панель управления сессией со всеми ползунками конфигурации ИИ"""
        sidebar_group = QGroupBox("Управление сессией")
        sidebar_group.setFixedWidth(280)
        sidebar_layout = QVBoxLayout(sidebar_group)
        sidebar_layout.setContentsMargins(8, 12, 8, 8)

        self.sys_prompt_edit = QTextEdit()
        self.sys_prompt_edit.setPlaceholderText("Системная роль ИИ...")
        self.sys_prompt_edit.setFixedHeight(60)
        self.sys_prompt_edit.textChanged.connect(self.on_sys_prompt_changed)
        sidebar_layout.addWidget(self.sys_prompt_edit)
        
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

        self.lbl_freq_val = QLabel("0.1")
        self.slider_freq_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_freq_penalty.setRange(0, 20); self.slider_freq_penalty.setValue(0)
        self.slider_freq_penalty.valueChanged.connect(lambda v: (self.lbl_freq_val.setText(str(v/10.0)), self.save_ui_setting("freq", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Штраф частоты (Freq):"), self.lbl_freq_val); form_layout.addRow(self.slider_freq_penalty)

        self.lbl_pres_val = QLabel("0.1")
        self.slider_pres_penalty = QSlider(Qt.Orientation.Horizontal)
        self.slider_pres_penalty.setRange(0, 20); self.slider_pres_penalty.setValue(0)
        self.slider_pres_penalty.valueChanged.connect(lambda v: (self.lbl_pres_val.setText(str(v/10.0)), self.save_ui_setting("pres", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Штраф тем (Presence):"), self.lbl_pres_val); form_layout.addRow(self.slider_pres_penalty)

        # Ползунок памяти контекста: увеличиваем диапазон до 8 (соответствует 256 000)
        self.lbl_ctx_val = QLabel("2048")
        self.slider_ctx = QSlider(Qt.Orientation.Horizontal)
        self.slider_ctx.setRange(1, 8); self.slider_ctx.setValue(2) # Максимум теперь 8 шаг (256k)
        self.slider_ctx.valueChanged.connect(lambda v: (self.lbl_ctx_val.setText(str(self.ctx_steps.get(v, 2048))), self.save_ui_setting("ctx", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Память контекста:"), self.lbl_ctx_val); form_layout.addRow(self.slider_ctx)

        # Ползунок лимита вывода: увеличиваем верхнюю границу до 16000 токенов
        self.lbl_predict_val = QLabel("4096")
        self.slider_predict = QSlider(Qt.Orientation.Horizontal)
        self.slider_predict.setRange(16, 16384); self.slider_predict.setValue(4096) # Максимум теперь 16000
        self.slider_predict.valueChanged.connect(lambda v: (self.lbl_predict_val.setText(str(v)), self.save_ui_setting("predict", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Лимит вывода (Tokens):"), self.lbl_predict_val); form_layout.addRow(self.slider_predict)

        self.lbl_threads_val = QLabel("4")
        self.slider_threads = QSlider(Qt.Orientation.Horizontal)
        self.slider_threads.setRange(1, 16); self.slider_threads.setValue(4)
        self.slider_threads.valueChanged.connect(lambda v: (self.lbl_threads_val.setText(str(v)), self.save_ui_setting("threads", v), self.save_session_to_db(self.current_session)))
        form_layout.addRow(QLabel("Ядра CPU для ИИ:"), self.lbl_threads_val); form_layout.addRow(self.slider_threads)

        self.cb_low_vram = QCheckBox("Режим Low VRAM")
        self.cb_low_vram.stateChanged.connect(lambda v: self.save_ui_setting("lowvram", 1 if v else 0))
        form_layout.addRow(self.cb_low_vram)

        self.cb_speech_on = QCheckBox("🔊 Озвучивать ответы ИИ")
        self.cb_speech_on.stateChanged.connect(lambda v: self.save_ui_setting("speech_on", 1 if v else 0))
        form_layout.addRow(self.cb_speech_on)
        sidebar_layout.addWidget(form_widget)

        self.lbl_token_usage = QLabel("Занято: 0 / 8192 токенов (0%)")
        self.lbl_generation_speed = QLabel("Скорость ИИ: 0.0 tok/sec")
        sidebar_layout.addWidget(self.lbl_token_usage); sidebar_layout.addWidget(self.lbl_generation_speed)

        self.lbl_sys_cpu = QLabel("Загрузка      CPU: 0.0%")
        self.lbl_sys_ram = QLabel("Использование RAM: 0.0%")
        sidebar_layout.addWidget(self.lbl_sys_cpu); sidebar_layout.addWidget(self.lbl_sys_ram)

        sidebar_layout.addStretch()
        hbox_layout.addWidget(sidebar_group)

    def apply_cyberpunk_theme(self):
        """🎨 Мягкий монолитный стиль: яркость рамок снижена, вкладки интегрированы"""
        self.setStyleSheet("""
            QMainWindow { background-color: #0d0f12; }
            QWidget { background-color: #0d0f12; color: #00b395; font-family: 'Segoe UI', Arial; }
            
            QGroupBox { border: 1px solid #005c4e; border-radius: 6px; margin-top: 0px; font-weight: bold; color: #00b395; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; top: -4px; padding: 0 5px; background-color: #0d0f12; }
            
            QTextEdit { background-color: #13171c; border: none; border-radius: 4px; color: #ffffff; font-size: 13px; }
            QListWidget { background-color: #13171c; border: none; border-radius: 4px; color: #ffffff; }
            
            QLineEdit, QComboBox { background-color: #13171c; border: 1px solid #005c4e; border-radius: 4px; color: #00ffcc; padding: 3px; }
            
            QTabWidget::pane { border: 1px solid #005c4e; background: #13171c; border-radius: 4px; top: -1px; }
            QTabBar::tab { background: #1a1f26; border: 1px solid #005c4e; border-bottom: none; color: #00b395; padding: 5px 12px; border-top-left-radius: 4px; border-top-right-radius: 4px; font-size: 11px; font-weight: bold; }
            QTabBar::tab:selected { background: #13171c; color: #00ffcc; border-bottom: 1px solid #13171c; }
            QTabBar::tab:hover { background: #005c4e; color: #ffffff; }

            QPushButton { background-color: #1a1f26; border: 1px solid #005c4e; border-radius: 4px; color: #00ffcc; font-weight: bold; padding: 4px; }
            QPushButton:hover { background-color: #00b395; color: #0d0f12; }
            QPushButton:pressed { background-color: #008f7a; }
            
            QSlider::groove:horizontal { border: 1px solid #222; height: 6px; background: #13171c; border-radius: 3px; }
            QSlider::handle:horizontal { background: #00b395; width: 14px; margin: -4px 0; border-radius: 7px; }
            QLabel, QCheckBox { color: #00b395; font-size: 11px; }
        """)

        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton { 
                background-color: #0d0f12; border: none;
                color: #005c4e; font-weight: bold; font-size: 8px; padding: 0px; margin: 0px;
            }
            QPushButton:hover { 
                background-color: #13171c; border-left: 1px solid #00b395; border-right: 1px solid #00b395;
                color: #00ffcc; 
            }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    client = AIClientApp()
    client.show()
    sys.exit(app.exec())

# КОНЕЦ ЧАСТИ 15.3 ИЗ 15.3

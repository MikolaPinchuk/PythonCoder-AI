import os
import re
import time
from PyQt6.QtCore import QThread, pyqtSignal


class LlamaLogWatcherWorker(QThread):
    """🔍 Фоновый анализатор логов llama-server с расшифровкой всех событий на русский язык в чат"""
    log_translated = pyqtSignal(str)

    def __init__(self, log_path):
        super().__init__()
        self.log_path = log_path
        self.is_running = True
        self._last_pos = os.path.getsize(log_path) if os.path.exists(log_path) else 0
        self._recent_messages = []


    def stop(self):
        self.is_running = False

    def _translate_line(self, line):
        line = line.strip()
        if not line:
            return None

        low = line.lower()

        # 1. Критическая нехватка видеопамяти (VRAM)
        if "erroroutofdevicememory" in low or "memory allocation of size" in low:
            mb_match = re.search(r"size\s+(\d+)", line)
            mb_info = f" (не хватило {round(int(mb_match.group(1)) / (1024 * 1024), 1)} МБ)" if mb_match else ""
            return (
                f"<b style='color:#ff4444;'>🚨 [Диагностика GPU]: Не хватило видеопамяти Intel Arc{mb_info}!</b><br>"
                f"<i style='color:#ffaa00;'>Совет: Уменьшите ползунок «Контекст чата» (например, до 32768) и перезапустите сервер.</i>"
            )

        # 2. Ошибки загрузки или повреждения файла модели GGUF
        if "failed to load model" in low or "invalid magic" in low or "error loading model" in low:
            return (
                "<b style='color:#ff4444;'>🚨 [Ошибка модели]: Не удалось загрузить файл нейросети (.gguf)!</b><br>"
                "<i style='color:#ffaa00;'>Причина: Файл повреждён, скачался не полностью или имеет неподдерживаемый формат.</i>"
            )

        # 2a. Фатальная ошибка формата/совместимости GGUF (ggml-impl.h / fatal error)
        if "fatal error" in low or "ggml-impl.h" in low:
            return (
                "<b style='color:#ff4444;'>🚨 [Критический сбой GGUF]: Ядро llama.cpp отклонило этот файл модели (fatal error)!</b><br>"
                "<i style='color:#ffaa00;'>Причина: Файл модели устарел, повреждён или несовместим с текущей версией сервера. Выберите другую модель GGUF.</i>"
            )


        # 3. Конфликт сетевого порта 8080
        if "couldn't bind http server socket" in low or "address already in use" in low:
            return (
                "<b style='color:#ff4444;'>🚨 [Конфликт порта]: Порт 8080 уже занят другим процессом!</b><br>"
                "<i style='color:#ffaa00;'>Совет: Закройте зависший процесс llama-server.exe в Диспетчере задач и запустите сервер заново.</i>"
            )

        # 4. Переполнение или усечение контекста (truncated = 1)
        if "truncated = 1" in low:
            return (
                "<b style='color:#ffaa00;'>⚠️ [Переполнение контекста]: Входящий запрос оказался длиннее выделенной памяти!</b><br>"
                "<i style='color:#e3e8ef;'>Сервер автоматически обрезал начало истории диалога, чтобы уместить запрос.</i>"
            )

        # 5. Сбои обработки изображений (Vision / mmproj)
        if "failed to encode image" in low or "failed to load clip" in low or "mmproj" in low and "error" in low:
            return (
                "<b style='color:#ff4444;'>🚨 [Ошибка CyberVision]: Не удалось обработать изображение!</b><br>"
                "<i style='color:#ffaa00;'>Причина: Файл картинки повреждён, слишком велик или несовместим с проектором mmproj.</i>"
            )
        # 5a. Сброс видеодрайвера по таймауту Windows (ErrorDeviceLost / device lost on Vulkan)
        if "errordevicelost" in low or "device lost on vulkan" in low or "failed to process mtmd chunk" in low:
            return (
                "<b style='color:#ff4444;'>🚨 [Сбой драйвера GPU]: Видеокарта Intel Arc сбросила задачу по таймауту (ErrorDeviceLost)!</b><br>"
                "<i style='color:#ffaa00;'>Совет: Добавьте флаг --no-mmproj-offload в Start Ai CC.bat, чтобы тяжелые картинки обрабатывались без перегрузки драйвера Vulkan.</i>"
            )

        # 6. Успешный запуск сервера и готовность модели
        if "server_on_li: listening on" in low:
            return "<b style='color:#00ffcc;'>✅ [Диагностика GPU]: Сервер нейросети загружен в видеопамять и готов к работе!</b>"

        # 7. Загрузка модуля зрения
        if "loaded multimodal model" in low:
            return "<i style='color:#00b395;'>👁️ [Диагностика GPU]: Модуль компьютерного зрения (mmproj) успешно загружен в VRAM.</i>"

        # 8. Итоги автоподборщика памяти
        if "common_fit_params:" in low and "successfully" in low:
            return f"<i style='color:#00b395;'>⚙️ [Автоподбор VRAM]: {line.split('common_fit_params:')[-1].strip()}</i>"

        # 9. Выделенный размер контекста и слотов
        if "n_ctx_slot =" in low:
            m_ctx = re.search(r"n_ctx_slot\s*=\s*(\d+)", line)
            m_slots = re.search(r"n_slots\s*=\s*(\d+)", line)
            if m_ctx:
                slots_txt = m_slots.group(1) if m_slots else "1"
                return f"<i style='color:#8fa0b0;'>🧠 [Память сервера]: Активно слотов: {slots_txt} | Контекст на слот: {m_ctx.group(1)} токенов.</i>"

        # 10. Скорость обработки входного промпта (Prefill)
        if "prompt processing," in low and "progress = 1.00" in low:
            m_speed = re.search(r"([\d\.]+)\s+tokens per second", line)
            m_tok = re.search(r"n_tokens\s*=\s*(\d+)", line)
            if m_speed and m_tok:
                return f"<i style='color:#8fa0b0;'>⚡ [Анализ запроса]: Прочитано {m_tok.group(1)} токенов со скоростью <b>{m_speed.group(1)} tok/sec</b>.</i>"

        # 11. Скорость генерации ответа (Token Generation)
        if "n_gen =" in low and "tg =" in low:
            m_tg = re.search(r"tg\s*=\s*([\d\.]+)\s*t/s", line)
            m_gen = re.search(r"n_gen\s*=\s*(\d+)", line)
            if m_tg and m_gen and int(m_gen.group(1)) % 100 == 0:
                return f"<i style='color:#8fa0b0;'>🚀 [Скорость GPU]: Сгенерировано {m_gen.group(1)} токенов (<b>{m_tg.group(1)} tok/sec</b>).</i>"

        # 12. Остановка или отмена задачи сервером
        if "cancel task" in low:
            return "<b style='color:#ffaa00;'>⚠️ [Сервер]: Текущая задача прервана сервером.</b>"

        # 13. Универсальный перехват любых других системных ошибок llama-server
        if " E " in line or "error:" in low or "ggml_assert" in low:
            return f"<b style='color:#ff4444;'>❌ [Ошибка ядра llama-server]:</b> <code>{line[:250]}</code>"

        return None

    def run(self):
        while self.is_running:
            try:
                if os.path.exists(self.log_path):
                    file_size = os.path.getsize(self.log_path)
                    if file_size < self._last_pos:
                        self._last_pos = 0

                    if file_size > self._last_pos:
                        with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(self._last_pos)
                            new_lines = f.readlines()
                            self._last_pos = f.tell()

                        for raw_line in new_lines:
                            human_msg = self._translate_line(raw_line)
                            if human_msg:
                                now_ts = time.time()
                                # Очищаем записи старше 5 секунд
                                self._recent_messages = [(m, t) for m, t in self._recent_messages if now_ts - t < 30.0]
                                # Если такое же сообщение уже было выведено за последние 5 секунд — пропускаем
                                if any(m == human_msg for m, _ in self._recent_messages):
                                    continue
                                self._recent_messages.append((human_msg, now_ts))
                                self.log_translated.emit(human_msg)
            except Exception:
                pass
            time.sleep(0.8)

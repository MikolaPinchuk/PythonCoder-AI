import os
import time
import logging
import requests
from collections import deque
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger("CyberCore.TelegramBridge")


class TelegramListenerWorker(QThread):
    """📡 Фоновый мост Telegram: Очередь задач + Разделение прав (Админ / Гость)"""
    command_received = pyqtSignal(str)
    status_log = pyqtSignal(str)

    def __init__(self, workspace_dir=None):
        super().__init__()
        self.is_running = True
        self.last_update_id = 0
        self.bot_token, self.admin_ids, self.guest_ids = self._load_config()
        
        if workspace_dir:
            self.workspace_dir = workspace_dir
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.workspace_dir = os.path.join(base_dir, "AI_Generated")
        os.makedirs(self.workspace_dir, exist_ok=True)
        
        self._whisper_model = None
        self.last_sender_id = self.admin_ids[0] if self.admin_ids else ""
        self.task_queue = deque()
        self.is_agent_busy = False
        self.pending_files = {}

        self.is_agent_busy = False

    def _load_config(self):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        raw_admins = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        raw_guests = os.environ.get("TELEGRAM_GUEST_IDS", "").strip()
        
        possible_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.txt"),
            os.path.join(os.getcwd(), "telegram_config.txt")
        ]
        for path in possible_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        for line in f:
                            line = line.strip()
                            if "=" in line and not line.startswith("#"):
                                k, v = line.split("=", 1)
                                k, v = k.strip(), v.strip().strip('"').strip("'")
                                if k == "TELEGRAM_BOT_TOKEN":
                                    token = v
                                elif k == "TELEGRAM_CHAT_ID":
                                    raw_admins = v
                                elif k == "TELEGRAM_GUEST_IDS":
                                    raw_guests = v
                    break
                except Exception:
                    pass
                    
        admins = [cid.strip() for cid in raw_admins.split(",") if cid.strip()]
        guests = [cid.strip() for cid in raw_guests.split(",") if cid.strip() and cid.strip() not in admins]
        return token, admins, guests

    def _api_url(self, method):
        s = chr(47)
        return "https:" + s + s + "api." + "telegram.org" + s + "b" + "ot" + self.bot_token + s + method

    def _set_active_chat(self, sender_id):
        self.last_sender_id = str(sender_id).strip()
        try:
            active_chat_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_tg_chat.txt")
            with open(active_chat_file, "w", encoding="utf-8") as af:
                af.write(self.last_sender_id)
        except Exception:
            pass

    def mark_task_finished(self):
        """Вызывается главным окном, когда агент закончил текущую задачу"""
        self.is_agent_busy = False

    def _enqueue_or_run(self, sender_id, role, prompt_text):
        """Ставит задачу в очередь, если агент занят, или запускает сразу"""
        if role == "guest":
            final_prompt = (
                "[ЗАПРОС ИЗ TELEGRAM | РЕЖИМ ГОСТЯ: ПОЛЬЗОВАТЕЛЬ НЕ ИМЕЕТ ПРАВ АДМИНИСТРАТОРА. "
                "ЗАПРЕЩЕНО ИСПОЛЬЗОВАТЬ ТЕРМИНАЛ, ФАЙЛОВУЮ СИСТЕМУ ПК И УПРАВЛЕНИЕ ОКНАМИ. "
                "ОТВЕЧАЙ КАК ПОМОЩНИК В ЧАТЕ И ОБЯЗАТЕЛЬНО ОТПРАВЬ ОТВЕТ ЧЕРЕЗ send_telegram_message]\n"
                f"Запрос гостя: {prompt_text}"
            )
        else:
            final_prompt = (
                "[ЗАПРОС ИЗ TELEGRAM — ПОСЛЕ ВЫПОЛНЕНИЯ ОБЯЗАТЕЛЬНО ОТПРАВЬ РЕЗУЛЬТАТ ЧЕРЕЗ send_telegram_message]\n"
                f"{prompt_text}"
            )

        if self.is_agent_busy:
            self.task_queue.append((sender_id, role, final_prompt))
            pos = len(self.task_queue)
            self.send_reply(
                f"⏳ Станция сейчас выполняет другую задачу. Ваш запрос поставлен в очередь (позиция: {pos}).",
                target_chat_id=sender_id
            )
        else:
            self.is_agent_busy = True
            self._set_active_chat(sender_id)
            self.command_received.emit(final_prompt)

    def _process_next_in_queue(self):
        """Запускает следующую задачу из очереди, если агент освободился"""
        if not self.is_agent_busy and len(self.task_queue) > 0:
            next_sender, next_role, next_prompt = self.task_queue.popleft()
            self.is_agent_busy = True
            self._set_active_chat(next_sender)
            self.send_reply("▶️ Ваша очередь подошла! Запускаю обработку запроса...", target_chat_id=next_sender)
            self.command_received.emit(next_prompt)
    def _download_tg_file(self, file_id, save_filename):
        try:
            resp = requests.get(self._api_url("getFile"), params={"file_id": file_id}, timeout=15).json()
            if not resp.get("ok"):
                return None
            file_path = resp["result"]["file_path"]
            s = chr(47)
            download_url = "https:" + s + s + "api." + "telegram.org" + s + "file" + s + "b" + "ot" + self.bot_token + s + file_path
            
            file_data = requests.get(download_url, timeout=30)
            if file_data.status_code == 200:
                safe_name = os.path.basename(save_filename)
                local_path = os.path.join(self.workspace_dir, safe_name)
                with open(local_path, "wb") as f:
                    f.write(file_data.content)
                return safe_name
        except Exception as e:
            logger.error(f"Ошибка скачивания файла из Telegram: {e}")
        return None

    def _transcribe_voice(self, local_filename):
        full_path = os.path.join(self.workspace_dir, local_filename)
        try:
            from faster_whisper import WhisperModel
            if self._whisper_model is None:
                self.status_log.emit("🎙️ [Telegram Bridge]: Загрузка модели Whisper в память...")
                self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            
            segments, _ = self._whisper_model.transcribe(full_path, beam_size=1)
            text = " ".join([seg.text.strip() for seg in segments]).strip()
            return text
        except Exception as e:
            logger.error(f"Ошибка Whisper: {e}")
            return None
        finally:
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception:
                pass

    def send_reply(self, text, target_chat_id=None):
        recipient = str(target_chat_id).strip() if target_chat_id else getattr(self, "last_sender_id", "")
        if not recipient and self.admin_ids:
            recipient = self.admin_ids[0]
        if not self.bot_token or not recipient:
            return
        try:
            requests.post(
                self._api_url("sendMessage"),
                json={"chat_id": recipient, "text": str(text)[:4000]},
                timeout=10
            )
        except Exception as e:
            logger.error(f"Ошибка отправки ответа в Telegram: {e}")

    def stop(self):
        self.is_running = False

    def run(self):
        if not self.bot_token or (not self.admin_ids and not self.guest_ids):
            self.status_log.emit("⚠️ [Telegram Bridge]: Файл telegram_config.txt не настроен, приём команд отключён.")
            return

        try:
            init_resp = requests.get(self._api_url("getUpdates"), params={"offset": -1, "timeout": 2}, timeout=5).json()
            res_list = init_resp.get("result", [])
            if init_resp.get("ok") and isinstance(res_list, list) and len(res_list) > 0:
                self.last_update_id = res_list[-1].get("update_id", 0)
        except Exception:
            pass

        self.status_log.emit(f"📡 [Telegram Bridge]: Активен! Админов: {len(self.admin_ids)}, Гостей: {len(self.guest_ids)}")
        self._is_offline = False

        while self.is_running:
            try:
                self._process_next_in_queue()

                resp = requests.get(
                    self._api_url("getUpdates"),
                    params={"offset": self.last_update_id + 1, "timeout": 5},
                    timeout=10
                )
                if resp.status_code != 200:
                    time.sleep(2)
                    continue
                
                data = resp.json()
                if not data.get("ok"):
                    time.sleep(2)
                    continue

                # Если связь только что восстановилась после обрыва — пишем в лог 1 раз
                if self._is_offline:
                    self._is_offline = False
                    self.status_log.emit("🟢 [Telegram Bridge]: Связь с сервером Telegram восстановлена!")

                for update in data.get("result", []):
                    self.last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    sender_id = str(msg.get("chat", {}).get("id", "")).strip()
                    if not sender_id:
                        continue

                    if sender_id in self.admin_ids:
                        role = "admin"
                    elif sender_id in self.guest_ids:
                        role = "guest"
                    else:
                        self.send_reply(f"⛔ Доступ закрыт. Ваш Chat ID: {sender_id}", target_chat_id=sender_id)
                        continue

                    text = str(msg.get("text", "")).strip()
                    caption = str(msg.get("caption", "")).strip()

                    if "voice" in msg or "audio" in msg:
                        media_obj = msg.get("voice") or msg.get("audio")
                        file_id = media_obj.get("file_id")
                        temp_name = f"tg_voice_{int(time.time())}.ogg"
                        self.send_reply("🎙️ Скачиваю и расшифровываю голосовое сообщение...", target_chat_id=sender_id)
                        saved = self._download_tg_file(file_id, temp_name)
                        if saved:
                            recognized_text = self._transcribe_voice(saved)
                            if recognized_text:
                                self.send_reply(f"📝 Распознано: «{recognized_text}»", target_chat_id=sender_id)
                                if sender_id in self.pending_files:
                                    attached = self.pending_files.pop(sender_id)
                                    recognized_text = f"[Прикреплён файл из Telegram в воркспейс: {attached}]\nЗадача пользователя: {recognized_text}"
                                self._enqueue_or_run(sender_id, role, recognized_text)
                            else:
                                self.send_reply("❌ Не удалось распознать речь.", target_chat_id=sender_id)
                        else:
                            self.send_reply("❌ Не удалось скачать голосовое сообщение.", target_chat_id=sender_id)
                        continue

                    if "photo" in msg and isinstance(msg["photo"], list):
                        best_photo = msg["photo"][-1]
                        file_id = best_photo.get("file_id")
                        photo_name = f"tg_photo_{int(time.time())}.jpg"
                        saved = self._download_tg_file(file_id, photo_name)
                        if saved:
                            if caption:
                                full_prompt = f"[Прикреплён файл из Telegram в воркспейс: {saved}]\nЗадача пользователя: {caption}"
                                self.send_reply(f"🖼️ Фото `{saved}` загружено. Запускаю задачу...", target_chat_id=sender_id)
                                self._enqueue_or_run(sender_id, role, full_prompt)
                            else:
                                self.pending_files[sender_id] = saved
                                self.send_reply(f"🖼️ Фото сохранено как `{saved}`.\n💬 Напишите текстом или продиктуйте голосом, что с ним сделать!", target_chat_id=sender_id)
                        else:
                            self.send_reply("❌ Не удалось скачать фото.", target_chat_id=sender_id)
                        continue

                    if "document" in msg:
                        doc_obj = msg["document"]
                        file_id = doc_obj.get("file_id")
                        orig_name = doc_obj.get("file_name") or f"tg_doc_{int(time.time())}.bin"
                        saved = self._download_tg_file(file_id, orig_name)
                        if saved:
                            if caption:
                                full_prompt = f"[Прикреплён файл из Telegram в воркспейс: {saved}]\nЗадача пользователя: {caption}"
                                self.send_reply(f"📎 Файл `{saved}` загружен. Запускаю задачу...", target_chat_id=sender_id)
                                self._enqueue_or_run(sender_id, role, full_prompt)
                            else:
                                self.pending_files[sender_id] = saved
                                self.send_reply(f"📎 Файл `{saved}` загружен в воркспейс.\n💬 Напишите текстом или продиктуйте голосом, что с ним сделать!", target_chat_id=sender_id)
                        else:
                            self.send_reply("❌ Не удалось скачать документ.", target_chat_id=sender_id)
                        continue

                    if not text or text == "/start":
                        role_label = "Администратор (полный доступ)" if role == "admin" else "Гость (безопасный режим чата)"
                        self.send_reply(f"🤖 CyberCore на связи!\nВаш статус: {role_label}.", target_chat_id=sender_id)
                        continue

                    if text.lower() == "/status":
                        q_len = len(self.task_queue)
                        busy_str = "Занят" if self.is_agent_busy else "Свободен"
                        self.send_reply(f"🟢 Станция онлайн | Статус: {busy_str} | В очереди: {q_len}", target_chat_id=sender_id)
                        continue

                    if sender_id in self.pending_files:
                        attached = self.pending_files.pop(sender_id)
                        text = f"[Прикреплён файл из Telegram в воркспейс: {attached}]\nЗадача пользователя: {text}"

                    self.send_reply(f"⚙️ Принял запрос:\n«{text}»", target_chat_id=sender_id)
                    self._enqueue_or_run(sender_id, role, text)

            except Exception as loop_err:
                if not self._is_offline:
                    self._is_offline = True
                    self.status_log.emit("⚠️ [Telegram Bridge]: Нет подключения к интернету. Перехожу в тихий режим ожидания сети...")
                time.sleep(5)

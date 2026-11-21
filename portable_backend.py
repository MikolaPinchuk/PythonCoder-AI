# ==================================================================================
# 🗂️ portable_backend.py - PART 1/2: NATIVE BATCH LAUNCH ENGINE
# ==================================================================================
import os
import sys
import time
import json
import logging
import subprocess
import socket
import urllib.request
import urllib.parse

logger = logging.getLogger("CyberCore.PortableBackend")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))

class PortableLlamaEngine:
    """🦾 Управляющий хаб автоматического запуска и пинга локального llama-server"""
    
    server_process = None
    current_loaded_model = None
    port = 8080 

    def __init__(self, relative_model_path=None, options=None):
        self.options = options if options else {}
        # Определяем корень, где лежит сам скрипт portable_backend.py
        self.project_root = os.path.dirname(os.path.abspath(__file__))
        
        # ЖЕСТКАЯ ПОРТАТИВНАЯ ПРИВЯЗКА К СЕРВЕРУ ПО НОВОМУ РЕГЛАМЕНТУ
        self.base_dir = os.path.normpath(os.path.join(self.project_root, "Model", "LLAMA CCP"))
        # Путь к папке с GGUF моделями внутри сервера
        self.models_dir = os.path.normpath(os.path.join(self.base_dir, "Model"))
        
        if relative_model_path:
            # Очищаем путь от старых префиксов папок, если они застряли в БД
            raw_path = str(relative_model_path).strip().replace("\\", "/")
            raw_path = raw_path.replace("Model/LLAMA CCP/Model/", "")
            raw_path = raw_path.replace("Model/Qwen3.5-9B-GGUF/", "")
            self.model_filename = raw_path
        else:
            self.model_filename = "Qwen3.5-9B-Q4_K_M.gguf"


    def start_server_if_needed(self, ui_callback=None):
        """🚀 ЗАПУСК СЕРВЕРА С ДИНАМИЧЕСКИМ ОПРЕДЕЛЕНИЕМ НАЛИЧИЯ ФАЙЛА ЗРЕНИЯ"""
        if self._check_server_alive():
            return True

        self.stop_server_process()
        
        # По умолчанию ставим "none" — если файла нет, запустимся как чистый текст
        mmproj_filename = "none"
        try:
            # Определяем точную подпапку, где лежит выбранная модель
            specific_model_dir = os.path.dirname(os.path.join(self.models_dir, self.model_filename))
            if os.path.exists(specific_model_dir):
                for f in os.listdir(specific_model_dir):
                    if f.lower().endswith(".gguf") and ("mmproj" in f.lower() or "projector" in f.lower()):
                        # Если нашли файл зрения, формируем его относительный путь для батника
                        if os.path.dirname(self.model_filename):
                            mmproj_filename = f"{os.path.dirname(self.model_filename)}/{f}"
                        else:
                            mmproj_filename = f
                        break
        except Exception as e:
            logger.error(f"Ошибка сканирования проекторов зрения: {e}")

        bat_path = os.path.join(self.base_dir, "Start Ai CC.bat")
        if not os.path.exists(bat_path):
            for f in os.listdir(self.base_dir):
                if f.lower().endswith(".bat"):
                    bat_path = os.path.join(self.base_dir, f)
                    break

        if not os.path.exists(bat_path):
            raise FileNotFoundError(f"Критическая ошибка: .bat файл запуска не найден в папке {self.base_dir}")

        if os.name == 'nt':
            win_model_path = self.model_filename.replace("/", os.sep)
            win_mmproj_path = mmproj_filename.replace("/", os.sep)
            
            # Нативно извлекаем значения всех стартовых ползунков из словаря опций
            ctx_value = str(self.options.get("num_ctx", 4096))
            threads_value = str(self.options.get("num_thread", 4))
            predict_value = str(self.options.get("num_predict", 4096))
            np_value = str(self.options.get("parallel_slots", 1))
            no_kv_value = str(self.options.get("no_kv_offload", 0))
            kv_compress_value = str(self.options.get("kv_compress", 0))
            
            # Упаковываем 8 аргументов для cmd.exe (%1..%8)
            cmd_args = [
                "cmd.exe", "/c", os.path.basename(bat_path), 
                win_model_path, win_mmproj_path, ctx_value, threads_value, predict_value,
                np_value, no_kv_value, kv_compress_value
            ]

            
            logger.info(f"🦾 [CyberCore Portable Boot]: Запуск {os.path.basename(bat_path)} | Context: {ctx_value} | Threads: {threads_value} | Predict: {predict_value} | Slots: {np_value} | KV_RAM: {no_kv_value}")
            
            PortableLlamaEngine.server_process = subprocess.Popen(
                cmd_args,
                cwd=self.base_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                stdout=None, stderr=None
            )

           
        else:
            if mmproj_filename == "none":
                cmd_str = f"./llama-server -m Model/{self.model_filename} -c 32768 --host 127.0.0.1 --port 8080"
            else:
                cmd_str = f"./llama-server -m Model/{self.model_filename} -c 32768 --host 127.0.0.1 --port 8080 --mmproj Model/{mmproj_filename}"
                
            PortableLlamaEngine.server_process = subprocess.Popen(
                cmd_str,
                shell=True, cwd=self.base_dir, stdout=None, stderr=None
            )

        return self._wait_for_server_boot(ui_callback)

    def _wait_for_server_boot(self, ui_callback=None):
        start_time = time.time()
        max_wait = 90
        while time.time() - start_time < max_wait:
            if self._check_server_alive():
                time.sleep(1.5)
                PortableLlamaEngine.current_loaded_model = self.model_filename
                return True
            time.sleep(1.0)
        self.stop_server_process()
        raise TimeoutError("Превышено время ожидания загрузки модели через .bat файл.")

    def _check_server_alive(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            result = s.connect_ex(('127.0.0.1', 8080))
            s.close()
            return result == 0
        except Exception:
            return False
# ==================================================================================
# 🗂️ portable_backend.py - PART 2/2: STREAM CHAT CONTOUR (FIXED 404 URL ENDPOINT)
# ==================================================================================
    def generate_chat_stream(self, messages):
        """🔥 ИСПРАВЛЕННЫЙ КОНТУР НАПРАВЛЕНИЯ ПАКЕТОВ: Потоковое извлечение токенов из сокета"""
        # ИСПОЛЬЗУЕМ СТРОКОВУЮ ПЕРЕМЕННУЮ ХОСТА ДЛЯ ЗАЩИТЫ ОТ КУПЮР И СРЕЗОВ СЕТИ
        BASE_CHAT_IP = "http://127.0.0.1:8080"
        
        # Нативный эндпоинт чат-инференса для современных бинарников llama.cpp
        target_url = f"{BASE_CHAT_IP}/v1/chat/completions"
        
        if not self._check_server_alive():
            try: self.start_server_if_needed()
            except Exception as e:
                yield f"❌ [Бэкенд]: Не удалось реанимировать llama-server: {e}"
                return

# СТАЛО:
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                # Если в сообщении присутствует нативный Base64-массив картинок от CyberVision
                if "images" in msg and msg["images"]:
                    content_list = [{"type": "text", "text": msg.get("content", "")}]
                    for b64_img in msg["images"]:
                        content_list.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                        })
                    formatted_messages.append({
                        "role": msg.get("role", "user"),
                        "content": content_list
                    })
                else:
                    formatted_messages.append(msg)
            elif isinstance(msg, (list, tuple)) and len(msg) >= 2:
                formatted_messages.append({"role": str(msg[0]), "content": str(msg[1])})
            else:
                formatted_messages.append({"role": "user", "content": str(msg)})

        payload = {
            "messages": formatted_messages,
            "stream": True,
            "temperature": float(self.options.get("temperature", 0.7)),
            "top_p": float(self.options.get("top_p", 0.9)),
            "top_k": int(self.options.get("top_k", 40)),
            "mirostat": int(self.options.get("mirostat", 0)),
            "repeat_penalty": float(self.options.get("repeat_penalty", 1.1)),
            "frequency_penalty": float(self.options.get("frequency_penalty", 0.0)),
            "presence_penalty": float(self.options.get("presence_penalty", 0.0)),
            "max_tokens": int(self.options.get("num_predict", 4096)),
            "chat_template_kwargs": {
                "enable_thinking": bool(self.options.get("enable_thinking", False))
            },
            "n_predict": int(self.options.get("num_predict", 4096)),
            "stop": ["<|im_end|>", "<|im_start|>", "<|endoftext|>"]
        }



        try:
            req_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(target_url, data=req_data, method="POST")
            req.add_header('Content-Type', 'application/json')
            req.add_header('Accept', 'text/event-stream')
            req.add_header('Authorization', 'Bearer no-key')
            req.add_header('Origin', BASE_CHAT_IP)
            req.add_header('User-Agent', 'Mozilla/5.0')

            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)

            with opener.open(req, timeout=None) as response:
                for line in response:
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if not line_str or not line_str.startswith("data:"):
                        continue
                    data_content = line_str[5:].strip()
                    if data_content == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_content)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if not token and "reasoning_content" in delta:
                            token = delta.get("reasoning_content", "")
                        if token:
                            yield token
                    except Exception:
                        continue
        except Exception as e:
            # Автоматический горячий фоллбэк на эндпоинт старых версий бинарников при 404 ошибке
            if "404" in str(e):
                try:
                    fallback_url = f"{BASE_CHAT_IP}/chat-completions"
                    req_fb = urllib.request.Request(fallback_url, data=req_data, method="POST")
                    req_fb.add_header('Content-Type', 'application/json')
                    with opener.open(req_fb, timeout=None) as response_fb:
                        for line in response_fb:
                            line_str = line.decode('utf-8', errors='ignore').strip()
                            if line_str.startswith("data:"):
                                chunk_json = json.loads(line_str[5:].strip())
                                token = chunk_json.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if token: yield token
                except Exception as ex_fb:
                    yield f"\n❌ [Ошибка эндпоинта чата]: {ex_fb}"
            else:
                yield f"\n❌ [Ошибка сетевого контура портативного ядра]: {e}"

    def stop_server_process(self):
        """🧹 Кроссплатформенный сброс дескрипторов ядра для предотвращения зомби-процессов и блокировки порта 8080"""
        try:
            import subprocess
            if os.name == 'nt':
                # Контур очистки для ОС Windows
                subprocess.run("taskkill /f /t /im llama-server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("taskkill /f /t /im llama-server", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("taskkill /f /t /im server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Универсальный контур очистки для UNIX-систем (Linux / macOS)
                subprocess.run("pkill -f llama-server", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run("pkill -f server.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"⚠️ [PortableBackend]: Ошибка выгрузки серверных ядер ОС: {e}")
            
        PortableLlamaEngine.server_process = None
        PortableLlamaEngine.current_loaded_model = None


    @staticmethod
    def get_local_gguf_models():
        project_root = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.normpath(os.path.join(project_root, "Model", "LLAMA CCP", "Model"))
        if not os.path.exists(target_dir):
            return []
        detected_models = []
        try:
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    if file.lower().endswith(".gguf") and "mmproj" not in file.lower() and "projector" not in file.lower():
                        # Вычисляем относительный путь от папки Model
                        rel_path = os.path.relpath(os.path.join(root, file), target_dir)
                        # Заменяем слэши на прямые, чтобы батник cmd.exe адекватно их воспринимал
                        detected_models.append(rel_path.replace("\\", "/"))
        except Exception:
            pass
        return sorted(list(set(detected_models)))

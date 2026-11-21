import os
import sys
import re
import logging
import warnings
import time
import json
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import QApplication, QProgressDialog

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
os.environ["PYTHONWARNINGS"] = "ignore"

sys.modules['pynvml'] = None
sys.modules['nvidia'] = None

import torch
torch.cuda.is_available = lambda: False
torch.cuda.device_count = lambda: 0

from diffusers import StableDiffusionPipeline
from diffusers.loaders import FromSingleFileMixin

logger = logging.getLogger("CyberCore.ImageGen")

class ImageGenerationExpert:
    """🌐 Модуль автоматического перевода промптов через локальный портативный llama-server"""
    @staticmethod
    def translate_prompt_via_ollama(russian_text, model_name="Qwen3.5-9B-Q4_K_M.gguf", is_portable=True):
        print("\n" + "="*70)
        print(f"📡 [DEBUG TRANSLATE]: Вход в метод перевода. Промпт: '{russian_text}'")
        print("="*70)
        
        if len(re.findall(r'[a-zA-Z]{3,}', str(russian_text))) > 2:
            print(" -> [DEBUG TRANSLATE]: Обнаружена латиница (>2 слов). Возврат без перевода.")
            return str(russian_text).strip()

        BASE_URL_IP = "http://127.0.0.1:8080"
        url_health = f"{BASE_URL_IP}/health"
        url_llama = f"{BASE_URL_IP}/completion"
        
        retry_count = 0
        while True:
            try:
                req_health = urllib.request.Request(url_health, method="GET")
                req_health.add_header('User-Agent', 'Mozilla/5.0')
                with urllib.request.urlopen(req_health, timeout=2) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                retry_count += 1
                if retry_count % 4 == 0:
                    print(f" -> [DEBUG TRANSLATE]: Сервер на порту 8080 всё еще занят или загружается... Ждем (Попытка {retry_count}).")
            time.sleep(0.5)

        # ХИТРЫЙ ХАК: Заканчиваем блок assistant закрытием тега </think>
        # Это заставляет модель пропустить стадию размышлений и сразу писать перевод!
        full_raw_prompt = (
            f"<|im_start|>system\n"
            f"You are a precise Russian-to-English translation API. Translate the user text into English tags for Stable Diffusion prompts. "
            f"Provide ONLY the final translation line. No quotes, no formatting.\n"
            f"<|im_end|>\n"
            f"<|im_start|>user\n{russian_text}\n"
            f"<|im_end|>\n"
            f"<|im_start|>assistant\n"
            f"<think>\nShort translation process\n</think>\n"
        )

        payload = {
            "prompt": full_raw_prompt,
            "temperature": 0.0,
            "n_predict": 256,    # Увеличиваем запас токенов
            "stream": False,
            "cache_prompt": True,
            "stop": ["<|im_end|>", "<|im_start|>", "\n\n", "User:"]
        }

        try:
            req_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = urllib.request.Request(url_llama, data=req_data, method="POST")
            req.add_header('Content-Type', 'application/json')
            
            with urllib.request.urlopen(req, timeout=20) as response:
                res_json = json.loads(response.read().decode('utf-8'))
                raw_content = res_json.get("content", "").strip()
                print(f" -> [DEBUG TRANSLATE]: Сырой вывод модели:\n{raw_content}")

                if "</think>" in raw_content:
                    raw_content = raw_content.split("</think>")[-1].strip()

                clean_content = re.sub(r'```[a-zA-Z0-9]*', '', raw_content)
                clean_content = clean_content.replace('"', '').replace("'", "").replace("`", "").strip()
                clean_content = re.sub(r'(?i)^(translation|prompt|english|text|result|output|translation:)\s*', '', clean_content).strip()

                print(f" -> [DEBUG TRANSLATE]: Финальный отпарсенный результат: '{clean_content}'")
                
                if clean_content and len(clean_content) > 1 and re.search(r'[a-zA-Z]{2,}', clean_content):
                    return clean_content
                else:
                    return russian_text
                    
        except Exception as e:
            print(f"💥 [CRITICAL TRANSLATE CRASH]: Полный сетевой отказ контура перевода: {e}")
            return russian_text

    @staticmethod
    def clean_translated_prompt(text, fallback):
        text = re.sub(r'```[a-zA-Z0-9]*', '', text) 
        text = text.replace('"', '').replace("'", "").strip()
        text = re.sub(r'(?i)^(here is the translation:|translation:|english prompt:)\s*', '', text)
        if not re.search(r'[a-zA-Z]{2,}', text):
            return fallback
        return text
class LocalDiffusionWorker(QThread):
    """⏳ Безопасный изолированный поток инференса Stable Diffusion на CPU"""
    status_update = pyqtSignal(str)
    generation_finished = pyqtSignal(bool, str, str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.project_root = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        # Жесткая привязка к портативной директории весов
        self.base_dir = os.path.normpath(os.path.join(self.project_root, "Model", "Image_Gen"))
        
        def get_clean_arg(index, key, default=""):
            if key in kwargs: return kwargs[key]
            if len(args) > index:
                val = args[index]
                return val[0] if isinstance(val, (list, tuple)) and len(val) > 0 else val
            return default

        self.model_dir = str(get_clean_arg(0, "model_dir")).strip()
        self.raw_prompt = str(get_clean_arg(1, "prompt")).strip()
        self.raw_negative_prompt = str(kwargs.get("negative_prompt", kwargs.get("negative", get_clean_arg(2, "negative_prompt")))).strip()
        self.width = int(get_clean_arg(3, "width", 512))
        self.height = int(get_clean_arg(4, "height", 512))
        self.steps = int(get_clean_arg(5, "steps", 15))
        self.cfg = float(get_clean_arg(6, "cfg", 7.0))
        self.seed = int(get_clean_arg(7, "seed", -1))
        self.output_path = str(get_clean_arg(8, "output_path")).strip()
        self.ollama_model = str(get_clean_arg(9, "ollama_model", "Qwen3.5-9B-Q4_K_M.gguf")).strip()
        self.is_portable = True

        self.safetensors_file = "photon_v1.safetensors"
        if any(x in self.model_dir.lower() for x in ["1-5", "pruned", "trinart"]):
            self.safetensors_file = os.path.basename(self.model_dir) if self.model_dir.lower().endswith((".ckpt", ".safetensors")) else "v1-5-pruned-emaonly.safetensors"

    def run(self):
        """🚀 Отладочный запуск генерации Stable Diffusion на CPU (Portable Edition)"""
        # === АВТОРСКИЙ ПАТЧ-ФИКС ДЛЯ ЗАЩИТЫ ЛИМИТА 77 ТОКЕНОВ CLIP ===
        clean_prompt = str(self.raw_prompt).strip()
        
        # Очищаем промпт от случайных русских команд агента и JSON-мусора
        clean_prompt = re.sub(r'(?i).*?(генерации|промпт|prompt|generate|image|diffusion)[:\s]*', '', clean_prompt)
        clean_prompt = re.sub(r'[{}\[\]"\'`]', '', clean_prompt).strip()
        
        # Если промпт слишком длинный для CLIP, мягко обрезаем его до 30 ключевых слов
        if len(clean_prompt.split()) > 35:
            clean_prompt = ", ".join(clean_prompt.split()[:30])

        print("\n" + "═"*70)
        print("🤖 [WORKER DEBUG]: Запущен поток LocalDiffusionWorker.run()")
        print(f" -> Рабочий промпт для CLIP: '{clean_prompt}'")
        print("═"*70)

        try:
            # === ШАГ 1: ФИКСАЦИЯ ПРОМПТА ===
            print("\n📢 [WORKER DEBUG]: ШАГ 1/5 - Фиксация промпта...")
            translated_prompt = clean_prompt # Используем очищенный промпт

            # === 🔥 ШАГ 2: ВЫГРУЗКА ПАМЯТИ ТЕКСТОВОГО ЯДРА ===
            print("\n📢 [WORKER DEBUG]: ШАГ 2/5 - Выгрузка llama-server для освобождения ресурсов...")
            try: self.status_update.emit("🧹 [Память]: Выгружаю текстовое ядро из ОЗУ...")
            except Exception: pass
            
            from portable_backend import PortableLlamaEngine
            cleaner = PortableLlamaEngine()
            print(" -> [WORKER DEBUG]: Вызов метода stop_server_process()...")
            cleaner.stop_server_process()
            print(" -> [WORKER DEBUG]: Процесс остановлен. Пауза 3.0 сек для очистки ОЗУ...")
            time.sleep(3.0)

            # === ШАГ 3: ПОДГОТОВКА И ЗАГРУЗКА ВЕСОВ PYTORCH ===
            print("\n📢 [WORKER DEBUG]: ШАГ 3/5 - Инициализация PyTorch и загрузка .safetensors...")
            try: self.status_update.emit("📦 [Ядро PyTorch]: Загрузка весов и компонентов в ОЗУ...")
            except Exception: pass
            
            src_model_path = os.path.join(self.base_dir, self.safetensors_file)
            print(f" -> [WORKER DEBUG]: Физический путь к модели: '{src_model_path}'")
            print(" -> [WORKER DEBUG]: Вызов StableDiffusionPipeline.from_single_file()...")
            
            pipe = None
            if hasattr(StableDiffusionPipeline, "from_single_file"):
                try: 
                    pipe = StableDiffusionPipeline.from_single_file(
                        src_model_path, torch_dtype=torch.float32, 
                        local_files_only=True, safety_checker=None, load_safety_checker=False
                    )
                    print(" -> [WORKER DEBUG]: Пайплайн успешно собран через нативный single_file метод.")
                except Exception as ex_pipe1: 
                    print(f" -> [WORKER DEBUG]: Первый метод загрузки отклонен: {ex_pipe1}")
                    pipe = None

            if pipe is None:
                print(" -> [WORKER DEBUG]: Попытка альтернативной загрузки через FromSingleFileMixin...")
                pipe = FromSingleFileMixin.from_single_file(
                    StableDiffusionPipeline, pretrained_model_link_or_path=src_model_path, 
                    torch_dtype=torch.float32, local_files_only=True
                )
                print(" -> [WORKER DEBUG]: Пайплайн собран через альтернативный миксин.")
            
            print(" -> [WORKER DEBUG]: Отключение safety_checker и перенос пайплайна на CPU...")
            pipe.safety_checker = None
            pipe = pipe.to("cpu")
            pipe.set_progress_bar_config(disable=True)
            pipe.enable_attention_slicing()
            print(" -> [WORKER DEBUG]: Пайплайн полностью готов к инференсу на CPU.")
            
            # === ШАГ 4: СИНТЕЗ ПИКСЕЛЕЙ (ИНФЕРЕНС) ===
            print("\n📢 [WORKER DEBUG]: ШАГ 4/5 - Запуск математического расчета денойзинга...")
            if self.seed <= 0:
                import random
                self.seed = random.randint(1, 1000000000)
            generator = torch.Generator(device="cpu").manual_seed(self.seed)

            with torch.no_grad():
                output = pipe(
                    prompt=translated_prompt, negative_prompt=self.raw_negative_prompt, 
                    width=self.width, height=self.height, num_inference_steps=self.steps, 
                    guidance_scale=self.cfg, generator=generator
                )
                images = output.images

            if not self.output_path:
                self.output_path = os.path.normpath(os.path.join(os.getcwd(), "AI_Generated", f"render_{self.seed}.png"))

            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            if images and len(images) > 0:
                images[0].save(self.output_path)
                print(" -> [WORKER DEBUG]: Файл физически сохранен на жесткий диск ПК.")

            final_clean_path = os.path.normpath(self.output_path)

            # === ШАГ 5: СИНТЕЗ ЗАВЕРШЕН, ВОССТАНАВЛИВАЕМ ТЕКСТОВОЕ ЯДРО ===
            print("\n📢 [WORKER DEBUG]: ШАГ 5/5 - Автоматический перезапуск llama-server...")
            try: 
                self.status_update.emit("♻️ [Ресурсы]: Картинка готова. Возвращаю текстовую модель в ОЗУ...")
            except Exception: 
                pass
            
            # Нормализуем путь перед отправкой сигнала
            final_clean_path = os.path.normpath(self.output_path)
            
            # Поднимаем текстовое ядро GGUF с реальными настройками ползунков
            try:
                from portable_backend import PortableLlamaEngine
                clean_model_name = str(self.ollama_model).strip().replace("\\", "/").replace("Model/LLAMA CCP/Model/", "").replace("Model/LLAMA CCP/", "") if not str(self.ollama_model).strip().startswith("Model/") else str(self.ollama_model).strip().replace("\\", "/").replace("Model/LLAMA CCP/Model/", "").replace("Model/LLAMA CCP/", "")[6:]

                restore_opts = dict(getattr(self, "options", {}))
                if not restore_opts:
                    try:
                        import json
                        cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cybercore_settings.json")
                        if os.path.exists(cfg_file):
                            with open(cfg_file, "r", encoding="utf-8") as cf:
                                restore_opts = json.load(cf)
                    except Exception:
                        pass

                engine_restore = PortableLlamaEngine(
                    relative_model_path=clean_model_name, 
                    options=restore_opts
                )
                engine_restore.start_server_if_needed()
                print(f" -> [WORKER DEBUG]: Локальный llama-server успешно реанимирован с параметрами: {restore_opts}")
            except Exception as ex_res:
                print(f" -> [WORKER DEBUG]: Предупреждение авто-подъема сервера: {ex_res}")


            print("\n📢 [WORKER DEBUG]: Сигнал generation_finished отправлен в Main Thread.")
            print("═"*70 + "\n")
            self.generation_finished.emit(True, final_clean_path, translated_prompt)
            
        except Exception as e:
            print(f"\n💥 [WORKER CRASH]: Обнаружена критическая ошибка инференса: {e}")
            # На случай падения конвейера также пытаемся поднять текстовый сервер

import os
import sys
import base64
import cv2
import logging
from PyQt6.QtCore import QThread, pyqtSignal

# Регистрация модуля в сквозной киберпанк-системе логирования
logger = logging.getLogger("CyberCore.Media")

class OCRWorker(QThread):
    """🔤 Фоновый поток для пакетного OCR-распознавания без блокировки интерфейса"""
    file_processed = pyqtSignal(str, str, str) # (имя_файла, статус_текст, распознанный_контент)
    all_finished = pyqtSignal(int)             # количество успешно обработанных файлов

    def __init__(self, file_paths, workspace_dir):
        super().__init__()
        self.file_paths = file_paths
        self.workspace_dir = workspace_dir

    def run(self):
        processed_count = 0
        logger.info(f"Запуск фонового OCRWorker для пакета из {len(self.file_paths)} файлов.")
        for path in self.file_paths:
            if not os.path.exists(path):
                logger.warning(f"OCR Направление пропущено: файл не существует {path}")
                continue
                
            filename = os.path.basename(path)
            
            # ГАРАНТИРОВАННАЯ ИНИЦИАЛИЗАЦИЯ ПЕРЕМЕННОЙ В НАЧАЛЕ ИТЕРАЦИИ ЦИКЛА
            recognized_content = "" 
            
            report = MediaProcessor.run_ocr_recognition(path, self.workspace_dir)
            
            if "создан документ" in report.lower() or "успешно извлечен" in report.lower():
                base_name, _ = os.path.splitext(filename)
                created_txt_path = os.path.normpath(os.path.join(self.workspace_dir, f"{base_name}-OCR.txt"))
                if os.path.exists(created_txt_path):
                    with open(created_txt_path, "r", encoding="utf-8", errors="ignore") as f:
                        recognized_content = f.read()
                processed_count += 1
                
            # Теперь переменная гарантированно существует и поток никогда не упадет
            self.file_processed.emit(filename, report, recognized_content)
            
        logger.info(f"OCRWorker успешно завершил пакетную обработку. Успешно: {processed_count}")
        self.all_finished.emit(processed_count)



class MediaProcessor:
    """🎬 МОДУЛЬ ДЛЯ ОБРАБОТКИ МЕДИАФАЙЛОВ, СИНТЕЗА ИИ-АНАЛИЗА И ЛОКАЛЬНОГО EasyOCR"""
    
    @staticmethod
    def process_image(file_path):
        """🖼️ Безопасное чтение картинки и кодирование в Base64 с логированием сбоев"""
        try:
            if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
                logger.warning(f"Ошибка process_image: невалидный путь к файлу '{file_path}'")
                return None
            with open(file_path, "rb") as img_f:
                return base64.b64encode(img_f.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Критическая ошибка кодирования изображения {file_path}: {str(e)}", exc_info=True)
            return None
    @staticmethod
    def extract_frames_from_video(video_path, max_frames=4):
        """🎬 Разрезает видеофайл на ключевые кадры и кодирует их в Base64"""
        encoded_frames = []
        try:
            if not video_path or not os.path.exists(video_path):
                logger.warning(f"Ошибка extract_frames: видео не найдено по пути '{video_path}'")
                return encoded_frames
                
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error(f"Не удалось открыть видеопоток OpenCV для файла: {video_path}")
                return encoded_frames
                
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                return encoded_frames

            step = max(1, total_frames // max_frames)
            frame_count = 0
            
            while len(encoded_frames) < max_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count)
                ret, frame = cap.read()
                if not ret:
                    break

                resized_frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
                success, encoded_image = cv2.imencode('.jpg', resized_frame)
                if success:
                    encoded_frames.append(base64.b64encode(encoded_image).decode('utf-8'))

                frame_count += step
                if frame_count >= total_frames:
                    break

            cap.release()
            logger.info(f"Успешная раскадровка видео {os.path.basename(video_path)}. Извлечено кадров: {len(encoded_frames)}")
        except Exception as e:
            logger.error(f"Ошибка OpenCV при раскадровке {video_path}: {str(e)}", exc_info=True)
            
        return encoded_frames

    @staticmethod
    def prepare_vision_context(media_path):
        """🧠 Создает структурированный медиа-контекст (изображения + текстовая директива)"""
        images_data = []
        directive_text = ""
        
        if not media_path or not os.path.exists(media_path) or not os.path.isfile(media_path):
            return images_data, directive_text

        file_name = os.path.basename(media_path)
        ext = os.path.splitext(file_name)[1].lower().strip()

        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
            b64 = MediaProcessor.process_image(media_path)
            if b64:
                images_data.append(b64)
                directive_text = f"\n[ВИЗУАЛЬНЫЙ КОНТЕКСТ]: К запросу прикреплено изображение '{file_name}'. Проанализируй его внутренними графическими слоями и дай подробный ответ, что на нем находится.\n"
        elif ext in [".mp4", ".avi", ".mkv"]:
            frames = MediaProcessor.extract_frames_from_video(media_path, max_frames=4)
            if frames:
                images_data.extend(frames)
                directive_text = f"\n[ВИЗУАЛЬНЫЙ КОНТЕКСТ]: К запросу прикреплена серия из {len(frames)} кадров видео '{file_name}'. Проанализируй раскадровку.\n"

        return images_data, directive_text

    @staticmethod
    def run_ocr_recognition(image_path, workspace_dir):
        """📝 Быстрое распознавание текста офлайн-методом EasyOCR с сохранением в -OSR.txt"""
        if not image_path or not os.path.exists(image_path):
            return "[Ошибка]: Исходный файл изображения для OCR не найден."
        try:
            import warnings
            warnings.filterwarnings("ignore", category=UserWarning)
            warnings.filterwarnings("ignore", category=FutureWarning)
            
            import easyocr
            import torch
            
            cuda_available = torch.cuda.is_available()
            local_model_dir = os.path.abspath(os.path.join(os.getcwd(), "EasyOCR", "model"))
            os.makedirs(local_model_dir, exist_ok=True)
            
            try:
                reader = easyocr.Reader(
                    ['ru', 'en'], 
                    gpu=cuda_available, 
                    model_storage_directory=local_model_dir,
                    download_enabled=False 
                ) 
            except Exception:
                logger.info("Локальные веса EasyOCR не найдены в кэше, запуск стандартного фоллбэк-детектора.")
                reader = easyocr.Reader(['ru', 'en'], gpu=cuda_available)
      

            base_name, _ = os.path.splitext(os.path.basename(image_path))
            output_filename = f"{base_name}-OSR.txt"
            final_txt_path = os.path.normpath(os.path.join(workspace_dir, output_filename))

            ocr_results = reader.readtext(image_path, detail=0)
            
            if not ocr_results:
                logger.info(f"OCR: Внутри файла '{os.path.basename(image_path)}' текст отсутствует.")
                return f"⚠️ Внутри файла '{os.path.basename(image_path)}' текст не обнаружен."
                
            combined_text = "\n".join(ocr_results).strip()
            
            os.makedirs(workspace_dir, exist_ok=True)
            with open(final_txt_path, "w", encoding="utf-8") as txt_f:
                txt_f.write(combined_text)
                
            device_used = "GPU (Ускорение)" if cuda_available else "CPU (Базовый)"
            logger.info(f"Успешный OCR-анализ для {os.path.basename(image_path)} через {device_used}")
            return f"🟢 Текст успешно извлечен ({device_used}) -> Создан документ: {output_filename}"
        except ImportError:
            logger.error("Критический сбой импорта: easyocr или torch отсутствуют в venv!")
            return "[Ошибка]: Библиотеки 'easyocr' или 'torch' не установлены в вашем venv."
        except Exception as ocr_err:
            logger.error(f"[Сбой OCR-модуля]: {str(ocr_err)}", exc_info=True)
            return f"[Сбой OCR-модуля]: {str(ocr_err)}"

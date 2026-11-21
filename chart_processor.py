# ==================================================================================
# 🗂️ chart_processor.py - МОДУЛЬ ГЕНЕРАЦИИ, ВИЗУАЛИЗАЦИИ И ЭКСПОРТА ГРАФИКОВ (ЧАСТЬ 1)
# ==================================================================================
import os
import base64
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtGui import QPixmap

class ChartProcessor:
    """🛠️ Нативный изолированный процессор для работы с графикой, диаграммами и Matplotlib"""
    
    @staticmethod
    def file_to_html_img(file_path, width=500):
        """📂 Конвертирует физический PNG/JPG график с диска в легкий Base64 HTML-тег для чата"""
        if not file_path or not os.path.exists(file_path):
            return ""
        try:
            with open(file_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            
            ext = os.path.splitext(file_path)[1].lower().replace(".", "")
            if ext not in ["png", "jpg", "jpeg", "webp"]:
                ext = "png"
                
            # Возвращаем готовый HTML-контейнер со встроенным контекстным меню сохранения
            return f'<br><img src="data:image/{ext};base64,{encoded_string}" width="{width}" style="border:1px solid #005c4e; border-radius:6px; margin:5px 0;"><br>'
        except Exception as e:
            return f"<b style='color:red;'>[Ошибка рендеринга изображения]: {str(e)}</b>"

    @staticmethod
    def save_chart_to_disk(parent_widget, source_file_path):
        """💾 Открывает диалог проводника и безопасно сохраняет сгенерированный график в любую папку ПК"""
        if not source_file_path or not os.path.exists(source_file_path):
            QMessageBox.warning(parent_widget, "Экспорт графики", "Исходный файл графика не найден на диске.")
            return False
            
        default_name = os.path.basename(source_file_path)
        target_path, _ = QFileDialog.getSaveFileName(
            parent_widget, 
            "Сохранить график / изображение", 
            os.path.join(os.path.expanduser("~"), "Desktop", default_name),
            "Изображения (*.png *.jpg *.jpeg);;Все файлы (*.*)"
        )
        
        if not target_path:
            return False  # Пользователь нажал Отмена
            
        try:
            import shutil
            shutil.copy2(source_file_path, target_path)
            QMessageBox.information(parent_widget, "Успех", f"Изображение успешно сохранено по пути:\n{target_path}")
            return True
        except Exception as e:
            QMessageBox.critical(parent_widget, "Ошибка сохранения", f"Не удалось скопировать файл:\n{str(e)}")
            return False
    @staticmethod
    def generate_chart_from_data(workspace_dir, chart_type, title, labels, values, filename="chart_output.png"):
        """📈 Создает и сохраняет на диск графики (Matplotlib Agg) без открытия лишних окон"""
        try:
            import matplotlib
            matplotlib.use('Agg')  # Жесткий фикс: блокируем вызов графических окон Matplotlib
            import matplotlib.pyplot as plt
            
            # Установка темного стиля под киберпанк-интерфейс программы
            plt.figure(figsize=(7, 4), facecolor='#0d0f12')
            ax = plt.axes()
            ax.set_facecolor('#13171c')
            
            # Настройка цветов осей и текста
            ax.spines['bottom'].set_color('#005c4e')
            ax.spines['top'].set_color('#005c4e')
            ax.spines['left'].set_color('#005c4e')
            ax.spines['right'].set_color('#005c4e')
            ax.tick_params(colors='#00b395', which='both')
            ax.xaxis.label.set_color('#00b395')
            ax.yaxis.label.set_color('#00b395')
            
            # 1. СТОЛБЧАТАЯ ДИАГРАММА
            if chart_type == "bar":
                bars = plt.bar(labels, values, color='#00ffcc', edgecolor='#00b395')
                
            # 2. ЛИНЕЙНЫЙ ГРАФИК
            elif chart_type == "line":
                plt.plot(labels, values, color='#ff0055', marker='o', linewidth=2, markersize=6)
                plt.grid(True, color='#1a1f26', linestyle='--')
                
            # 3. КРУГОВАЯ ДИАГРАММА
            elif chart_type == "pie":
                plt.pie(values, labels=labels, colors=['#00ffcc', '#ff0055', '#ffaa00', '#00b395', '#9900ff'], 
                        textprops={'color': "#00ffcc"}, wedgeprops={'edgecolor': '#0d0f12'})
            
            plt.title(title, color='#00ffcc', fontsize=12, fontweight='bold', pad=10)
            plt.tight_layout()
            
            # Сохранение физического файла на жесткий диск
            os.makedirs(workspace_dir, exist_ok=True)
            final_path = os.path.normpath(os.path.join(workspace_dir, filename))
            plt.savefig(final_path, dpi=120, facecolor='#0d0f12')
            plt.close()
            
            return final_path
        except Exception as e:
            print(f"Ошибка компиляции Matplotlib: {e}")
            return None

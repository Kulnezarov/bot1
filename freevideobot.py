import telebot
import yt_dlp
import os
import time
import subprocess
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Рекомендуется хранить токен в переменных окружения, а не в коде.
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8499873216:AAGuS3i9QbmcptkWmr-2L46CNtvTYSEMp1k')
if not BOT_TOKEN:
    raise ValueError("Необходимо установить переменную окружения TELEGRAM_BOT_TOKEN или указать токен в коде")

bot = telebot.TeleBot(BOT_TOKEN)

CHOICE_TEXT = {
    'best_video': '🎬 Видео (лучшее качество)',
    'audio_only': '🎧 Аудио (MP3)',
    'low_quality': '📉 Видео (низкое качество)'
}

def get_progress_bar(percent, bar_length=20):
    """Создает текстовый прогресс-бар."""
    filled_length = int(bar_length * percent / 100)
    bar = "█" * filled_length + "─" * (bar_length - filled_length)
    return f"[{bar}] {percent:.1f}%"

def download_media(url, output_template, choice, progress_hooks=None):
    """Скачивает медиа по ссылке в зависимости от выбора."""
    ydl_opts = {
        'outtmpl': output_template,
        'http_headers': {'User-Agent': 'Mozilla/5.0'},
        'progress_hooks': progress_hooks if progress_hooks else [],
        'concurrent_fragments': 16,
        'force_ipv4': True,
    }

    is_social_media = 'tiktok.com' in url or 'instagram.com' in url

    if choice == 'audio_only':
        ydl_opts.update({
            'format': 'bestaudio/best',
        })
    elif choice == 'low_quality':
        ydl_opts.update({
            'format': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            'merge_output_format': 'mp4',
        })
    else: 
        format_selector = 'bestvideo*+bestaudio/best' if is_social_media else 'bestvideo+bestaudio/best'
        ydl_opts.update({
            'format': format_selector,
            'merge_output_format': 'mp4',
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info_dict)
            return filename
    except yt_dlp.utils.DownloadError as e:
        print(f"Ошибка yt-dlp при скачивании медиа: {e}")
        return str(e)
    except Exception as e:
        print(f"Неожиданная ошибка при скачивании медиа: {e}")
        return str(e)

def get_file_size(file_path):
    """Возвращает размер файла в мегабайтах, или None если файл не найден."""
    try:
        file_size = os.path.getsize(file_path)
        return file_size / (1024 * 1024)  
    except FileNotFoundError:
        return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Отправляет приветственное сообщение и инструкции."""
    bot.reply_to(message, """
Привет! Отправь мне ссылку на видео из YouTube, TikTok или Instagram, и я его скачаю для тебя.
    """)

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    """Получает ссылку от пользователя и обрабатывает ее в зависимости от источника."""
    url = message.text
    if not (url.startswith('http://') or url.startswith('https://')):
        bot.reply_to(message, "Пожалуйста, отправьте корректную ссылку.")
        return

    if 'youtube.com' in url or 'youtu.be' in url:
        markup = InlineKeyboardMarkup()
        markup.row_width = 1
        markup.add(
            InlineKeyboardButton(CHOICE_TEXT['best_video'], callback_data="best_video"),
            InlineKeyboardButton(CHOICE_TEXT['audio_only'], callback_data="audio_only"),
            InlineKeyboardButton(CHOICE_TEXT['low_quality'], callback_data="low_quality")
        )
        bot.reply_to(message, "Выберите формат для скачивания:", reply_markup=markup)
    elif 'tiktok.com' in url or 'instagram.com' in url:
        status_message = bot.reply_to(message, "Получил ссылку. Начинаю обработку... ⏳")
        process_social_media_download(status_message, message, url)
    else:
        bot.reply_to(message, "К сожалению, я поддерживаю только ссылки с YouTube, TikTok и Instagram.")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """Обрабатывает нажатия на инлайн-кнопки."""
    choice = call.data
    status_message = call.message
    original_message = status_message.reply_to_message

    if not original_message:
        bot.edit_message_text("Не удалось найти исходное сообщение со ссылкой. Пожалуйста, отправьте ссылку заново.",
                              chat_id=status_message.chat.id, message_id=status_message.message_id, reply_markup=None)
        return

    url = original_message.text

    bot.edit_message_text(f"Выбрано: {CHOICE_TEXT.get(choice, 'Неизвестный выбор')}.\nНачинаю скачивание... ⏳",
                          chat_id=status_message.chat.id,
                          message_id=status_message.message_id,
                          reply_markup=None)

    process_download(status_message, original_message, url, choice)

def create_progress_hook(bot_instance, status_message):
    """Фабричная функция для создания progress_hook с замыканием на сообщение."""
    last_update = {'time': 0, 'text': ""}

    def progress_hook(d):
        """Обновляет сообщение, отображая прогресс скачивания."""
        try:
            current_time = time.time()
            # Интервал обновления увеличен до 2.5 секунд для стабильности
            if current_time - last_update['time'] < 2.5: 
                return

            if d['status'] == 'downloading':
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                
                percent_num = 0.0
                if total_bytes:
                    percent_num = (d.get('downloaded_bytes', 0) / total_bytes) * 100
                else:
                    percent_str = d.get('_percent_str', '0.0').replace('%', '').strip()
                    try:
                        percent_num = float(percent_str)
                    except (ValueError, TypeError):
                        percent_num = 0.0

                speed_str = d.get('_speed_str', 'N/A').strip()
                eta_str = d.get('_eta_str', 'N/A').strip()
                progress_bar = get_progress_bar(percent_num)

                progress_text = (
                    f"⏳ **Скачивание...**\n"
                    f"{progress_bar}\n"
                    f"⚡️ Скорость: {speed_str} | ⏳ Осталось: {eta_str}"
                )

                if progress_text != last_update['text']:
                    bot_instance.edit_message_text(
                        progress_text,
                        chat_id=status_message.chat.id,
                        message_id=status_message.message_id,
                        parse_mode='Markdown'
                    )
                    last_update['time'] = current_time
                    last_update['text'] = progress_text
        except telebot.apihelper.ApiTelegramException as e:
            if 'message is not modified' not in e.description:
                print(f"Ошибка при обновлении прогресса: {e}")
        except Exception as e:
            print(f"Непредвиденная ошибка в progress_hook: {e}")

    return progress_hook

def process_social_media_download(status_message, original_message, url):
    """Скачивает видео и аудио для ссылок из соцсетей и отправляет оба файла."""
    os.makedirs('downloads', exist_ok=True)
    video_path, audio_path = None, None

    try:
        video_template = f"downloads/{original_message.chat.id}_{original_message.message_id}_video.%(ext)s"
        
        hook = create_progress_hook(bot, status_message)
        video_path = download_media(url, video_template, 'best_video', progress_hooks=[hook])

        if not video_path or not os.path.exists(video_path):
            error_message = video_path if video_path else "Неизвестная ошибка скачивания."
            bot.edit_message_text(f"Не удалось скачать видео. Причина:\n`{error_message}`", chat_id=status_message.chat.id, message_id=status_message.message_id, parse_mode='Markdown')
            return

        bot.edit_message_text("✅ Видео скачано. Извлекаю аудио... 🎧", chat_id=status_message.chat.id, message_id=status_message.message_id)
        try:
            base_name = os.path.splitext(video_path)[0]
            audio_path = base_name + ".mp3"
            command = ['ffmpeg', '-i', video_path, '-vn', '-ab', '192k', '-preset', 'veryfast', '-y', audio_path]
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if not os.path.exists(audio_path):
                audio_path = None
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"Не удалось извлечь аудио: {e}")
            audio_path = None

        has_sent_anything = False
        if get_file_size(video_path) <= 50:
            with open(video_path, 'rb') as f:
                bot.send_video(original_message.chat.id, f, caption="Вот ваше видео", timeout=180)
            has_sent_anything = True
        else:
            bot.send_message(original_message.chat.id, "Видеофайл слишком большой для отправки (> 50 МБ).")

        if audio_path and os.path.exists(audio_path) and get_file_size(audio_path) <= 50:
            with open(audio_path, 'rb') as f:
                bot.send_audio(original_message.chat.id, f, caption="А вот аудиодорожка 🎵", timeout=180)
            has_sent_anything = True
        elif audio_path:
            bot.send_message(original_message.chat.id, "Аудиофайл слишком большой для отправки (> 50 МБ).")

        if has_sent_anything:
            bot.delete_message(chat_id=status_message.chat.id, message_id=status_message.message_id)
        else:
            bot.edit_message_text("Не удалось отправить файлы. Возможно, они слишком большие или произошла ошибка при скачивании.", chat_id=status_message.chat.id, message_id=status_message.message_id)

    except Exception as e:
        print(f"Ошибка при обработке ссылки из соцсети: {e}")
        bot.edit_message_text(f"Произошла ошибка: {e}", chat_id=status_message.chat.id, message_id=status_message.message_id)
    finally:
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

def process_download(status_message, original_message, url, choice):
    """Основная логика скачивания, проверки и отправки файла."""
    output_template = f"downloads/{original_message.chat.id}_{original_message.message_id}.%(ext)s"
    os.makedirs('downloads', exist_ok=True)

    hook = create_progress_hook(bot, status_message)
    media_path = download_media(url, output_template, choice, progress_hooks=[hook])

    if not media_path or not os.path.exists(media_path):
        error_message = media_path if media_path else "Неизвестная ошибка скачивания."
        bot.edit_message_text(f"Не удалось скачать файл. Причина:\n`{error_message}`", chat_id=status_message.chat.id, message_id=status_message.message_id, parse_mode='Markdown')
        return

    if choice == 'audio_only':
        bot.edit_message_text("✅ Скачивание завершено. Конвертирую в MP3...", chat_id=status_message.chat.id, message_id=status_message.message_id)
        try:
            audio_path_mp3 = os.path.splitext(media_path)[0] + ".mp3"
            command = ['ffmpeg', '-i', media_path, '-vn', '-ab', '192k', '-preset', 'veryfast', '-y', audio_path_mp3]
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.remove(media_path) 
            media_path = audio_path_mp3  
        except Exception as e:
            bot.edit_message_text(f"Произошла ошибка при конвертации в MP3: {e}", chat_id=status_message.chat.id, message_id=status_message.message_id)
            if os.path.exists(media_path):
                os.remove(media_path)
            return

    bot.edit_message_text("Файл готов. Проверяю размер...", chat_id=status_message.chat.id, message_id=status_message.message_id)

    file_size_mb = get_file_size(media_path)
    if file_size_mb is None:
            bot.edit_message_text("Не удалось определить размер файла.", chat_id=status_message.chat.id, message_id=status_message.message_id)
            if os.path.exists(media_path):
                os.remove(media_path)
            return

    if file_size_mb > 50:
            bot.edit_message_text(f"Файл слишком большой для отправки через Telegram ({file_size_mb:.2f} МБ). Лимит 50 МБ.", chat_id=status_message.chat.id, message_id=status_message.message_id)
            os.remove(media_path)
            return

    bot.edit_message_text("🚀 Загружаю файл в чат...", chat_id=status_message.chat.id, message_id=status_message.message_id)

    send_function = bot.send_video if choice != 'audio_only' else bot.send_audio
    try:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with open(media_path, 'rb') as media_file:
                        send_function(original_message.chat.id, media_file, timeout=180)

                    bot.delete_message(chat_id=status_message.chat.id, message_id=status_message.message_id)
                    break  
                except ConnectionResetError as e:
                    print(f"ConnectionResetError (попытка {attempt + 1}/{max_retries}): {e}")
                    if attempt + 1 < max_retries:
                        time.sleep(3)  
                    else:
                        bot.edit_message_text("Не удалось отправить файл: сервер разорвал соединение после нескольких попыток.", chat_id=status_message.chat.id, message_id=status_message.message_id)
                except Exception as e:
                    print(f"Непредвиденная ошибка при отправке файла: {e}")
                    bot.edit_message_text(f"Произошла непредвиденная ошибка при отправке файла: {e}", chat_id=status_message.chat.id, message_id=status_message.message_id)
                    break
    finally:
            if os.path.exists(media_path):
                os.remove(media_path)

if __name__ == '__main__':
    bot.infinity_polling()
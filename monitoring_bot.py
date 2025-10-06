import requests
import urllib.parse
import logging
import time
import os

# --- КОНФИГУРАЦИЯ ---

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# URL сайта или сайтов, который нужно проверять
urls = [
    'https://sas-company.by/',
    'https://belkraj.by/',
    'https://bood.by/',
    'https://flersalon.by/',
    'https://forosaktiv.by/',
    'https://pomogator.by/',
    'https://potolkisvetilniki.by/',
    'https://statgar.by/',
    'https://zoohelp.by/',
]

# Токен и Chat ID считываются из секретов GitHub Actions (переменных окружения)
# Это сделано для безопасности. НЕ храните их в открытом виде в коде!
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- ФУНКЦИИ ---

# Улучшенная функция проверки доступности сайта
def check_site_availability(url):
    """Проверяет доступность сайта и возвращает HTTP-код или None при ошибке."""
    try:
        # Добавляем заголовки для имитации реального браузера
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
        }
        response = requests.get(url, timeout=10, headers=headers)
        return response.status_code
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при проверке {url}: {e}")
        return None

# Функция отправки уведомления в Telegram-группу
def send_telegram_notification(bot_token, chat_id, message):
    """Отправляет уведомление в Telegram."""
    if not bot_token or not chat_id:
        logging.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы в переменных окружения.")
        return

    try:
        encoded_message = urllib.parse.quote_plus(message)
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded_message}"
        response = requests.get(url)
        response.raise_for_status() # Проверка статуса ответа от Telegram API
        logging.info(f"Сообщение отправлено в Telegram: {message}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")

# --- ОСНОВНАЯ ЛОГИКА ---

if __name__ == "__main__":
    logging.info("Начало ежечасной проверки сайтов...")
    
    # Основная логика для проверки всех сайтов
    for url in urls:
        http_code = check_site_availability(url)

        # Проверяем, чтобы HTTP-код не был 200, 301 или 302
        if http_code is None or (http_code not in [200, 301, 302]):
            message = f"🚨 САЙТ НЕДОСТУПЕН: {url}. Код: {http_code}"
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        else:
            logging.info(f"Сайт {url} доступен. Код: {http_code}")

        # Небольшая задержка между запросами к разным сайтам, чтобы не перегружать
        time.sleep(5) 
        
    logging.info("Проверка завершена. GitHub Action завершает работу до следующего часа.")

import requests
import urllib.parse
import logging
import time

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

# Токен вашего бота и chat_id группы
bot_token = "7673225834:AAGgiE0Z9Wn7GIsIr5GBxrqAUH5TvU1b790" # Не забудьте вставить свой токен
chat_id = "-4654375001"     # Не забудьте вставить свой chat_id

# Улучшенная функция проверки доступности сайта
def check_site_availability(url):
    try:
        # Добавляем больше заголовков, чтобы имитировать реальный браузер
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
        }
        # Убедитесь, что здесь используется именно requests.get
        response = requests.get(url, timeout=10, headers=headers)
        return response.status_code
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при проверке {url}: {e}")
        return None

# Функция отправки уведомления в Telegram-группу
def send_telegram_notification(bot_token, chat_id, message):
    try:
        encoded_message = urllib.parse.quote_plus(message)
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded_message}"
        response = requests.get(url)
        response.raise_for_status() # Проверка статуса ответа от Telegram API
        logging.info(f"Сообщение отправлено в Telegram: {message}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")

# Основная логика для проверки всех сайтов
for url in urls:
    http_code = check_site_availability(url)

    # Проверяем, чтобы HTTP-код не был 200 (успех), 301 (редирект) или 302 (временный редирект)
    if http_code is None or (http_code != 200 and http_code != 301 and http_code != 302):
        message = f"Сайт {url} недоступен! Код ошибки: {http_code}"
        send_telegram_notification(bot_token, chat_id, message)
        print(message)
    else:
        print(f"Сайт {url} доступен или перенаправляет. Код: {http_code}")

    time.sleep(5) # Задержка между проверками сайтов
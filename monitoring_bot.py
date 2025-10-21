import requests
import urllib.parse
import logging
import time
import os

# --- КОНФИГУРАЦИЯ ---

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# URL сайтов, которые нужно проверять
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
    'https://b2b-auto.by/',
    'https://sollers-auto.by/',
    'https://kupon.by/',
    'https://akumulyator.by/',
    'https://svaybel.by/',
    'https://mdcom.by/',
    'https://toppromotion.by/',
]

# Токен и Chat ID считываются из переменных окружения (например, секретов GitHub Actions)
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- ФУНКЦИИ ---

def check_site_availability(url, retries=3, delay=5):
    """
    Проверяет доступность сайта с несколькими попытками.
    Возвращает кортеж (http_code, error_message).
    При успехе error_message будет None.
    При ошибке http_code будет None.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
    }
    # Пробуем подключиться к сайту несколько раз
    for attempt in range(retries):
        try:
            # Устанавливаем таймаут для запроса
            response = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
            # Если запрос успешен, возвращаем код статуса и выходим из цикла
            return response.status_code, None
        except requests.exceptions.RequestException as e:
            logging.warning(f"Попытка {attempt + 1} для {url} не удалась: {e}")
            # Если это не последняя попытка, ждем перед следующей
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                # Если все попытки провалились, логируем ошибку и возвращаем ее
                logging.error(f"Все {retries} попытки для {url} не удались.")
                return None, str(e)
    # Эта строка выполнится, только если что-то пойдет не так с циклом
    return None, "Неизвестная ошибка в функции проверки"

def send_telegram_notification(bot_token, chat_id, message):
    """Отправляет уведомление в Telegram."""
    if not bot_token or not chat_id:
        logging.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не установлены.")
        return

    try:
        encoded_message = urllib.parse.quote_plus(message)
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded_message}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        logging.info(f"Уведомление успешно отправлено в Telegram.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")

# --- ОСНОВНАЯ ЛОГИКА ---

if __name__ == "__main__":
    logging.info("Начало ежечасной проверки сайтов с логикой повторных попыток...")

    for url in urls:
        http_code, error_message = check_site_availability(url)

        if error_message:
            # Если произошла ошибка соединения после всех попыток
            message = f"🚨 САЙТ НЕДОСТУПЕН: {url}\n\nПричина: Ошибка соединения после нескольких попыток.\nДетали: {error_message[:150]}..."
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        elif http_code not in [200, 301, 302]:
            # Если сайт ответил, но кодом ошибки
            message = f"🚨 САЙТ ОТВЕЧАЕТ С ОШИБКОЙ: {url}\n\nКод ответа: {http_code}"
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        else:
            # Если все в порядке
            logging.info(f"Сайт {url} доступен. Код: {http_code}")
        
        # Небольшая задержка между проверкой разных сайтов
        time.sleep(3)

    logging.info("Проверка сайтов завершена.")

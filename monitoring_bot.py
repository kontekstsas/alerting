import cloudscraper
import urllib.parse
import logging
import time
import os
from requests.exceptions import RequestException

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
    'https://akumulyator.by/',
    'https://svaybel.by/',
    'https://mdcom.by/',
    'https://toppromotion.by/',
]

# Токен и Chat ID считываются из переменных окружения
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- ИНИЦИАЛИЗАЦИЯ СКРАПЕРА ---
# Создаем эмулятор браузера. Это помогает обходить Cloudflare и защиту от ботов.
# Мы инициализируем его один раз, чтобы сохранять сессию (cookies и keep-alive).
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# --- ФУНКЦИИ ---

def check_site_availability(url, retries=3, delay=5):
    """
    Проверяет доступность сайта с несколькими попытками, обходя Cloudflare.
    Возвращает кортеж (http_code, error_message).
    """
    # Максимально имитируем реальный браузер Chrome
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            # Используем scraper.get вместо requests.get
            response = scraper.get(url, timeout=20, headers=headers, allow_redirects=True)
            
            # Если Cloudflare вернул 403 или 503 (часто бывает при проверке JS),
            # scraper обычно сам это обрабатывает. Если код все равно 403:
            if response.status_code == 403:
                 logging.warning(f"Попытка {attempt}: Получен 403 Forbidden (возможно, сильная защита Cloudflare).")
                 # Не выходим сразу, пробуем еще раз (иногда CF пропускает со 2 раза)
                 if attempt == retries:
                     return 403, "Доступ запрещен (403). Возможно, блокировка Cloudflare или IP."
            else:
                # Успешный запрос (или другая ошибка, которую вернем как статус)
                return response.status_code, None

        except Exception as e:
            last_error = str(e)
            logging.warning(f"Попытка {attempt} для {url} не удалась: {e}")
            
            # Если это не последняя попытка, ждем перед следующей
            if attempt < retries:
                time.sleep(delay)
            else:
                logging.error(f"Все {retries} попытки для {url} не удались.")

    # Возвращаем последнюю ошибку, если цикл закончился неудачей
    return None, last_error

def send_telegram_notification(bot_token, chat_id, message):
    """Отправляет уведомление в Telegram."""
    if not bot_token or not chat_id:
        logging.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не установлены.")
        return

    try:
        # Для отправки сообщения используем тот же scraper, чтобы не импортировать requests отдельно
        # Telegram API не требует обхода Cloudflare, но scraper отлично справляется с обычными запросами
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message
        }
        # Используем POST для надежности с длинными сообщениями
        response = scraper.post(url, data=payload, timeout=10)
        response.raise_for_status()
        logging.info(f"Уведомление успешно отправлено в Telegram.")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")

# --- ОСНОВНАЯ ЛОГИКА ---

if __name__ == "__main__":
    logging.info("Начало ежечасной проверки сайтов с защитой от Cloudflare...")

    for url in urls:
        http_code, error_message = check_site_availability(url)

        if error_message:
            # Ошибка соединения (DNS, Timeout, Reset connection)
            message = f"🚨 САЙТ НЕДОСТУПЕН: {url}\n\nПричина: Ошибка соединения.\nДетали: {error_message[:150]}..."
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        
        elif http_code not in [200, 301, 302]:
            # Сайт ответил, но кодом ошибки (404, 500, 403)
            message = f"🚨 САЙТ ОТВЕЧАЕТ С ОШИБКОЙ: {url}\n\nКод ответа: {http_code}"
            
            if http_code == 403:
                 message += "\n(Вероятно, блокировка ботов или Cloudflare)"
            
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        
        else:
            # Все хорошо
            logging.info(f"Сайт {url} доступен. Код: {http_code}")
        
        # Небольшая задержка между проверкой разных сайтов, чтобы не спамить
        time.sleep(3)

    logging.info("Проверка сайтов завершена.")

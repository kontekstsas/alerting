import cloudscraper
import urllib.parse
import logging
import time
import os
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# --- КОНФИГУРАЦИЯ ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- SPECAL SSL ADAPTER ---
# Этот класс нужен для лечения ошибки "RemoteDisconnected".
# Он заставляет Python использовать более совместимые параметры шифрования,
# которые не обрывают соединение на строгих или старых серверах.
class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        # SECLEVEL=1 позволяет использовать более широкий спектр шифров
        context = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(SSLAdapter, self).init_poolmanager(*args, **kwargs)

# --- ИНИЦИАЛИЗАЦИЯ СКРАПЕРА ---
# Переключаемся на Firefox, так как его отпечатки реже блокируются "глупыми" фаерволами.
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'firefox',
        'platform': 'windows',
        'desktop': True
    }
)

# Подключаем наш лечебный адаптер ко всем https запросам
scraper.mount('https://', SSLAdapter())

# --- ФУНКЦИИ ---

def check_site_availability(url, retries=3, delay=5):
    """
    Проверяет доступность сайта.
    """
    # ВАЖНО: Мы убрали User-Agent отсюда. 
    # cloudscraper сам подставит правильный User-Agent, соответствующий Firefox.
    # Ручная подмена часто вызывает ошибку RemoteDisconnected из-за несовпадения отпечатков.
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate, br',
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
            response = scraper.get(url, timeout=25, headers=headers, allow_redirects=True)
            
            if response.status_code == 403:
                 logging.warning(f"Попытка {attempt}: Получен 403 Forbidden.")
                 if attempt == retries:
                     return 403, "Доступ запрещен (403). Блокировка защиты."
            else:
                return response.status_code, None

        except Exception as e:
            last_error = str(e)
            logging.warning(f"Попытка {attempt} для {url} не удалась: {e}")
            
            if attempt < retries:
                time.sleep(delay)
            else:
                logging.error(f"Все {retries} попытки для {url} не удались.")

    return None, last_error

def send_telegram_notification(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        return

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': message}
        # Для Telegram не используем заголовки браузера, это API
        scraper.post(url, data=payload, headers={}, timeout=10)
        logging.info(f"Уведомление успешно отправлено в Telegram.")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")

# --- ОСНОВНАЯ ЛОГИКА ---

if __name__ == "__main__":
    logging.info("Начало проверки сайтов (SSL Fix + Cloudscraper)...")

    for url in urls:
        http_code, error_message = check_site_availability(url)

        if error_message:
            message = f"🚨 САЙТ НЕДОСТУПЕН: {url}\n\nПричина: Ошибка соединения.\nДетали: {error_message[:150]}..."
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        
        elif http_code not in [200, 301, 302]:
            message = f"🚨 САЙТ ОТВЕЧАЕТ С ОШИБКОЙ: {url}\n\nКод ответа: {http_code}"
            if http_code == 403:
                 message += "\n(Вероятно, блокировка ботов)"
            send_telegram_notification(bot_token, chat_id, message)
            logging.warning(message)
        
        else:
            logging.info(f"Сайт {url} доступен. Код: {http_code}")
        
        time.sleep(3)

    logging.info("Проверка сайтов завершена.")

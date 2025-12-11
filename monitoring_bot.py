import cloudscraper
import logging
import time
import os
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# Попытка импортировать curl_cffi для обхода жестких блокировок 403
try:
    from curl_cffi import requests as cffi_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    print("ВАЖНО: Установите curl_cffi (pip install curl_cffi) для обхода 403 ошибок!")

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

# --- SSL ADAPTER (Лечит "RemoteDisconnected" на belkraj.by) ---
class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(SSLAdapter, self).init_poolmanager(*args, **kwargs)

# --- ИНИЦИАЛИЗАЦИЯ CLOUDSCRAPER ---
scraper = cloudscraper.create_scraper(
    browser={'browser': 'firefox', 'platform': 'windows', 'desktop': True}
)
scraper.mount('https://', SSLAdapter())

# --- ФУНКЦИИ ---

def check_site_availability(url, retries=3, delay=5):
    """
    Гибридная проверка:
    1. Сначала cloudscraper (для совместимости со старыми SSL).
    2. Если 403 -> curl_cffi (для имитации реального браузера).
    """
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
    }

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            # --- ПОПЫТКА 1: Cloudscraper + SSLAdapter ---
            response = scraper.get(url, timeout=25, headers=headers)
            
            # Если получили 403 и у нас есть тяжелая артиллерия (curl_cffi)
            if response.status_code == 403 and CURL_CFFI_AVAILABLE:
                logging.warning(f"Попытка {attempt}: Cloudscraper получил 403. Пробуем curl_cffi (impersonate)...")
                try:
                    # Используем impersonate="chrome110" - это создает идеальный TLS отпечаток
                    cffi_response = cffi_requests.get(
                        url, 
                        impersonate="chrome110", 
                        headers=headers, 
                        timeout=25
                    )
                    # Если cffi пробил защиту, возвращаем его статус
                    if cffi_response.status_code == 200:
                        logging.info(f"Успех: curl_cffi обошел блокировку для {url}")
                        return 200, None
                    elif cffi_response.status_code != 403:
                         return cffi_response.status_code, None
                    
                except Exception as cffi_e:
                    logging.error(f"Ошибка curl_cffi: {cffi_e}")

            # Если cffi не помог или не нужен, проверяем обычный статус
            if response.status_code == 403:
                 if attempt == retries:
                     return 403, "Доступ запрещен (403). Жесткая защита Cloudflare."
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
        scraper.post(url, data=payload, headers={}, timeout=10)
        logging.info(f"Уведомление успешно отправлено в Telegram.")
    except Exception as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")

# --- ОСНОВНАЯ ЛОГИКА ---

if __name__ == "__main__":
    if not CURL_CFFI_AVAILABLE:
        logging.warning("⚠️ Библиотека curl_cffi не найдена. Сайты с сильной защитой могут выдавать 403.")
    
    logging.info("Начало проверки (Hybrid: Cloudscraper + Curl_CFFI)...")

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

# -*- coding: utf-8 -*-
"""
Мониторинг сайтов клиентов.

Ловит не только "сайт не отвечает", но и случаи, когда сервер бодро отдаёт 200,
а на месте сайта заглушка хостера, припаркованный домен или голая разметка без
стилей. Именно так в августе 2026 отвалился forosaktiv.by:
302 -> /cgi-sys/suspendedpage.cgi -> 200 OK, и проверка по коду ответа считала
это нормой почти двое суток.

Запуск:
    python monitoring_bot.py            обычная проверка
    python monitoring_bot.py --selftest проверить сам детектор на образцах
"""

import os
import re
import ssl
import sys
import json
import time
import socket
import difflib
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import cloudscraper
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

try:
    from curl_cffi import requests as cffi_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Консоль Windows живёт в cp1251 и давится эмодзи — переводим на utf-8
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# --- КОНФИГУРАЦИЯ ---

# Строкой или словарём:
#   must_contain — строка, которая обязана быть на живой странице (свой "ключ проверки")
#   timeout      — свой таймаут для медленных сайтов
#   skip         — отключённые проверки: suspension, stub, catchall, assets, ssl
#   network      — 'by-only'    сайт отвечает только из Беларуси: с зарубежной
#                                машины обрыв связи для него ожидаем, а не авария;
#                  'cloudflare'  за Cloudflare, который отдаёт 403 датацентровым IP.
#                                Проверить с сервера нельзя, пока не сделано
#                                исключение в самом Cloudflare (см. headers ниже)
#   headers      — свои заголовки к запросу. Нужны, чтобы пройти Cloudflare:
#                  заводим в нём правило Skip по секретному заголовку и шлём его
SITES = [
    'https://sas-company.by/',
    {'url': 'https://flersalon.by/', 'timeout': 60, 'network': 'by-only'},
    {'url': 'https://forosaktiv.by/', 'must_contain': '760-88-66'},
    'https://potolkisvetilniki.by/',
    'https://statgar.by/',
    'https://zoohelp.by/',
    {'url': 'https://akumulyator.by/', 'network': 'cloudflare'},
    {'url': 'https://mdcom.by/', 'timeout': 60, 'network': 'by-only'},
    'https://toppromotion.by/',
    {'url': 'https://auto-akb.by/', 'network': 'cloudflare'},
    {'url': 'https://x-lab.by/', 'timeout': 60, 'network': 'by-only'},
    'https://optizona.by/',
    'https://flersalon2.by/',
]

# Откуда запущен мониторинг: 'by' — из Беларуси, всё остальное — извне.
# Задаётся переменной окружения MONITOR_LOCATION.
LOCATION = os.environ.get("MONITOR_LOCATION", "abroad").strip().lower()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, 'state.json')

PROBE_PATH = '/__monitor_check_404__/'   # заведомо несуществующий адрес
DEFAULT_TIMEOUT = 45
SSL_WARN_DAYS = 14                       # за сколько дней предупредить о сертификате
MIN_TEXT_LEN = 500                       # меньше этого — страница явно пустая
COLLAPSE_RATIO = 0.3                     # усыхание относительно обычного размера
SOFT_FAIL_STREAK = 2                     # сетевые сбои: сколько раз подряд до тревоги
REMIND_HOURS = 24                        # как часто напоминать о неисправленном
DIGEST_HOUR_UTC = 6                      # ежедневная сводка, 06:00 UTC = 09:00 Минск

# Адреса, куда редиректят хостеры при приостановке
SUSPENSION_URL_MARKERS = [
    'suspendedpage.cgi', 'suspended', 'account_suspended', 'accountsuspended',
    'parked', 'parking', 'domain-expired', 'expired', 'sperrseite', 'stop.html',
]

# Заголовки страниц-заглушек
SUSPENSION_TITLES = [
    'suspended page', 'account suspended', 'suspended', 'parked domain',
    'домен припаркован', 'не обслуживается',
]

# Фразы, которые сами по себе означают заглушку
STUB_TEXT_HARD = [
    'не обслуживается', 'account suspended', 'this account has been suspended',
    'сайт приостановлен', 'услуга приостановлена', 'приостановлено за неуплату',
    'домен не оплачен', 'домен припаркован', 'этот домен припаркован',
    'срок регистрации домена', 'this domain has expired', 'domain has expired',
    'сайт заблокирован', 'хостинг приостановлен', 'оплатите услугу',
    'вы владелец этого сайта',
]

# Фразы, подозрительные только на маленькой странице
STUB_TEXT_SOFT = [
    'технические работы', 'сайт временно недоступен', 'under construction',
    'maintenance mode', 'скоро открытие', 'coming soon',
]

HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
}


class SSLAdapter(HTTPAdapter):
    """Лечит RemoteDisconnected на сайтах со старым SSL (belkraj.by)."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=1')
        return super(SSLAdapter, self).init_poolmanager(*args, **kwargs)


scraper = cloudscraper.create_scraper(
    browser={'browser': 'firefox', 'platform': 'windows', 'desktop': True}
)
scraper.mount('https://', SSLAdapter())


# --- ЗАГРУЗКА СТРАНИЦ ---

class Result:
    __slots__ = ('status', 'url', 'text', 'content_type', 'error')

    def __init__(self, status=None, url=None, text='', content_type='', error=None):
        self.status = status
        self.url = url or ''
        self.text = text or ''
        self.content_type = content_type or ''
        self.error = error


def fetch(url, retries=2, delay=5, timeout=DEFAULT_TIMEOUT, extra_headers=None):
    """Гибрид: cloudscraper, а при 403 — curl_cffi с подменой TLS-отпечатка."""
    last_error = None
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    for attempt in range(1, retries + 1):
        try:
            r = scraper.get(url, timeout=timeout, headers=headers)

            if r.status_code == 403 and CURL_CFFI_AVAILABLE:
                logging.warning("%s: 403 от cloudscraper, пробуем curl_cffi", url)
                try:
                    c = cffi_requests.get(url, impersonate="chrome124",
                                          headers=headers, timeout=timeout)
                    if c.status_code != 403:
                        return Result(c.status_code, str(c.url), c.text,
                                      c.headers.get('content-type', ''))
                except Exception as e:
                    logging.error("curl_cffi не смог: %s", e)

            if r.status_code == 403 and attempt < retries:
                time.sleep(delay)
                continue

            return Result(r.status_code, str(r.url), r.text,
                          r.headers.get('content-type', ''))

        except Exception as e:
            last_error = str(e)
            logging.warning("%s: попытка %s не удалась — %s", url, attempt, e)
            if attempt < retries:
                time.sleep(delay)

    return Result(error=last_error)


# --- РАЗБОР СТРАНИЦЫ ---

def visible_text(html):
    """Грубо выкидываем разметку, скрипты и стили — остаётся видимый текст."""
    t = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', html)
    t = re.sub(r'(?s)<!--.*?-->', ' ', t)
    t = re.sub(r'(?s)<[^>]+>', ' ', t)
    t = re.sub(r'&nbsp;?', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def page_title(html):
    m = re.search(r'(?is)<title[^>]*>(.*?)</title>', html)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''


def stylesheet_links(html, base_url, limit=2):
    """Свои (не внешние) файлы стилей со страницы."""
    out = []
    base_host = urlparse(base_url).netloc
    for tag in re.findall(r'(?is)<link\b[^>]*>', html):
        if 'stylesheet' not in tag.lower():
            continue
        m = re.search(r'(?is)href\s*=\s*["\']([^"\']+)["\']', tag)
        if not m:
            continue
        full = urljoin(base_url, m.group(1).strip())
        if urlparse(full).netloc != base_host:
            continue          # Google Fonts и прочую внешку не трогаем
        out.append(full)
        if len(out) >= limit:
            break
    return out


def ssl_days_left(url):
    host = urlparse(url).netloc.split(':')[0]
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        expires = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
        expires = expires.replace(tzinfo=timezone.utc)
        return (expires - datetime.now(timezone.utc)).days
    except Exception as e:
        logging.info("%s: сертификат не проверен — %s", host, e)
        return None


# --- АНАЛИЗ СОДЕРЖИМОГО (без сети, поэтому его можно тестировать) ---

def content_problems(html, final_url, site=None, baseline=None):
    site = site or {}
    skip = site.get('skip', [])
    problems = []

    text = visible_text(html)
    low_text = text.lower()
    low_url = (final_url or '').lower()
    title = page_title(html).lower()

    # 1. Редирект на страницу приостановки
    if 'suspension' not in skip:
        for marker in SUSPENSION_URL_MARKERS:
            if marker in low_url:
                problems.append("редирект на заглушку хостера: " + final_url)
                break

    # 2. Заголовок заглушки
    if 'stub' not in skip and title:
        for marker in SUSPENSION_TITLES:
            if marker in title:
                problems.append("заголовок страницы — «%s»" % page_title(html))
                break

    # 3. Текст заглушки
    if 'stub' not in skip:
        for phrase in STUB_TEXT_HARD:
            if phrase in low_text:
                problems.append("на странице текст заглушки: «%s»" % phrase)
                break
        else:
            if len(text) < 3000:
                for phrase in STUB_TEXT_SOFT:
                    if phrase in low_text:
                        problems.append("похоже на заглушку: «%s» на пустой странице" % phrase)
                        break

    # 4. Страница пустая
    if len(text) < MIN_TEXT_LEN:
        problems.append("страница почти пустая: %s символов текста" % len(text))

    # 5. Усохла относительно обычного размера
    if baseline and len(text) < baseline * COLLAPSE_RATIO:
        problems.append("текст усох: %s символов вместо привычных ~%s" % (len(text), baseline))

    # 6. Обязательная строка (свой ключ проверки)
    must = site.get('must_contain')
    if must and must.lower() not in html.lower():
        problems.append("на странице нет обязательной строки «%s»" % must)

    return problems


# --- ПОЛНАЯ ПРОВЕРКА САЙТА ---

def check_site(site, prev):
    """Возвращает (проблемы, новый базовый размер, точно_ли_сломан)."""
    url = site['url']
    skip = site.get('skip', [])
    timeout = site.get('timeout', DEFAULT_TIMEOUT)

    site_headers = site.get('headers')

    main = fetch(url, timeout=timeout, extra_headers=site_headers)

    # Сетевые сбои считаем ненадёжными: сайт мог просто моргнуть
    if main.error:
        return ["нет соединения: " + main.error[:160]], prev.get('baseline_len'), False

    if main.status >= 500:
        return ["код ответа %s" % main.status], prev.get('baseline_len'), False

    if main.status >= 400:
        return ["код ответа %s" % main.status], prev.get('baseline_len'), True

    baseline = prev.get('baseline_len')
    text = visible_text(main.text)
    problems = content_problems(main.text, main.url, site, baseline)

    # Весь сайт отдаёт одну и ту же страницу (мягкий 404)
    if 'catchall' not in skip:
        probe = fetch(urljoin(url, PROBE_PATH), retries=1, timeout=timeout,
                      extra_headers=site_headers)
        if not probe.error and probe.status == 200:
            probe_text = visible_text(probe.text)
            same = probe_text == text
            if not same and probe_text and text:
                ratio = difflib.SequenceMatcher(None, probe_text[:3000], text[:3000]).ratio()
                same = ratio >= 0.98
            if same:
                problems.append("несуществующий адрес отдаёт 200 и ту же самую страницу "
                                "— сайт подменён заглушкой на всех URL")

    # Стили отдаются как HTML (сайт без вёрстки)
    if 'assets' not in skip:
        for css_url in stylesheet_links(main.text, main.url):
            got = fetch(css_url, retries=1, timeout=timeout, extra_headers=site_headers)
            if got.error or got.status != 200:
                continue
            if 'html' in got.content_type.lower():
                problems.append("вместо стилей отдаётся HTML (%s) — страница откроется "
                                "без вёрстки" % css_url.split('/')[-1])
                break

    # Сертификат
    if 'ssl' not in skip:
        days = ssl_days_left(url)
        if days is not None and days < SSL_WARN_DAYS:
            problems.append("SSL-сертификат кончается через %s дн." % days)

    # Базовый размер обновляем только на здоровой странице
    new_baseline = baseline
    if not problems:
        rounded = int(round(len(text) / 500.0) * 500)
        new_baseline = (int(round((baseline * 0.8 + rounded * 0.2) / 500.0) * 500)
                        if baseline else rounded)

    return problems, new_baseline, True


# --- TELEGRAM ---

def send(message):
    if not BOT_TOKEN or not CHAT_ID:
        logging.warning("Нет TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID — вывожу в консоль")
        print(message)
        return
    try:
        scraper.post(
            "https://api.telegram.org/bot%s/sendMessage" % BOT_TOKEN,
            data={'chat_id': CHAT_ID, 'text': message, 'disable_web_page_preview': 'true'},
            timeout=15,
        )
        logging.info("Отправлено в Telegram")
    except Exception as e:
        logging.error("Telegram не принял сообщение: %s", e)


# --- СОСТОЯНИЕ ---

def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def normalize(site):
    return {'url': site} if isinstance(site, str) else dict(site)


# --- САМОПРОВЕРКА ДЕТЕКТОРА ---

def selftest():
    """Гоняем анализатор на образцах, чтобы он не разучился ловить заглушки."""
    ok = True

    sample = os.path.join(BASE_DIR, 'tests', 'suspended_hostfly.html')
    with open(sample, encoding='utf-8', errors='replace') as f:
        stub_html = f.read()

    found = content_problems(stub_html, 'https://example.by/cgi-sys/suspendedpage.cgi',
                             {'must_contain': '760-88-66'})
    if found:
        print("OK  заглушка Hostfly опознана, сработало правил: %s" % len(found))
        for p in found:
            print("      - " + p)
    else:
        print("FAIL заглушка Hostfly НЕ опознана")
        ok = False

    # Обратная проверка: нормальная страница не должна вызывать тревогу
    normal_html = ("<html><head><title>Бухгалтерские услуги — ООО ФоросАктив</title></head>"
                   "<body><p>Телефон +375 44 760-88-66. " + ("Бухгалтерское сопровождение. " * 60)
                   + "</p></body></html>")
    found = content_problems(normal_html, 'https://forosaktiv.by/',
                             {'must_contain': '760-88-66'}, baseline=2000)
    if found:
        print("FAIL нормальная страница помечена как сломанная: %s" % found)
        ok = False
    else:
        print("OK  нормальная страница претензий не вызвала")

    print("\nИТОГ: " + ("детектор исправен" if ok else "ЕСТЬ ПРОБЛЕМЫ"))
    return 0 if ok else 1


# --- ГЛАВНОЕ ---

def main():
    now = datetime.now(timezone.utc)
    state = load_state()
    sites = state.setdefault('sites', {})

    down_now, recovered = [], []

    for raw in SITES:
        site = normalize(raw)
        url = site['url']
        prev = sites.get(url, {})

        problems, baseline, hard = check_site(site, prev)
        entry = {'baseline_len': baseline} if baseline else {}

        # Часть сайтов с чужого адреса проверить нельзя в принципе:
        #   by-only    — не пускают зарубежные адреса, соединение не встаёт;
        #   cloudflare — Cloudflare отдаёт 403 любому датацентровому IP,
        #                подмена TLS-отпечатка тут не спасает: режут по адресу,
        #                а не по отпечатку, поэтому от страны запуска не зависит.
        # Ожидаемый симптом для таких сайтов — не авария, тревогу не поднимаем.
        # Но и молча забыть нельзя: они идут отдельной строкой в сводку.
        symptom = problems[0] if problems else ''
        no_connection = symptom.startswith('нет соединения')
        net = site.get('network')
        expected = (
            (net == 'by-only' and LOCATION != 'by' and no_connection)
            or (net == 'cloudflare' and (symptom == 'код ответа 403' or no_connection))
        )
        if expected:
            entry['status'] = 'skipped'
            entry['fail_streak'] = 0
            sites[url] = entry
            logging.info("%s: с этого адреса не проверяется (%s), это ожидаемо", url, net)
            time.sleep(2)
            continue

        if problems:
            streak = prev.get('fail_streak', 0) + 1
            entry['fail_streak'] = streak

            # Точные улики — тревога сразу. Сетевые сбои — только если повторились.
            worth_alerting = hard or streak >= SOFT_FAIL_STREAK

            was_ok = prev.get('status') != 'fail'
            last_alert = prev.get('last_alert')
            stale = True
            if last_alert:
                try:
                    stale = (now - datetime.fromisoformat(last_alert)) > timedelta(hours=REMIND_HOURS)
                except ValueError:
                    stale = True

            entry.update({
                'status': 'fail',
                'problems': problems,
                'since': now.isoformat(timespec='seconds') if was_ok else prev.get('since'),
                'last_alert': prev.get('last_alert'),
            })

            if worth_alerting and (was_ok or stale):
                entry['last_alert'] = now.isoformat(timespec='seconds')
                down_now.append((url, problems, entry['since'], was_ok))

            logging.warning("%s: %s", url, "; ".join(problems))
        else:
            if prev.get('status') == 'fail' and prev.get('last_alert'):
                recovered.append((url, prev.get('since')))
            entry['status'] = 'ok'
            entry['fail_streak'] = 0
            logging.info("%s: в порядке", url)

        sites[url] = entry
        time.sleep(2)

    for url, problems, since, is_new in down_now:
        head = "🚨 САЙТ СЛОМАН" if is_new else "🔁 ВСЁ ЕЩЁ СЛОМАН"
        lines = [head + ": " + url, ""]
        lines += ["• " + p for p in problems]
        if since:
            lines += ["", "Началось: " + since.replace('T', ' ') + " UTC"]
        send("\n".join(lines))

    for url, since in recovered:
        text = "✅ Поднялся: " + url
        if since:
            text += "\nЛежал с " + since.replace('T', ' ') + " UTC"
        send(text)

    # Ежедневная сводка — чтобы тишина не означала "бот умер"
    today = now.date().isoformat()
    # >=, а не ==: если запуск в шесть утра пропустили, сводка всё равно уйдёт
    # с ближайшим следующим, а не потеряется на сутки
    if now.hour >= DIGEST_HOUR_UTC and state.get('last_digest') != today:
        broken = [u for u, s in sites.items() if s.get('status') == 'fail']
        skipped = [u for u, s in sites.items() if s.get('status') == 'skipped']
        checked = len(sites) - len(skipped)

        lines = ["📋 Сводка за " + today, ""]
        if broken:
            lines.append("Проблемные сайты (%s из %s):" % (len(broken), checked))
            lines += ["• " + u for u in broken]
        else:
            lines.append("Все %s проверенных сайтов в порядке." % checked)
        if skipped:
            lines += ["", "Не проверяются с этого адреса (блокировка по IP):"]
            lines += ["• " + u for u in skipped]
        send("\n".join(lines))
        state['last_digest'] = today

    save_state(state)
    logging.info("Проверка завершена")


if __name__ == "__main__":
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    main()

#!/usr/bin/env python3
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import time
import os
import sys
import json
import argparse
import random
from urllib.parse import urlparse
from tqdm import tqdm

GREEN = "\033[92m"
RESET = "\033[0m"
YELLOW = "\033[93m"
RED = "\033[91m"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

DEFAULT_HEADERS = {
    "User-Agent": random.choice(USER_AGENTS)
}
TIMEOUT = 10
RETRIES = 2
REQUEST_DELAY = 0.5

def load_sites_from_file(filename="sites.txt"):
    sites = {}
    if not os.path.exists(filename):
        print(f"Файл {filename} не найден. Используйте пример:")
        print("github|https://github.com/{nick}|itemprop=\"name\",repositories,events-tab|")
        sys.exit(1)
    with open(filename, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('|')
            if len(parts) < 4:
                print(f"Ошибка в строке {line_num}: ожидается 4 поля, получено {len(parts)}")
                continue
            name = parts[0].strip()
            url_template = parts[1].strip()
            markers = [m.strip() for m in parts[2].split(',') if m.strip()]
            login_markers = [m.strip() for m in parts[3].split(',') if m.strip()]
            sites[name] = {
                "url": url_template,
                "markers": markers,
                "login_markers": login_markers
            }
    print(f"Загружено {len(sites)} соцсетей из {filename}")
    return sites

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def fetch_url(url, headers=None):
    if headers is None:
        headers = DEFAULT_HEADERS.copy()
        headers["User-Agent"] = random.choice(USER_AGENTS)
    last_exc = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
            return r
        except requests.RequestException as e:
            last_exc = e
            time.sleep(0.5)
    raise last_exc

def analyze_response(platform, nick, url, resp, site_info):
    status = resp.status_code
    text = resp.text or ""
    markers = site_info.get("markers", [])
    login_markers = site_info.get("login_markers", [])

    if status == 200:
        not_found_phrases = [
            "404", "not found", "страница не найдена",
            "does not exist", "no user", "could not be found",
            "this account doesn't exist", "пользователь не найден"
        ]
        if any(phrase in text.lower() for phrase in not_found_phrases):
            return "not_found"

        login_phrases = ["login", "sign in", "log in", "sign up", "register", "вход", "регистрация"]
        if any(phrase in text.lower() for phrase in login_phrases):
            for lm in login_markers:
                if lm.lower() in text.lower():
                    return "login_required"

        soup = BeautifulSoup(text, "html.parser")

        if soup.title and nick.lower() in soup.title.get_text(strip=True).lower():
            return "found"
        for meta in soup.find_all("meta"):
            content = meta.get("content", "")
            if nick.lower() in content.lower():
                return "found"

        for tag in soup.find_all(['h1', 'h2', 'h3', 'strong', 'span', 'div']):
            parent = tag.find_parent(['nav', 'footer', 'header'])
            if parent:
                continue
            tag_text = tag.get_text(strip=True)
            if nick.lower() in tag_text.lower():
                for m in markers:
                    try:
                        m_formatted = m.format(nick=nick)
                    except Exception:
                        m_formatted = m
                    if m_formatted.lower() in tag_text.lower():
                        return "found"

        return "unknown"

    elif status in (301, 302):
        final = resp.url
        if nick.lower() in final.lower():
            bad_redirects = ["login", "signin", "404", "error"]
            if not any(bad in final.lower() for bad in bad_redirects):
                return "found (redirect)"
        return f"redirect ({final})"

    elif status == 403:
        return "forbidden"
    elif status == 429:
        return "rate_limited"
    elif status == 404:
        return "not_found"
    else:
        return f"status_{status}"

def check_profile(platform, nick, site_info):
    url = site_info["url"].format(nick=nick)
    try:
        time.sleep(REQUEST_DELAY)
        r = fetch_url(url)
    except Exception as e:
        return platform, url, f"error: {e.__class__.__name__}"
    res = analyze_response(platform, nick, url, r, site_info)
    return platform, url, res

def scan_nick(nick, sites, workers=5):
    results = []
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_profile, name, nick, info): name for name, info in sites.items()}
        with tqdm(total=len(sites), desc="Сканирование", unit="сайт", ncols=80) as pbar:
            for fut in as_completed(futures):
                plat, url, status = fut.result()
                results.append((plat, url, status))
                pbar.update(1)
                pbar.set_postfix({"Текущий": plat, "Статус": status[:10]})
    elapsed = time.time() - start_time
    print(f"\nВремя выполнения: {elapsed:.2f} сек.")
    return results

def save_results_json(results, filename="socmint_results.json"):
    data = []
    for platform, url, status in results:
        data.append({
            "platform": platform,
            "url": url,
            "status": status,
            "found": "found" in status.lower()
        })
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"{GREEN}Results saved to {filename}{RESET}")

def print_header():
    banner = r"""
 _______   .__          __       ___ ___                  .__
 \      \  |__|  ____  |  | __  /   |   \   ____    ____  |__| __ __   _____
 /   |   \ |  |_/ ___\ |  |/ / /    ~    \ /  _ \  /    \ |  ||  |  \ /     \
/    |    \|  |\  \___ |    <  \    Y    /(  <_> )|   |  \|  ||  |  /|  Y Y  \
\____|__  /|__| \___  >|__|_ \  \___|_  /  \____/ |___|  /|__||____/ |__|_|  /
        \/          \/      \/        \/               \/                  \/

Version 2.0

GitHub - https://github.com/js91ns0/NickHonium.git

"""
    lines = banner.splitlines()
    main_banner = "\n".join(lines[:-1]) + "\n"
    signature = lines[-1]
    print(GREEN + main_banner + RESET + signature + RESET)

def print_results(results):
    print("\nResults:\n")
    for platform, url, status in sorted(results):
        if "found" in status.lower():
            color = GREEN
        elif "unknown" in status.lower():
            color = YELLOW
        else:
            color = RED
        print(f"{color}{platform:15} {status:20} {url}{RESET}")

def print_summary(results):
    found = sum(1 for _, _, s in results if "found" in s.lower())
    not_found = sum(1 for _, _, s in results if "not_found" in s.lower())
    errors = len(results) - found - not_found
    print(f"\n Итог: найдено {found}, не найдено {not_found}, ошибок {errors} из {len(results)}")

def main():
    parser = argparse.ArgumentParser(description="SOCMINT - поиск профилей по нику в соцсетях (из файла sites.txt)")
    parser.add_argument("nick", nargs="?", help="Ник для поиска (если не указан, будет запрошен в цикле)")
    parser.add_argument("-s", "--sites", default="sites.txt", help="Файл со списком соцсетей")
    parser.add_argument("-o", "--output", default="socmint_results.json", help="Файл для сохранения результатов (JSON) (будет перезаписан при каждом новом поиске, если не указать уникальное имя)")
    parser.add_argument("-w", "--workers", type=int, default=5, help="Количество потоков (по умолчанию 5)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Показать прогресс (не используется, теперь всегда показывается)")
    args = parser.parse_args()

    sites = load_sites_from_file(args.sites)
    if not sites:
        print("Не загружено ни одной соцсети. Проверьте файл.")
        sys.exit(1)

    if args.nick:
        nick = args.nick
        clear()
        print_header()
        print(f"Scanning: {nick}\n")
        results = scan_nick(nick, sites, workers=args.workers)
        print_results(results)
        print_summary(results)
        save_results_json(results, args.output)
        return

    while True:
        clear()
        print_header()
        print("Для выхода введите 'exit' или оставьте пустую строку и нажмите Enter.")
        nick = input("Введите ник для поиска: ").strip()
        if not nick or nick.lower() == 'exit':
            print("Выход.")
            break
        print(f"\nScanning: {nick}\n")
        results = scan_nick(nick, sites, workers=args.workers)
        print_results(results)
        print_summary(results)
        outfile = f"socmint_{nick}_{int(time.time())}.json" if args.output == "socmint_results.json" else args.output
        save_results_json(results, outfile)
        input("\nНажмите Enter, чтобы продолжить...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)

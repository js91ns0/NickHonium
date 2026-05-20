#!/usr/bin/env python3
# pip install requests beautifulsoup4
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import time
import os
import sys
import json
import argparse
from urllib.parse import urlparse

GREEN = "\033[92m"
RESET = "\033[0m"
YELLOW = "\033[93m"
RED = "\033[91m"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}
TIMEOUT = 10
RETRIES = 2
REQUEST_DELAY = 0.5 

def load_sites_from_file(filename="sites.txt"):
    """
    Загружает список соцсетей из файла.
    Формат строки: name|url|markers_list|login_markers_list
    markers_list и login_markers_list разделены запятыми (без пробелов).
    Возвращает словарь: {name: {"url": url, "markers": list, "login_markers": list}}
    """
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
        headers = DEFAULT_HEADERS
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
        if "404" in text or "Not Found" in text or "Страница не найдена" in text:
            return "not_found"
        for lm in login_markers:
            if lm.lower() in text.lower():
                return "login_required"
        for m in markers:
            try:
                m_formatted = m.format(nick=nick)
            except Exception:
                m_formatted = m
            if m_formatted.lower() in text.lower():
                return "found"
        soup = BeautifulSoup(text, "html.parser")
        title = (soup.title.string or "") if soup.title else ""
        if nick.lower() in title.lower():
            return "found"
        for a in soup.find_all("a", href=True)[:50]:
            if nick.lower() in a["href"].lower() or nick.lower() in a.get_text("").lower():
                return "found"
        return "unknown"
    elif status in (301, 302):
        final = resp.url
        if nick.lower() in final.lower():
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

def scan_nick(nick, sites, workers=5, show_progress=True):
    results = []
    total = len(sites)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_profile, name, nick, info): name for name, info in sites.items()}
        for fut in as_completed(futures):
            done += 1
            plat, url, status = fut.result()
            results.append((plat, url, status))
            if show_progress:
                print(f"{YELLOW}[{done}/{total}]{RESET} scanned: {plat}")
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
$$__$$_$$$$$$__$$$$__$$__$$__$$__$$__$$$$__$$__$$_$$$$$$_$$__$$_$$___$
$$$_$$___$$___$$__$$_$$_$$___$$__$$_$$__$$_$$$_$$___$$___$$__$$_$$$_$$
$$_$$$___$$___$$_____$$$$____$$$$$$_$$__$$_$$_$$$___$$___$$__$$_$$_$_$
$$__$$___$$___$$__$$_$$_$$___$$__$$_$$__$$_$$__$$___$$___$$__$$_$$___$
$$__$$_$$$$$$__$$$$__$$__$$__$$__$$__$$$$__$$__$$_$$$$$$__$$$$__$$___$

By js91ns0.

"""
    print(GREEN + banner + RESET)

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

def main():
    parser = argparse.ArgumentParser(description="SOCMINT - поиск профилей по нику в соцсетях (из файла sites.txt)")
    parser.add_argument("nick", nargs="?", help="Ник для поиска (если не указан, будет запрошен в цикле)")
    parser.add_argument("-s", "--sites", default="sites.txt", help="Файл со списком соцсетей")
    parser.add_argument("-o", "--output", default="socmint_results.json", help="Файл для сохранения результатов (JSON) (будет перезаписан при каждом новом поиске, если не указать уникальное имя)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Показать прогресс")
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
        results = scan_nick(nick, sites, workers=5, show_progress=args.verbose)
        print_results(results)
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
        results = scan_nick(nick, sites, workers=5, show_progress=args.verbose)
        print_results(results)
        outfile = f"socmint_{nick}_{int(time.time())}.json" if args.output == "socmint_results.json" else args.output
        save_results_json(results, outfile)
        input("\nНажмите Enter, чтобы продолжить...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)

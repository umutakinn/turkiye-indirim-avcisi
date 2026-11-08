
import os
import json
import re
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("Telegram bilgileri eksik!")

# Herkese açık RSS kaynakları
FEEDS = [
    "https://www.donanimhaber.com/rss/tum/",
    "https://www.technopat.net/feed/",
]

SEEN_FILE = Path("seen.json")
KEYWORDS = [
    "indirim", "fırsat", "kampanya", "ucuzladı",
    "fiyat düştü", "sıcak fırsat", "sepette"
]

def load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError("Telegram mesajı gönderilemedi!")

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def get_discount(text):
    matches = re.findall(
        r"%\s*(\d{1,2}(?:[.,]\d+)?)",
        text
    )

    for value in matches:
        try:
            percent = float(value.replace(",", "."))
            if 10 <= percent <= 99:
                return percent
        except ValueError:
            continue

    return None

def parse_feed(feed_url):
    request = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "IndirimAvcisiTR/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()

    root = ET.fromstring(content)
    items = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        description = clean_text(item.findtext("description"))
        guid = (item.findtext("guid") or link or title).strip()

        items.append({
            "title": title,
            "link": link,
            "description": description,
            "guid": guid
        })

    # Atom akışları için destek
    ns = {"a": "http://www.w3.org/2005/Atom"}

    for entry in root.findall(".//a:entry", ns):
        title = clean_text(entry.findtext("a:title", namespaces=ns))
        link_element = entry.find("a:link", ns)
        link = link_element.get("href", "") if link_element is not None else ""
        description = clean_text(
            entry.findtext("a:summary", namespaces=ns)
            or entry.findtext("a:content", namespaces=ns)
        )
        guid = entry.findtext("a:id", namespaces=ns) or link or title

        items.append({
            "title": title,
            "link": link,
            "description": description,
            "guid": guid
        })

    return items

def main():
    seen = load_seen()
    new_seen = set(seen)
    sent = 0

    for feed in FEEDS:
        try:
            items = parse_feed(feed)
            print(f"Kaynak kontrol edildi: {feed} ({len(items)} içerik)")

            for item in items:
                title = item["title"]
                description = item["description"]
                text = f"{title} {description}".lower()

                if not any(word in text for word in KEYWORDS):
                    continue

                discount = get_discount(text)
                if discount is None:
                    continue

                key = item["guid"]
                if not key or key in seen:
                    continue

                message = (
                    "🔥 İNDİRİM FIRSATI\n\n"
                    f"📦 {title}\n"
                    f"🏷️ Belirtilen indirim: %{discount:g}\n\n"
                    f"🔗 {item['link']}\n\n"
                    "⚠️ Fiyatı ve stok durumunu satın almadan önce kontrol et."
                )

                send_telegram(message)
                new_seen.add(key)
                sent += 1
                print(f"Bildirim gönderildi: {title}")

        except Exception as error:
            print(f"Kaynak okunamadı: {feed} | {error}")

    SEEN_FILE.write_text(
        json.dumps(sorted(new_seen), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"Tarama tamamlandı. Yeni bildirim: {sent}")

if __name__ == "__main__":
    main()

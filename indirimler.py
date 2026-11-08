
import os
import re
import json
import time
import html
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("Telegram token veya Chat ID eksik!")

SEEN_FILE = Path("seen.json")
MIN_DISCOUNT = 10
MAX_SEEN = 3000

# Açık RSS kaynakları ve mağaza odaklı haber aramaları
GOOGLE_QUERIES = [
    "Türkiye indirim fırsat kampanya ürün",
    "Trendyol indirim fırsat",
    "Hepsiburada indirim fırsat",
    "Amazon Türkiye indirim fırsat",
    "N11 indirim fırsat",
    "market elektronik giyim ev indirim",
]

FEEDS = [
    ("DonanımHaber", "https://www.donanimhaber.com/rss/tum/"),
]

for query in GOOGLE_QUERIES:
    params = urllib.parse.urlencode({
        "q": query,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr"
    })
    FEEDS.append((
        "Google Haberler",
        "https://news.google.com/rss/search?" + params
    ))

KEYWORDS = [
    "indirim", "fırsat", "kampanya", "fiyat düştü",
    "ucuzladı", "indirimli fiyat", "sepette"
]

AMOUNT = (
    r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"
    r"|\d+(?:,\d{1,2})?)\s*(?:TL|₺)"
)

def load_seen():
    if SEEN_FILE.exists():
        try:
            data = json.loads(
                SEEN_FILE.read_text(encoding="utf-8")
            )
            return set(data)
        except Exception:
            print("Geçmiş dosyası okunamadı, yeni liste oluşturuluyor.")
    return set()

def save_seen(seen):
    data = sorted(seen)[-MAX_SEEN:]
    SEEN_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def parse_price(value):
    value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None

def find_price_pair(text):
    # Önce açıkça belirtilmiş eski ve yeni fiyatları ara.
    old_pattern = re.compile(
        r"(?:eski fiyat|önceki fiyat|normal fiyat|liste fiyatı)"
        r"\D{0,35}" + AMOUNT,
        re.IGNORECASE
    )
    new_pattern = re.compile(
        r"(?:yeni fiyat|indirimli fiyat|şimdiki fiyat|satış fiyatı)"
        r"\D{0,35}" + AMOUNT,
        re.IGNORECASE
    )

    old_match = old_pattern.search(text)
    new_match = new_pattern.search(text)

    if old_match and new_match:
        old_price = parse_price(old_match.group(1))
        new_price = parse_price(new_match.group(1))
        if old_price and new_price and old_price > new_price:
            return old_price, new_price

    # "1.500 TL yerine 1.200 TL" gibi ifadeleri ara.
    amounts = re.findall(AMOUNT, text, re.IGNORECASE)

    if len(amounts) == 2 and re.search(
        r"yerine|iken|önce|düştü|indirimli",
        text,
        re.IGNORECASE
    ):
        old_price = parse_price(amounts[0])
        new_price = parse_price(amounts[1])

        if old_price and new_price and old_price > new_price:
            return old_price, new_price

    return None

def get_discount(old_price, new_price):
    return ((old_price - new_price) / old_price) * 100

def parse_feed(feed_url):
    request = urllib.request.Request(
        feed_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; IndirimAvcisiTR/1.0)"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()

    root = ET.fromstring(content)
    items = []

    # RSS formatı
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        description = clean_text(item.findtext("description"))
        guid = (item.findtext("guid") or link or title).strip()

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": description,
                "guid": guid
            })

    # Atom formatı
    ns = {"a": "http://www.w3.org/2005/Atom"}

    for entry in root.findall(".//a:entry", ns):
        title = clean_text(
            entry.findtext("a:title", namespaces=ns)
        )

        link_element = entry.find("a:link", ns)
        link = (
            link_element.get("href", "")
            if link_element is not None else ""
        )

        description = clean_text(
            entry.findtext("a:summary", namespaces=ns)
            or entry.findtext("a:content", namespaces=ns)
        )

        guid = (
            entry.findtext("a:id", namespaces=ns)
            or link or title
        )

        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": description,
                "guid": guid
            })

    return items

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
        raise RuntimeError("Telegram mesaj gönderme hatası!")

def main():
    seen = load_seen()
    new_seen = set(seen)

    sent = 0
    scanned = 0
    errors = 0

    for source_name, feed_url in FEEDS:
        try:
            items = parse_feed(feed_url)
            print(
                f"{source_name}: {len(items)} içerik bulundu."
            )

            scanned += len(items)

            for item in items:
                title = item["title"]
                description = item["description"]
                combined = f"{title} {description}"

                if not any(
                    word in combined.lower()
                    for word in KEYWORDS
                ):
                    continue

                price_pair = find_price_pair(combined)

                # Eski ve yeni fiyat doğrulanamıyorsa gönderme.
                if not price_pair:
                    continue

                old_price, new_price = price_pair
                discount = get_discount(old_price, new_price)

                if discount < MIN_DISCOUNT:
                    continue

                key = item["guid"]

                if not key or key in seen:
                    continue

                message = (
                    "🔥 İNDİRİM AVCISI TR\n\n"
                    f"📦 {title}\n\n"
                    f"🏷️ Önceki fiyat: {old_price:,.2f} TL\n"
                    f"💰 Yeni fiyat: {new_price:,.2f} TL\n"
                    f"📉 Hesaplanan indirim: %{discount:.1f}\n\n"
                    f"🔗 {item['link']}\n\n"
                    f"📡 Kaynak: {source_name}\n"
                    "⚠️ Satın almadan önce güncel fiyatı ve "
                    "stok durumunu kontrol et."
                )

                try:
                    send_telegram(message)
                    new_seen.add(key)
                    sent += 1
                    print(f"Bildirim gönderildi: {title}")
                    time.sleep(1)

                except Exception as error:
                    errors += 1
                    print(f"Telegram gönderim hatası: {error}")

        except Exception as error:
            errors += 1
            print(
                f"Kaynak okunamadı: {source_name} | {error}"
            )

    save_seen(new_seen)

    print("--------------------------------")
    print(f"Toplam taranan içerik: {scanned}")
    print(f"Yeni fırsat bildirimi: {sent}")
    print(f"Kaynak/gönderim hatası: {errors}")
    print("Tarama tamamlandı.")

if __name__ == "__main__":
    main()

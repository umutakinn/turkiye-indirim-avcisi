import os
import re
import json
import time
import html
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "")

if not TOKEN or not CHAT_ID:
    raise ValueError("Telegram token veya Chat ID eksik!")

MIN_DISCOUNT = 10
MAX_SEEN = 5000
SEEN_FILE = Path("seen.json")
USER_AGENT = "IndirimAvcisiTR/1.0 (+public RSS reader)"

# Kaynaklar: herkese açık RSS akışları. Erişim engeli aşılmaz.
FEEDS = [
    ("DonanımHaber", "https://www.donanimhaber.com/rss/tum/"),
]

# Google Haberler RSS: farklı kategoriler ve mağaza odaklı aramalar.
QUERIES = [
    "Türkiye indirim fırsat kampanya",
    "Trendyol indirim fırsat",
    "Hepsiburada indirim fırsat",
    "Amazon Türkiye indirim fırsat",
    "N11 indirim fırsat",
    "elektronik telefon bilgisayar indirim",
    "ev yaşam mutfak mobilya indirim",
    "giyim ayakkabı kozmetik indirim",
    "market süpermarket bebek ürünleri indirim",
    "otomotiv oto aksesuar yapı market indirim",
    "spor outdoor oyuncak kitap indirim",
]

for query in QUERIES:
    params = urllib.parse.urlencode({
        "q": query,
        "hl": "tr",
        "gl": "TR",
        "ceid": "TR:tr",
    })
    FEEDS.append((
        "Google Haberler - " + query,
        "https://news.google.com/rss/search?" + params
    ))

KEYWORDS = (
    "indirim", "fırsat", "kampanya", "kupon", "fiyat düştü",
    "ucuzladı", "sepette", "black friday", "efsane kasım"
)

def load_seen():
    try:
        if SEEN_FILE.exists():
            values = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(values if isinstance(values, list) else [])
    except Exception as exc:
        print(f"Geçmiş dosyası okunamadı: {exc}")
    return set()

def save_seen(values):
    SEEN_FILE.write_text(
        json.dumps(sorted(values)[-MAX_SEEN:], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def fetch(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()

def parse_feed(url):
    root = ET.fromstring(fetch(url))
    items = []

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

    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//a:entry", ns):
        title = clean_text(entry.findtext("a:title", namespaces=ns))
        link_node = entry.find("a:link", ns)
        link = link_node.get("href", "") if link_node is not None else ""
        description = clean_text(
            entry.findtext("a:summary", namespaces=ns)
            or entry.findtext("a:content", namespaces=ns)
        )
        guid = entry.findtext("a:id", namespaces=ns) or link or title
        if title and link:
            items.append({
                "title": title,
                "link": link,
                "description": description,
                "guid": guid
            })

    return items

def find_discount(text):
    # Yalnızca içerikte açıkça yazan yüzde indirimleri kabul edilir.
    patterns = [
        r"%\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:'e|'a|’e|’a)?\s*(?:varan|indirim)",
        r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:indirim|indirimli|tasarruf)",
        r"(?:%|yüzde)\s*(\d{1,2}(?:[.,]\d+)?)"
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                value = float(match.group(1).replace(",", "."))
                if MIN_DISCOUNT <= value <= 99:
                    return value
            except ValueError:
                continue
    return None

def extract_prices(text):
    # Fiyatlar sadece metinde açıkça varsa gösterilir; hesaplanmış gibi sunulmaz.
    price_re = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:TL|₺)"
    found = re.findall(price_re, text, re.IGNORECASE)
    return found[:2]

def telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(request, timeout=25) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API hatası: {result}")

def main():
    seen = load_seen()
    new_seen = set(seen)
    scanned = 0
    sent = 0
    errors = 0
    eligible = 0

    for source, feed_url in FEEDS:
        try:
            entries = parse_feed(feed_url)
            print(f"Kaynak OK: {source} | {len(entries)} içerik")
            scanned += len(entries)

            for entry in entries:
                combined = f"{entry['title']} {entry['description']}"
                if not any(word in combined.lower() for word in KEYWORDS):
                    continue

                discount = find_discount(combined)
                if discount is None:
                    continue

                eligible += 1
                key = hashlib.sha256(
                    (source + "|" + entry["guid"]).encode("utf-8")
                ).hexdigest()

                if key in seen:
                    continue

                prices = extract_prices(combined)
                price_line = ""
                if prices:
                    price_line = "\nMetinde geçen fiyat(lar): " + " / ".join(prices) + " TL"

                message = (
                    "🔥 İNDİRİM AVCISI TR\n\n"
                    f"📦 {entry['title']}\n"
                    f"📉 Kaynakta belirtilen indirim: %{discount:g}"
                    f"{price_line}\n\n"
                    f"🔗 {entry['link']}\n"
                    f"📡 Kaynak: {source}\n\n"
                    "ℹ️ İndirim oranı kaynak metninden alınmıştır; "
                    "bağımsız fiyat geçmişi doğrulaması değildir. "
                    "Satın almadan önce mağaza fiyatını kontrol et."
                )

                try:
                    telegram(message)
                    new_seen.add(key)
                    sent += 1
                    print(f"Telegram bildirimi gönderildi: {entry['title']}")
                    time.sleep(1)
                except Exception as exc:
                    errors += 1
                    print(f"Telegram gönderim hatası: {exc}")

        except Exception as exc:
            errors += 1
            print(f"Kaynak okunamadı: {source} | {exc}")

    save_seen(new_seen)

    summary = (
        "🕵️ İNDİRİM AVCISI TR - TARAMA RAPORU\n\n"
        f"📚 Taranan içerik: {scanned}\n"
        f"🔎 %{MIN_DISCOUNT} ve üzeri oran içeren içerik: {eligible}\n"
        f"📨 Yeni Telegram bildirimi: {sent}\n"
        f"⚠️ Kaynak/gönderim hatası: {errors}\n\n"
        "Not: Bu sürüm açık RSS/haber akışlarını tarar; "
        "mağazaların tüm ürün kataloglarını taradığı anlamına gelmez."
    )

    print("--------------------------------")
    print(summary)

    # Manuel Run workflow testinde mutlaka sonuç mesajı gönder.
    if EVENT_NAME == "workflow_dispatch":
        telegram(summary)

if __name__ == "__main__":
    main()

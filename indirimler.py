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
USER_AGENT = "IndirimAvcisiTR/1.1 (+public RSS reader)"

FEEDS = [
    ("DonanımHaber", "https://www.donanimhaber.com/rss/tum/"),
]

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
        "q": query, "hl": "tr", "gl": "TR", "ceid": "TR:tr"
    })
    FEEDS.append((
        "Google Haberler - " + query,
        "https://news.google.com/rss/search?" + params
    ))

PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:TL|₺)",
    re.IGNORECASE
)

def load_seen():
    try:
        if SEEN_FILE.exists():
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data if isinstance(data, list) else [])
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
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml"
        }
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()

def parse_feed(url):
    root = ET.fromstring(fetch(url))
    entries = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        description = clean_text(item.findtext("description"))
        guid = (item.findtext("guid") or link or title).strip()
        if title and link:
            entries.append({
                "title": title, "link": link,
                "description": description, "guid": guid
            })

    ns = {"a": "http://www.w3.org/2005/Atom"}
    for item in root.findall(".//a:entry", ns):
        title = clean_text(item.findtext("a:title", namespaces=ns))
        link_node = item.find("a:link", ns)
        link = link_node.get("href", "") if link_node is not None else ""
        description = clean_text(
            item.findtext("a:summary", namespaces=ns)
            or item.findtext("a:content", namespaces=ns)
        )
        guid = item.findtext("a:id", namespaces=ns) or link or title
        if title and link:
            entries.append({
                "title": title, "link": link,
                "description": description, "guid": guid
            })
    return entries

def to_number(value):
    value = value.strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(".", "")
    try:
        return float(value)
    except ValueError:
        return None

def explicit_discount(text):
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
                    return value, "Kaynakta açıkça belirtilen oran"
            except ValueError:
                pass
    return None, None

def price_based_discount(text):
    # İki fiyatı ancak metinde eski/yeni fiyat ilişkisi açıkça anlatılıyorsa kıyasla.
    markers = (
        "yerine", "önce", "şimdi", "fiyatı düştü", "düşerek",
        "indirildi", "eski fiyat", "yeni fiyat", "den düştü",
        "dan düştü", "tl oldu"
    )
    if not any(marker in text.lower() for marker in markers):
        return None

    matches = list(PRICE_RE.finditer(text))
    if len(matches) < 2:
        return None

    # Yakın iki fiyatı sırayla al; eski fiyatın yüksek olması şart.
    for first, second in zip(matches, matches[1:]):
        old_price = to_number(first.group(1))
        new_price = to_number(second.group(1))
        if old_price and new_price and old_price > new_price > 0:
            rate = (old_price - new_price) / old_price * 100
            if MIN_DISCOUNT <= rate <= 99:
                return {
                    "rate": round(rate, 1),
                    "old": first.group(1),
                    "new": second.group(1)
                }
    return None

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
    percent_candidates = 0
    price_candidates = 0
    skipped_duplicates = 0

    for source, feed_url in FEEDS:
        try:
            entries = parse_feed(feed_url)
            print(f"Kaynak OK: {source} | {len(entries)} içerik")
            scanned += len(entries)

            for entry in entries:
                text = f"{entry['title']} {entry['description']}"
                rate, method = explicit_discount(text)
                price_info = None

                if rate is not None:
                    percent_candidates += 1
                else:
                    price_info = price_based_discount(text)
                    if price_info:
                        rate = price_info["rate"]
                        method = "Metindeki eski/yeni fiyatlardan hesaplandı"
                        price_candidates += 1

                if rate is None or rate < MIN_DISCOUNT:
                    continue

                key = hashlib.sha256(
                    (source + "|" + entry["guid"]).encode("utf-8")
                ).hexdigest()

                if key in seen:
                    skipped_duplicates += 1
                    continue

                price_line = ""
                if price_info:
                    price_line = (
                        f"\n🏷️ Eski fiyat: {price_info['old']} TL"
                        f"\n💰 Yeni fiyat: {price_info['new']} TL"
                    )

                message = (
                    "🔥 İNDİRİM AVCISI TR\n\n"
                    f"📦 {entry['title']}\n"
                    f"📉 İndirim: %{rate:g}\n"
                    f"🧾 Tespit: {method}"
                    f"{price_line}\n\n"
                    f"🔗 {entry['link']}\n"
                    f"📡 Kaynak: {source}\n\n"
                    "⚠️ Bu bilgi RSS/haber metninden çıkarılmıştır; "
                    "mağaza fiyatı ve stok durumu bağımsız olarak doğrulanmamıştır. "
                    "Satın almadan önce bağlantıdaki fiyatı kontrol et."
                )

                try:
                    telegram(message)
                    new_seen.add(key)
                    sent += 1
                    print(f"Bildirim gönderildi: {entry['title']}")
                    time.sleep(1)
                except Exception as exc:
                    errors += 1
                    print(f"Telegram gönderim hatası: {exc}")

        except Exception as exc:
            errors += 1
            print(f"Kaynak okunamadı: {source} | {exc}")

    save_seen(new_seen)

    report = (
        "🕵️ İNDİRİM AVCISI TR - TARAMA RAPORU\n\n"
        f"📚 Taranan içerik: {scanned}\n"
        f"📊 Açık yüzde oranı bulunan: {percent_candidates}\n"
        f"🧮 Fiyat farkından hesaplanan: {price_candidates}\n"
        f"🔁 Daha önce gönderilmiş: {skipped_duplicates}\n"
        f"📨 Yeni bildirim: {sent}\n"
        f"⚠️ Kaynak/gönderim hatası: {errors}\n\n"
        "Not: Yalnızca açık RSS/haber akışları taranır. "
        "Bu sistem mağazaların tüm ürün kataloglarını taramaz; "
        "fiyat ve stok bilgisi satın almadan önce kontrol edilmelidir."
    )
    print("--------------------------------")
    print(report)

    if EVENT_NAME == "workflow_dispatch":
        telegram(report)

if __name__ == "__main__":
    main()

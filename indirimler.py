import os
import urllib.request
import urllib.parse
import json

token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat_id = os.environ.get("TELEGRAM_CHAT_ID")

if not token or not chat_id:
    raise ValueError("Telegram token veya chat ID eksik!")

# İlk aşamada yalnızca manuel testte mesaj gönder.
if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": "✅ İndirim Avcısı bağlantısı çalışıyor! Otomasyon hazır."
    }).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError("Telegram mesajı gönderilemedi!")

    print("Telegram bağlantısı başarılı!")

else:
    print("Zamanlanmış çalışma başarılı. Fırsat taraması sonraki aşamada eklenecek.")

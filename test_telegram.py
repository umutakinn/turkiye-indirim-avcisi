import os
import urllib.request
import urllib.parse
import urllib.error

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{token}/sendMessage"

data = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": "🚀 İndirim Avcısı TR bağlantısı başarılı!"
}).encode()

try:
    request = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(request) as response:
        print(response.read().decode())
except urllib.error.HTTPError as e:
    print("TELEGRAM HATA DETAYI:")
    print(e.read().decode())
    raise

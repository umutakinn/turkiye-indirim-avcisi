import os
import urllib.request
import urllib.parse

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{token}/sendMessage"

data = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": "🚀 İndirim Avcısı TR bağlantısı başarılı! Sistem test aşamasında."
}).encode()

request = urllib.request.Request(url, data=data)

with urllib.request.urlopen(request) as response:
    print(response.read().decode())

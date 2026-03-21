import requests
from dotenv import load_dotenv
import os

load_dotenv()

CLAL = os.getenv("LNGCOOKIE")

AUTH_URL = (
    "https://lng-tgk-aime-gw.am-all.net/common_auth/login"
    "?site_id=maimaidxex"
    "&redirect_url=https://maimaidx-eng.com/maimai-mobile/"
    "&back_url=https://maimai.sega.com/"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})
session.cookies.set("clal", CLAL, domain="lng-tgk-aime-gw.am-all.net")
response = session.get(AUTH_URL, allow_redirects=True)

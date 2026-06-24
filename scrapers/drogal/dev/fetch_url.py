import requests
from bs4 import BeautifulSoup

TEST_URL = "https://www.drogal.com.br/prednisolona-5mg-eurofarma-10-comprimidos/p"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def fetch_url(url):
    """
    Baixa o conteúdo de uma URL com o User-Agent
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.content  # Return raw bytes for BeautifulSoup to handle encoding
    except requests.exceptions.RequestException:
        return None


print(fetch_url(TEST_URL))

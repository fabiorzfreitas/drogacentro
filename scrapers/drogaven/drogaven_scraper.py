import requests
from bs4 import BeautifulSoup
import json
import time
import concurrent.futures
import os
import pandas as pd
from datetime import datetime
from tqdm import tqdm

# --- Required modules ---
# python -m pip install requests lxml fake_useragent beautifulsoup4 tqdm pandas openpyxl

# --- Configuration ---
SITEMAP_URL = "https://io.convertiez.com.br/s/drogaven/sitemap-products-1.xml"
OUTPUT_DIR = 'output'

# Set the maximum number of worker threads for multi-threading
MAX_WORKERS = 150 # You can adjust this value based on your system's capabilities and website's tolerance
SLEEP_TIME = 2 # Seconds before next request

# Control scraping scope: Set to True to scrape all unique URLs, False to scrape a sample
TEST_RUN = True
SAMPLE_SIZE = 500 # Number of URLs to scrape if SCRAPE_ALL_URLS is False

# Selectors for data extraction
PRICE_SELECTOR = 'p.seal-pix.pix-price.sale-price.sale-price-pix.money'
NAME_SELECTOR = 'meta[name="description"]'
EAN_SELECTOR = 'meta[itemprop="gtin13"]'

# Headers to mimic a browser request and avoid being blocked
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}


print('\n --- Drogaven Scraper ---\n')

# Checar a variável de teste
if TEST_RUN:
    print(f'Iniciando teste com {SAMPLE_SIZE} URLs\n')

# --- Funções acessórias ---

def fetch_url(url):
    """
    Baixa o conteúdo de uma URL com o User-Agent
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException:
        return None


def extract_product_urls_from_sitemap(sitemap_url):
    """
    Extrai as URLs de produtos de um sitemap XML
    O sitemap deve ter a tag <loc> nas URLs
    """
    print(f"Baixando sitemap: {sitemap_url}")
    xml_content = fetch_url(sitemap_url)
    if not xml_content:
        return []

    soup = BeautifulSoup(xml_content, 'xml')
    urls = [loc_tag.get_text() for loc_tag in soup.find_all('loc')]
    time.sleep(SLEEP_TIME)
    return urls


def parse_product_page(html_content, url):
    """
    Lê a página do produto e extrai preço, EAN e nome a partir de uma URL
    Retorna um dicionário com as informações do produto ou None se o produto não estiver disponível
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    product_data = {"url": url, "price": None, "ean": None, "name": None}


    # Extrai a tag para o preço
    try:
        price_paragraph = soup.select_one(PRICE_SELECTOR)
        strong_tag = price_paragraph.find('strong')
        price_text = strong_tag.get_text(strip=True)
        cleaned_price = price_text.replace('R$', '').replace(',', '.').strip()
        price_decimal = float(cleaned_price)
        product_data['price'] = price_decimal
    except (AttributeError, ValueError, TypeError):
        pass

    # Extrai a tag para o nome
    try:
        name_description_tag = soup.select_one(NAME_SELECTOR)
        product_data["name"] = name_description_tag.get('content')
    except (json.JSONDecodeError, AttributeError):
        pass
                
    # Extrai a tag para o EAN

    try:
        # 1. Find the specific JSON-LD script that contains the "Product" type
        json_ld_tag = soup.find('script', type='application/ld+json')
        
        if json_ld_tag:
            # 2. Load the string as a Python dictionary
            data = json.loads(json_ld_tag.string)
            
            # 3. Extract the gtin13 (EAN) value
            product_data["ean"] = data.get('gtin13')
            
    except (json.JSONDecodeError, AttributeError, TypeError):
        # Gracefully skip if JSON is malformed or the tag is missing
        pass

    # try:
    #     ean_description_tag = soup.select_one(EAN_SELECTOR)
    #     product_data["ean"] = ean_description_tag.get('content')
    # except (json.JSONDecodeError, AttributeError):
    #     pass
        

    # Junta os dados
    if (product_data["ean"] or product_data["name"]) and (product_data["price"] is None or product_data["price"] == ""):
        return None

    return product_data


def scrape_single_product(url):
    """
    Função para o worker baixar e processar a URL de um um único produto
    Retorna product_info ou None se o produto não estiver disponível
    """
    html_content = fetch_url(url)
    if not html_content:
        return None

    product_info = parse_product_page(html_content, url)
    time.sleep(SLEEP_TIME) # Pausa entre os requests
    return product_info


def save_data_to_files(data, output_dir="output"):
    """
    Saves data to project-level output folder
    """
    # Go up two levels to reach the project root 'output'
    base_output = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', output_dir))
    os.makedirs(base_output, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    json_filepath = os.path.join(base_output, f"Scrape_Drogaven_{date_str}.json")
    csv_filepath = os.path.join(base_output, f"Scrape_Drogaven_{date_str}.csv")
    xlsx_filepath = os.path.join(base_output, f"Scrape_Drogaven_{date_str}.xlsx")

    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nDados salvos em: {json_filepath}")

    if data:
        df = pd.DataFrame(data)

        df.rename(columns={
            "url": "Link",
            "price": "Preço (R$)",
            "ean": "EAN",
            "name": "Produto"
        }, inplace=True)

        df = df[["EAN", "Produto", "Preço (R$)", "Link"]]

        df.to_csv(csv_filepath, sep=';', index=False)
        print(f"Dados salvos em: {csv_filepath}.")

        df.to_excel(xlsx_filepath, index=False)
        print(f"Dados salvos em: {xlsx_filepath}.")
    else:
        print("Nenhum dado para salvar.")


def main():
    start_time = time.perf_counter()

    # Extrair todas as URLs de produtos
    urls_from_sitemap = extract_product_urls_from_sitemap(SITEMAP_URL)

    # Remover duplicados
    unique_product_urls = list(set(urls_from_sitemap))
    print(f"\nEncontradas {len(unique_product_urls)} URLs de produtos.")

    scraped_products = []
    no_ean = []
    total_failed_products = 0

    # Iniciar teste ou scraping
    if TEST_RUN:
        urls_to_scrape = unique_product_urls[:SAMPLE_SIZE]
        print(f"Extraindo {len(urls_to_scrape)} URLs de produtos para teste...")
        with open(f'{OUTPUT_DIR}/drogaven_sample_urls.txt', 'w+', encoding='utf-8') as f:
            for url in urls_to_scrape:
                f.write(url + '\n')        
    else:
        urls_to_scrape = unique_product_urls
        print(f"Extraindo {len(urls_to_scrape)} URLs de produtos...")

    # Usar workers para scraping em paralelo
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for product_info in tqdm(executor.map(scrape_single_product, urls_to_scrape), total=len(urls_to_scrape), desc="Extraindo Produtos..."):
            if not product_info:
                total_failed_products += 1
                continue
            if not product_info['ean']:
                no_ean.append(product_info)
                continue
            scraped_products.append(product_info)

    # Salvar em arquivos
    save_data_to_files(scraped_products, OUTPUT_DIR)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    print(f"""
          Drogaven:
    Tempo total: {total_time:.2f} segundos
    Total de produtos com sucesso: {len(scraped_products)}
    Total de produtos sem EAN: {len(no_ean)}
    Total de produtos com falha: {total_failed_products}
    """)


if __name__ == "__main__":
    main()

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import concurrent.futures
import os
import pandas as pd
from fake_useragent import UserAgent
from datetime import datetime
from tqdm import tqdm
import logging

# --- Required modules ---
# python -m pip install requests lxml fake_useragent beautifulsoup4 tqdm pandas openpyxl

# --- Logging Setup ---
log_filename = f"drogaraia_scraper_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration ---
SITEMAP_URL = "https://www.drogaraia.com.br/sitemap/2/sitemap.xml"
OUTPUT_DIR = 'output'

# Set the maximum number of worker threads for multi-threading
MAX_WORKERS = 10 # You can adjust this value based on your system's capabilities and website's tolerance

# Sets the pause values for fetch_url()
INITIAL_SLEEP_TIME = 300
MAX_RETRIES = 5
MAX_403_CODES = 3

# Control scraping scope: Set to True to scrape all unique URLs, False to scrape a sample
TEST_RUN = True
SAMPLE_SIZE = 500 # Number of URLs to scrape if TEST_RUN is True

# Selectors for data extraction
PRICE_SELECTOR = 'meta[property="product:price:amount"]'
NAME_SELECTOR = 'meta[property="og:image:alt"]'
EAN_SELECTOR = 'script[type="application/ld+json"]'

# Headers (without User-Agent) to mimic a browser request and avoid being blocked
BASE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br, ztsd',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': ''
}

# Global variables to persist across all function calls
global_ua_instance = UserAgent()
bad_uas = set()


# Iniciar e checar a variável de teste
logger.info('--- DrogaRaia Scraper Starting ---')
if TEST_RUN:
    logger.info(f'Iniciando teste com {SAMPLE_SIZE} URLs')


# --- Funções acessórias ---

def url_attempt(url, max_retries):

    last_status_code = None
    for attempt in range(max_retries):    
        current_ua_string = ''
        try:
            # Get a new random user agent that is NOT in our bad list
            current_ua_string = global_ua_instance.random
            while current_ua_string in bad_uas:
                current_ua_string = global_ua_instance.random

            headers = BASE_HEADERS.copy()
            headers['User-Agent'] = current_ua_string

            logger.debug(f"Attempt {attempt + 1} of {max_retries}: Fetching {url}")
            response = requests.get(url, headers=headers, timeout=10)
            
            # This will raise an exception for 4xx or 5xx status codes
            response.raise_for_status()
            
            logger.debug(f"✅ Success with: {current_ua_string}")
            return response.content # Return raw bytes for BeautifulSoup to handle encoding
        
        except requests.exceptions.RequestException as e:
            # Capture the status code if the exception has a response object
            if e.response is not None:
                last_status_code = e.response.status_code
            
            logger.warning(f"Request failed for {url}: {e}")
            logger.debug(f"❌ Failed with User-Agent: {current_ua_string}")
            bad_uas.add(current_ua_string)
            logger.debug(f"Adding to blacklist. Current bad UAs: {len(bad_uas)}")
            
            # Check for a 403 specifically, but only after all retries have been exhausted
            if attempt == max_retries - 1 and last_status_code == 403:
                # Break the inner loop to trigger the exponential backoff logic
                return last_status_code
            
            # End of the failed attempt
            sleep_time = random.uniform(2, 5)
            logger.debug(f"Retrying in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)


def fetch_url(url, max_retries=MAX_RETRIES, max_403_attempts=MAX_403_CODES):
    """
    Handles the fetching of a URL with a rotating User-Agent.
    
    If a 403 Forbidden error is encountered after all retries, the script
    will pause with an exponentially increasing delay and then retry the URL.
        
    Returns:
        response.text (str) if successful.
        None otherwise.
    """
    
    current_sleep_time = INITIAL_SLEEP_TIME # Initial pause time in seconds for a 403 error
    consecutive_403_count = 0
    
    while consecutive_403_count < max_403_attempts:
        # Performs multiple attempts at URL
        last_response = url_attempt(url, max_retries)

        # last_responde can be either the payload or an error status code
        if isinstance(last_response, str):
            return last_response

        # After the inner loop, check if the last failure was a 403
        if last_response == 403 and current_sleep_time < 3600:
            consecutive_403_count += 1
            logger.warning(f"⚠️ 403 Forbidden on {url}. Pausing for {current_sleep_time}s...")
            time.sleep(current_sleep_time)
            
            # Exponentially increase the sleep time, capping at 1 hour
            current_sleep_time = min(current_sleep_time * 1.5, 3600)
            
        else:
            # If the last error was NOT a 403, something else is wrong.
            # Stop trying on this URL and move on.
            logger.error(f"Abandoning URL {url}. Final status: {last_response}")
            return None
    
    # If the max 403 attempts were exhausted, give up on this URL.
    logger.error(f"Max 403 attempts reached for {url}.")
    return None
    

def extract_product_urls_from_sitemap(sitemap_url):
    """
    Extrai as URLs de produtos de um sitemap XML
    O sitemap deve ter a tag <loc> nas URLs
    """
    logger.info(f"Baixando sitemap: {sitemap_url}")
    xml_content = fetch_url(sitemap_url)
    if not xml_content:
        return []

    soup = BeautifulSoup(xml_content, 'xml')

    urls = []
    for url_tag in soup.find_all('url'):
        loc_tag = url_tag.find('loc')
        priority_tag = url_tag.find('priority')

        if priority_tag.get_text() == '1.0':
            urls.append(loc_tag.get_text())
        
    time.sleep(2)
    return urls

def parse_product_page(html_content, url):
    """
    Lê a página do produto e extrai preço, EAN e nome a partir de uma URL
    Retorna um dicionário com as informações do produto ou None se o produto não estiver disponível
    """
    logger.debug(f"Parsing product page for {url}. Content type: {type(html_content)}")
    soup = BeautifulSoup(html_content, 'html.parser')
    product_data = {"url": url, "price": None, "ean": None, "name": None}


    # Extrai a tag para o preço
    try:
        price_tag = soup.select_one(PRICE_SELECTOR)
        product_data['price'] = float(price_tag.get('content'))
    except (AttributeError, ValueError, TypeError):
        pass

    # Extrai a tag para o nome
    try:
        name_description_tag = soup.select_one(NAME_SELECTOR)
        product_data['name'] = name_description_tag.get('content')
    except (json.JSONDecodeError, AttributeError):
        pass
        
    # Extrai a tag para o EAN
    ld_json_scripts = soup.select(EAN_SELECTOR)
    for script in ld_json_scripts:
        if script.string:
            try:
                # Parse the JSON content
                data = json.loads(script.string)
                ean = data.get("gtin13")
                # If ean is found, store the value and stop searching
                if ean:
                    product_data['ean'] = ean
                    break
            except json.JSONDecodeError:
                # This script's content was not valid JSON, so we just move on
                continue

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
    time.sleep(2) # Pausa entre os requests
    return product_info


def save_data_to_files(data, output_dir="output"):
    """
    Saves data to project-level output folder
    """
    # Go up two levels to reach the project root 'output'
    base_output = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', output_dir))
    os.makedirs(base_output, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    json_filepath = os.path.join(base_output, f"Scrape_DrogaRaia_{date_str}.json")
    csv_filepath = os.path.join(base_output, f"Scrape_DrogaRaia_{date_str}.csv")
    xlsx_filepath = os.path.join(base_output, f"Scrape_DrogaRaia_{date_str}.xlsx")

    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Dados salvos em JSON: {json_filepath}")

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
        logger.info(f"Dados salvos em CSV: {csv_filepath}.")

        df.to_excel(xlsx_filepath, index=False)
        logger.info(f"Dados salvos em Excel: {xlsx_filepath}.")
    else:
        logger.warning("Nenhum dado para salvar.")


def main():
    start_time = time.perf_counter()

    # Extrair todas as URLs de produtos
    urls_from_sitemap = extract_product_urls_from_sitemap(SITEMAP_URL)

    # Remover duplicados
    unique_product_urls = list(set(urls_from_sitemap))
    logger.info(f"Encontradas {len(unique_product_urls)} URLs de produtos.")

    scraped_products = []
    no_ean = []
    total_failed_products = 0

    # Iniciar teste ou scraping
    if TEST_RUN:
        urls_to_scrape = unique_product_urls[:SAMPLE_SIZE]
        logger.info(f"Extraindo {len(urls_to_scrape)} URLs de produtos para teste...")
    else:
        urls_to_scrape = unique_product_urls
        logger.info(f"Extraindo {len(urls_to_scrape)} URLs de produtos...")

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
    logger.info(f"--- DrogaRaia Finish ---")
    logger.info(f"Tempo total: {total_time:.2f} segundos")
    logger.info(f"Total de produtos com sucesso: {len(scraped_products)}")
    logger.info(f"Total de produtos sem EAN: {len(no_ean)}")
    logger.info(f"Total de produtos com falha: {total_failed_products}")

    logger.info(f"Final count of blacklisted UAs: {len(bad_uas)}")


if __name__ == "__main__":
    main()

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

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Find input/eans.txt (two levels up from scrapers/drogaven/)
INPUT_EANS_FILE = os.path.abspath(
    os.path.join(SCRIPT_DIR, "..", "..", "input", "eans.txt")
)
OUTPUT_DIR = "output"

# Set parameters for requests and concurrency
MAX_WORKERS = 15
MAX_RETRIES = 5
MAX_403_CODES = 3
INITIAL_SLEEP_TIME = 120

# Control scraping scope
TEST_RUN = True
SAMPLE_SIZE = 500  # Default test sample size (can be customized)

# Headers (without User-Agent) to mimic a browser request
BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# --- Logging Setup ---
# Log file lives under <project_root>/output/logs/
_log_dir = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", OUTPUT_DIR, "logs"))
os.makedirs(_log_dir, exist_ok=True)
log_filename = os.path.join(
    _log_dir, f"drogaven_scraper_{datetime.now().strftime('%Y%m%dT%H%M')}.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception — raised when a single EAN should be skipped (non-fatal).
# ---------------------------------------------------------------------------
class ScraperSkipError(Exception):
    """Raised when an EAN should be skipped; never propagates past scrape_single_ean."""


# Global rotating UserAgent variables
global_ua_instance = UserAgent()
bad_uas = set()


def url_attempt(url, max_retries):
    """
    Performs a single requests attempt using a rotating User-Agent.
    """
    last_status_code = None
    for attempt in range(max_retries):
        current_ua_string = ""
        try:
            # Get a new random User-Agent that is not blacklisted
            current_ua_string = global_ua_instance.random
            while current_ua_string in bad_uas:
                current_ua_string = global_ua_instance.random

            headers = BASE_HEADERS.copy()
            headers["User-Agent"] = current_ua_string

            logger.debug(f"Attempt {attempt + 1} of {max_retries}: Fetching {url}")
            response = requests.get(url, headers=headers, timeout=10)

            # Raise exception if status is 4xx/5xx
            response.raise_for_status()

            logger.debug(f"✅ Success with UA: {current_ua_string}")
            return response.json()

        except Exception as e:
            if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                last_status_code = e.response.status_code

            logger.warning(f"Request failed for {url}: {e}")
            logger.debug(f"❌ Failed with User-Agent: {current_ua_string}")
            bad_uas.add(current_ua_string)

            # If we hit 403 on the last retry, pass it back to handle backoff
            if attempt == max_retries - 1 and last_status_code == 403:
                return last_status_code

            sleep_time = random.uniform(1, 3)
            logger.debug(f"Retrying in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)

    return last_status_code


def fetch_url(url, max_retries=MAX_RETRIES, max_403_attempts=MAX_403_CODES):
    """
    Handles request fetching with exponential backoff on 403 errors.
    Raises ScraperSkipError if the URL cannot be fetched after all retries.
    """
    current_sleep_time = INITIAL_SLEEP_TIME
    consecutive_403_count = 0

    while consecutive_403_count < max_403_attempts:
        last_response = url_attempt(url, max_retries)

        # Successfully parsed JSON dict/list
        if isinstance(last_response, (dict, list)):
            return last_response

        # Exponential backoff on 403 Forbidden
        if last_response == 403 and current_sleep_time < 3600:
            consecutive_403_count += 1
            logger.warning(
                f"⚠️ 403 Forbidden on {url}. Pausing for {current_sleep_time}s..."
            )
            time.sleep(current_sleep_time)
            current_sleep_time = min(current_sleep_time * 1.5, 3600)
        else:
            raise ScraperSkipError(
                f"Abandoning URL after failed retries (status: {last_response}): {url}"
            )

    raise ScraperSkipError(f"Max 403 attempts ({max_403_attempts}) reached for: {url}")


def parse_api_response(response_json, ean):
    """
    Parses the suggest JSON response and returns a product info dict.
    Raises ScraperSkipError for any condition that should skip this EAN.
    """
    if not response_json or not isinstance(response_json, dict):
        raise ScraperSkipError(f"EAN {ean}: invalid or empty API response.")

    result_list = response_json.get("result_list", [])

    if not result_list:
        raise ScraperSkipError(f"EAN {ean}: not found (empty result_list).")

    # More than one result means the EAN is ambiguous/invalid (partial string match)
    if len(result_list) != 1:
        raise ScraperSkipError(
            f"EAN {ean}: ambiguous response ({len(result_list)} results) — likely an invalid EAN."
        )

    item = result_list[0]

    name = item.get("name")
    url_slug = item.get("url")

    if not name or not url_slug:
        raise ScraperSkipError(
            f"EAN {ean}: missing required fields (name={name!r}, url={url_slug!r})."
        )

    product_url = f"https://www.drogaven.com.br/{url_slug}/p"

    price_decimal = None

    # Try to extract the pix/seal price first (lowest price)
    seals = item.get("seals", [])
    for seal_html in seals:
        if "seal-pix" in seal_html or "pix-price" in seal_html:
            try:
                soup = BeautifulSoup(seal_html, "html.parser")
                strong_tag = soup.find("strong")
                if strong_tag:
                    price_text = strong_tag.get_text(strip=True)
                    cleaned_price = (
                        price_text.replace("R$", "").replace(",", ".").strip()
                    )
                    price_decimal = float(cleaned_price)
                    break
            except Exception as e:
                logger.debug(f"EAN {ean}: failed to parse seal price: {e}")

    # Fallback to standard price field
    if price_decimal is None:
        try:
            price_decimal = float(item.get("price"))
        except (TypeError, ValueError):
            pass

    if price_decimal is None or price_decimal <= 0:
        raise ScraperSkipError(
            f"EAN {ean}: no valid price found (price={item.get('price')!r})."
        )

    return {"url": product_url, "price": price_decimal, "ean": ean, "name": name}


def scrape_single_ean(ean):
    """
    Worker function to fetch and parse a single EAN.
    Returns a product dict on success, or None if the EAN is skipped.
    ScraperSkipError is caught here so individual failures never halt the pool.
    """
    url = f"https://www.drogaven.com.br/busca/suggest/?query_term={ean}"
    try:
        response_json = fetch_url(url)
        product_info = parse_api_response(response_json, ean)
        # Add a short delay to be gentle to the servers
        time.sleep(random.uniform(0.5, 1.5))
        logger.info(f"✅ EAN {ean}: '{product_info['name']}' — R$ {product_info['price']:.2f}")
        return product_info
    except ScraperSkipError as e:
        logger.warning(f"⚠️ Skipped — {e}")
        return None


def save_failed_eans(failed_eans, output_dir="output"):
    """
    Writes skipped/failed EANs (one per line) to output/errors/ for manual review.
    """
    if not failed_eans:
        logger.info("Nenhum EAN com falha para exportar.")
        return

    errors_dir = os.path.abspath(
        os.path.join(SCRIPT_DIR, "..", "..", output_dir, "errors")
    )
    os.makedirs(errors_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    errors_filepath = os.path.join(errors_dir, f"Errors_Drogaven_{date_str}.txt")

    with open(errors_filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(failed_eans))
    logger.info(f"{len(failed_eans)} EANs com falha exportados para: {errors_filepath}")


def save_data_to_files(data, output_dir="output"):
    """
    Saves data to project-level output folder in JSON, CSV, and XLSX format.
    """
    base_output = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", output_dir))
    os.makedirs(base_output, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    json_filepath = os.path.join(base_output, f"Scrape_Drogaven_{date_str}.json")
    csv_filepath = os.path.join(base_output, f"Scrape_Drogaven_{date_str}.csv")
    xlsx_filepath = os.path.join(base_output, f"Scrape_Drogaven_{date_str}.xlsx")

    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Dados salvos em JSON: {json_filepath}")

    if data:
        df = pd.DataFrame(data)

        df.rename(
            columns={
                "url": "Link",
                "price": "Preço (R$)",
                "ean": "EAN",
                "name": "Produto",
            },
            inplace=True,
        )

        df = df[["EAN", "Produto", "Preço (R$)", "Link"]]

        df.to_csv(csv_filepath, sep=";", index=False)
        logger.info(f"Dados salvos em CSV: {csv_filepath}.")

        df.to_excel(xlsx_filepath, index=False)
        logger.info(f"Dados salvos em Excel: {xlsx_filepath}.")
    else:
        logger.warning("Nenhum dado para salvar.")


def main():
    start_time = time.perf_counter()
    logger.info("--- Drogaven Scraper Starting ---")
    logger.info(f"Log file: {log_filename}")

    if not os.path.exists(INPUT_EANS_FILE):
        logger.error(f"Input EAN file not found at: {INPUT_EANS_FILE}")
        return

    # Load and clean target EANs
    with open(INPUT_EANS_FILE, "r", encoding="utf-8") as f:
        eans = [line.strip() for line in f if line.strip()]

    unique_eans = list(set(eans))
    logger.info(f"Loaded {len(unique_eans)} unique EANs from input file.")

    if TEST_RUN:
        eans_to_scrape = unique_eans[:SAMPLE_SIZE]
        logger.info(f"Test Run: Scraping a sample of {len(eans_to_scrape)} EANs...")
    else:
        eans_to_scrape = unique_eans
        logger.info(f"Scraping all {len(eans_to_scrape)} EANs...")

    scraped_products = []
    failed_eans = []

    # Execute suggest queries in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(
            tqdm(
                executor.map(scrape_single_ean, eans_to_scrape),
                total=len(eans_to_scrape),
                desc="Scraping EANs via Suggest API",
            )
        )

    for ean, product_info in zip(eans_to_scrape, results):
        if product_info:
            scraped_products.append(product_info)
        else:
            failed_eans.append(ean)

    # Save output files
    save_data_to_files(scraped_products, OUTPUT_DIR)
    save_failed_eans(failed_eans, OUTPUT_DIR)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    logger.info(f"--- Drogaven Finish ---")
    logger.info(f"Tempo total: {total_time:.2f} segundos")
    logger.info(f"Total de produtos com sucesso: {len(scraped_products)}")
    logger.info(f"Total de EANs com falha: {len(failed_eans)}")
    logger.info(f"Final count of blacklisted UAs: {len(bad_uas)}")


if __name__ == "__main__":
    main()

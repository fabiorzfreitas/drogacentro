"""
Internal vs. Competitor Comparison Report
Generates a report comparing the best competitor price against our internal system prices.
"""
import json
import os
import time
import pandas as pd
from datetime import datetime
import warnings

# --- Configuration ---
SCRAPE_DATE = '2025-08-15'

INPUT_DIR = 'input'   # Internal spreadsheet lives here
DATA_DIR = 'output'   # Consolidated competitor data lives here
REPORT_DIR = 'output' # Final report goes here

# External catalog containing compared prices.
COMPETITOR_JSON = f'Scrape_concorrentes_{SCRAPE_DATE}.json'
# Internal spreadsheet containing source data.
INTERNAL_SHEET = 'Dados_sistema.xlsx'

def dict_handler(external, internal):

    internal_compared_catalog = {}
    
    for product in internal:
        if product in external:
            if float(external[product]['price']) < internal[product]['price']:
                winner = external[product]['source']
                best_price = external[product]['price']
            else:
                winner = 'DROGACENTRO'
                best_price = internal[product]['price']
            internal_compared_catalog[product] = {
                'ean': product,
                'category': internal[product]['category'],
                'name': internal[product]['name'],
                'best_external': external[product]['source'],
                'best_external_price': float(external[product]['price']),
                'internal_price': internal[product]['price'],
                'best': winner,
                'best_price': best_price,
                'class': internal[product]['class'],
            }
    
    return internal_compared_catalog


def save_data_to_files(data, output_dir="output"):
    """
    Salva os dados em JSON, CSV e XLSX, com a data no nome
    """
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    script_dir = os.path.dirname(__file__)

    json_filepath = os.path.join(script_dir, output_dir, f"Comparativo_{date_str}.json")
    csv_filepath = os.path.join(script_dir, output_dir, f"Comparativo_{date_str}.csv")
    xlsx_filepath = os.path.join(script_dir, output_dir, f"Comparativo_{date_str}.xlsx")

    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nData saved as: {json_filepath}")

    if data:
        df = pd.DataFrame(data).T
        df.columns = ['EAN', 'Curva', 'Produto', 'Concorrente', 'Preço concorrente', 'Nosso preço', 'Ganhador', 'Melhor preço', 'Classificação']

        df.to_csv(csv_filepath, sep=';', index=False)
        print(f"Data saved as: {csv_filepath}.")

        df.to_excel(xlsx_filepath, index=False)
        print(f"Data saved as: {xlsx_filepath}.")
    else:
        print("No data to save.")


def main():
    print(f"\n--- Generating Comparison Report for Scrape Date: {SCRAPE_DATE} ---")
    start_time = time.perf_counter()
    
    script_dir = os.path.dirname(__file__)
    catalog_file = os.path.join(script_dir, DATA_DIR, COMPETITOR_JSON)
    sheet_file = os.path.join(script_dir, INPUT_DIR, INTERNAL_SHEET)

    if not os.path.exists(catalog_file):
        print(f"❌ Error: Consolidated competitor file not found: {catalog_file}")
        print("Run '2-concorrentes.py' first.")
        return

    # Import external catalog
    with open(catalog_file, 'r', encoding='utf-8') as f:
        external_dict = json.load(f)

    # Import internal spreadsheet
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style, apply openpyxl's default",
            category=UserWarning
        )
        print(f"📊 Reading internal system data: {INTERNAL_SHEET}")
        df = pd.read_excel(sheet_file, usecols='A, B, C, J, Q', dtype=str, engine='openpyxl')

    # Rename columns
    column_names = ['ean', 'category', 'name', 'price', 'class']
    df.columns = column_names
    df = df.astype({'price': float})

    # Import as list of dicts and convert to dict of dicts
    internal_as_list = df.to_dict(orient='records')
    internal_as_dict = {product_row['ean']: product_row for product_row in internal_as_list}

    # Compare and save data to files
    processed_catalog = dict_handler(external_dict, internal_as_dict)
    save_data_to_files(processed_catalog, REPORT_DIR)

    end_time = time.perf_counter()
    total_time = end_time - start_time
    print(f"\n[SUCCESS] Comparison report generated in {total_time:.2f} seconds.")
    

if __name__ == "__main__":
    main()

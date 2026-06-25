import json
import pandas as pd
import os

json_file = r"c:\Users\Fabio\Git\drogacentro\output\Scrape_Drogaven_2026-06-24.json"
xlsx_file = r"c:\Users\Fabio\Git\drogacentro\output\Scrape_Drogaven_2026-06-24.xlsx"

if not os.path.exists(json_file):
    print(f"Error: {json_file} does not exist.")
    exit(1)

with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

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
    df.to_excel(xlsx_file, index=False)
    print(f"Successfully exported to {xlsx_file}")
else:
    print("No data found to export.")

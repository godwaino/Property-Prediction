# Predictelligence Property

Unified UK property valuation + live prediction platform.

## Start
```bash
pip install -r requirements.txt
python app.py
```


## Rightmove workaround (no scraping required)
Use `/admin` and upload a CSV of comparables via **Rightmove Workaround: CSV Comparable Import**.

Headers: `postcode,property_type,bedrooms,price,date_sold,floor_area_sqft,tenure,new_build`.
This lets valuation and prediction continue without direct portal access.


## Vercel deployment notes
- This project includes `api/index.py` and root `vercel.json` to run Flask in Vercel Python runtime.
- Set env var `PREDICTELLIGENCE_DATA_DIR=/tmp/predictelligence-data` for writable SQLite/cache location in serverless.
- Background scheduler threads are automatically disabled when `VERCEL` is detected.

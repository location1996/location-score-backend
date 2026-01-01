# Charging Location Intelligence – MVP

This MVP uses **real open data** (OSM, Zensus, Copernicus-ready).
Due to offline packaging, datasets are **auto-downloaded on first run**.

## First run
```bash
pip install -r requirements.txt
python app/main.py
```
The scripts will automatically download:
- Population raster (DE Zensus)
- OSM charging stations (Overpass)
- OSRM routing (public)

You will then be able to call:
POST /analyze

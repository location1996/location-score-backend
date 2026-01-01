import os
import geopandas as gpd
from shapely.geometry import shape

DATA_GPKG = "app/data/population_grid.gpkg"
LAYER_NAME = "population"   # so wie du es bei gdal_polygonize angegeben hast
POP_COL = "pop"             # so wie du es bei gdal_polygonize angegeben hast

# Cache: Grid nur einmal laden (schneller)
_GRID = None

def _load_grid():
    global _GRID
    if _GRID is None:
        if not os.path.exists(DATA_GPKG):
            raise FileNotFoundError(f"Missing {DATA_GPKG}. Did you create it with gdal_polygonize.py?")
        _GRID = gpd.read_file(DATA_GPKG, layer=LAYER_NAME)
        if _GRID.crs is None:
            raise ValueError("Population grid has no CRS. Please ensure the GPKG has a CRS.")
    return _GRID

def population_in_area(isochrone_geojson) -> int:
    iso_geom = shape(isochrone_geojson["features"][0]["geometry"])
    iso = gpd.GeoDataFrame([{"geometry": iso_geom}], crs="EPSG:4326")

    grid = _load_grid()

    # CRS angleichen
    if grid.crs != iso.crs:
        iso = iso.to_crs(grid.crs)

    # Schnell vorfiltern
    iso_poly = iso.geometry.iloc[0]
    cand = grid[grid.intersects(iso_poly)].copy()
    if cand.empty:
        return 0

    # Exakte Überlappung (Intersection)
    inter = gpd.overlay(cand, iso, how="intersection")

    # Bei polygonize entspricht "pop" dem Pixelwert (Personen pro Pixel)
    # Für verlässliche Summen: proportional nach Fläche gewichten
    metric = "EPSG:3857"
    cand_m = cand.to_crs(metric)
    inter_m = inter.to_crs(metric)

    # stabiler cell_id Ansatz
    cand = cand.reset_index(drop=True)
    cand["cell_id"] = cand.index
    inter = gpd.overlay(cand, iso, how="intersection")
    cand_m = cand.to_crs(metric)
    inter_m = inter.to_crs(metric)

    cell_area = cand_m.set_index("cell_id").geometry.area.to_dict()
    inter_m["cell_area"] = inter_m["cell_id"].map(cell_area)
    inter_m["inter_area"] = inter_m.geometry.area

    if POP_COL not in inter_m.columns:
        raise KeyError(f"Column '{POP_COL}' not found. Available columns: {list(inter_m.columns)}")

    inter_m["pop_part"] = inter_m[POP_COL] * (inter_m["inter_area"] / inter_m["cell_area"])

    return int(round(float(inter_m["pop_part"].sum())))

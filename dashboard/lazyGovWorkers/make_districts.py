"""Census TIGER 120th Congress districts (.gdb) -> simplified, clockwise-wound GeoJSON keyed like TX-18 / WY-AL.

    python dashboard/lazyGovWorkers/make_districts.py [path_to.gdb]
"""
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.polygon import orient

HERE = Path(__file__).resolve().parent
GDB = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/mnt/tlgdb_2026_us_legislative.gdb")
FIPS_ABBR = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
             "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
             "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
             "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
             "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
             "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}
TOL = 0.003  # degrees (~300 m): keeps small NYC / LA districts readable
LAND = os.path.expanduser("~/mnt/census map/cb_2025_us_cd119_500k/cb_2025_us_cd119_500k.shp")  # shoreline-clipped 500k outline; used only as a land mask

g = gpd.read_file(GDB, layer="Congressional_Districts")
g = g[g.STATEFP.isin(FIPS_ABBR) & (g.CD120FP != "ZZ")].copy()  # drop territories and water-only placeholders
at_large = g.groupby("STATEFP").CD120FP.transform("size") == 1
g["key"] = [f"{FIPS_ABBR[s]}-AL" if (a or c in ("00", "98")) else f"{FIPS_ABBR[s]}-{c}"
            for s, c, a in zip(g.STATEFP, g.CD120FP, at_large)]
assert g.key.is_unique, g.key[g.key.duplicated()].tolist()
g = g.to_crs(4326)

# TIGER/Line districts run out into lakes and the ocean; cut them back to the 500k shoreline.
land = gpd.read_file(LAND)
land = land[land.STATEFP.isin(FIPS_ABBR)].to_crs(4326)
land_geom = land.geometry.buffer(0).union_all().buffer(0.002)  # tiny pad so inland edges are not shaved
before = g.geometry.area.sum()
g["geometry"] = [geo.buffer(0).intersection(land_geom) for geo in g.geometry]
empty = g[g.geometry.is_empty | g.geometry.isna()].key.tolist()
assert not empty, f"districts lost in clip: {empty}"
print(f"clipped to shoreline: area {before:.1f} -> {g.geometry.area.sum():.1f} sq deg")
g["geometry"] = g.geometry.simplify(TOL, preserve_topology=True)


def cw(geom):  # d3 wants clockwise exterior rings
    polys = [geom] if isinstance(geom, Polygon) else [q for x in getattr(geom, "geoms", []) for q in ([x] if isinstance(x, Polygon) else list(getattr(x, "geoms", [])))]
    polys = [orient(p, sign=-1.0) for p in polys if not p.is_empty and p.area > 1e-7]  # drop specks
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


feats = [{"type": "Feature", "properties": {"key": k, "state": FIPS_ABBR[s]}, "geometry": mapping(cw(geo))}
         for k, s, geo in zip(g.key, g.STATEFP, g.geometry)]
(HERE / "cd120_simplified.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
print(len(feats), "districts;", (HERE / "cd120_simplified.geojson").stat().st_size // 1000, "KB")
print("at-large keys:", sorted(k for k in g.key if k.endswith("-AL")))

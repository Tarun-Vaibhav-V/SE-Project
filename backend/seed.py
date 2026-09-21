"""Seed Supabase with the 5 pilot sites + basins + precomputed caches.

Inputs (place in ../data/):
- pilot_basins.geojson  (exported by hydris_ps1_pilot.ipynb cell 9)
- drivers_demo.json     (exported by notebooks/hydris_drivers.ipynb, optional but recommended)

Run:  python seed.py            (needs .env with GEE + Supabase creds)
      python seed.py --offline  (skip GEE; seed only from the two files)
"""
import json
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv()

import supa

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

SITES = [
    {"id": "S1", "name": "Chennai plant (IN)", "lat": 13.0827, "lng": 80.2707},
    {"id": "S2", "name": "Tiruppur textile (IN)", "lat": 11.1085, "lng": 77.3411},
    {"id": "S3", "name": "Fresno plant (US-CA)", "lat": 36.7378, "lng": -119.7871},
    {"id": "S4", "name": "Hamburg plant (DE)", "lat": 53.5511, "lng": 9.9937},
    {"id": "S5", "name": "Riyadh plant (SA)", "lat": 24.7136, "lng": 46.6753},
]


def normalize_geometry(geom):
    """GEE's simplify() can degrade basin Polygons into GeometryCollections of
    LineStrings, which map fill layers silently ignore. Rebuild Polygon /
    MultiPolygon from whatever parts survived (closing open rings)."""
    t = geom.get("type")
    if t in ("Polygon", "MultiPolygon"):
        return geom

    def ring_of(line):
        c = list(line)
        if len(c) < 4:
            return None
        if c[0] != c[-1]:
            c.append(c[0])
        return c if len(c) >= 4 else None

    if t == "LineString":
        r = ring_of(geom["coordinates"])
        return {"type": "Polygon", "coordinates": [r]} if r else geom
    if t == "GeometryCollection":
        parts = []
        for g in geom.get("geometries", []):
            gt = g.get("type")
            if gt == "Polygon":
                parts.append(g["coordinates"])
            elif gt == "MultiPolygon":
                parts.extend(g["coordinates"])
            elif gt == "LineString":
                r = ring_of(g["coordinates"])
                if r:
                    parts.append([r])
        if len(parts) == 1:
            return {"type": "Polygon", "coordinates": parts[0]}
        if parts:
            return {"type": "MultiPolygon", "coordinates": parts}
    return geom


def seed_basins():
    gj = json.load(open(DATA / "pilot_basins.geojson"))
    for feat in gj["features"]:
        props = feat["properties"]
        pfaf = props.get("pfaf_id")
        if pfaf is None:
            continue
        supa.upsert_basin(pfaf, normalize_geometry(feat["geometry"]), props)
        sid = props.get("site_id")
        if sid:
            supa.upsert_site({"id": sid, "name": props.get("name"),
                              "lat": props.get("lat"), "lng": props.get("lng"),
                              "pfaf_id": pfaf})
    print(f"seeded {len(gj['features'])} basins + sites")


def seed_drivers():
    path = DATA / "drivers_demo.json"
    if not path.exists():
        print("drivers_demo.json not found - skip (export it from hydris_drivers.ipynb)")
        return
    data = json.load(open(path))
    n = 0
    for site_id, entry in data.items():
        for risk in ("drought", "groundwater", "flood"):
            if entry.get(risk):
                supa.upsert_driver_cache(site_id, risk, entry[risk])
                n += 1
    print(f"seeded {n} driver-cache rows")


def seed_profiles():
    import engine
    engine.init_ee()
    for s in SITES:
        prof = engine.get_site_profile(s["lat"], s["lng"])
        if not prof:
            print(f"{s['name']}: no basin"); continue
        pfaf = prof["_meta"]["pfaf_id"]
        pwi = engine.derive_pwi_scores(prof)
        fut = {f"bau{y}": engine.get_future(pfaf, y, "bau") for y in (30, 50)}
        supa.upsert_risk_cache(pfaf, profile=prof, future=fut, pwi=pwi)
        supa.upsert_site({**s, "pfaf_id": pfaf})
        print(f"{s['name']}: profile+pwi+future cached (pfaf {pfaf})")


if __name__ == "__main__":
    seed_basins()
    seed_drivers()
    if "--offline" not in sys.argv:
        seed_profiles()
    print("seed complete")

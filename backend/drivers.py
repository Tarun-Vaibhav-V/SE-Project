"""Hydris driver engines — drought / groundwater / flood, ported 1:1 from
notebooks/hydris_drivers.ipynb (Phase 1). Same no-hallucination rules:
dataset IDs probed live, per-driver source + confidence, renormalized weights,
attribution labeled as modelled contribution (never causation).
"""
import os
import time

import ee
import numpy as np
import scipy.stats as stats

from engine import AQ, clean

CHIRPS_YEARS = list(range(1995, 2026))
COMMON_YEARS = list(range(2003, 2026))

LC_INFIL = {10: .80, 20: .70, 30: .65, 40: .60, 50: .20, 60: .50,
            70: .50, 80: 1.0, 90: .90, 95: .90, 100: .60}

CN_TABLE = {
    10: (36, 60, 73, 79), 20: (35, 56, 70, 77), 30: (49, 69, 79, 84),
    40: (70, 80, 87, 90), 50: (77, 85, 90, 92), 60: (77, 86, 91, 94),
    70: (98, 98, 98, 98), 80: (100, 100, 100, 100), 90: (85, 85, 85, 85),
    95: (85, 85, 85, 85), 100: (63, 77, 85, 88),
}

_DS = None


def _probe_ic(cands, band=None):
    for cid in cands:
        try:
            bands = ee.ImageCollection(cid).first().bandNames().getInfo()
            if band and band not in bands:
                continue
            return cid
        except Exception:
            continue
    return None


def _probe_img(cands, band=None):
    for cid in cands:
        try:
            bands = ee.Image(cid).bandNames().getInfo()
            if band and band not in bands:
                continue
            return cid
        except Exception:
            continue
    return None


def DS():
    """Probe every dataset ID live, once per process. Missing -> driver degrades to no-data."""
    global _DS
    if _DS is not None:
        return _DS
    project = os.environ.get("GEE_PROJECT", "")
    _DS = {
        "chirps": _probe_ic(["UCSB-CHG/CHIRPS/DAILY"], "precipitation"),
        "gldas": _probe_ic(["NASA/GLDAS/V021/NOAH/G025/T3H"], "SoilMoi0_10cm_inst"),
        "ndvi": _probe_ic(["MODIS/061/MOD13Q1", "MODIS/006/MOD13Q1"], "NDVI"),
        "pet": _probe_ic(["MODIS/061/MOD16A2GF", "MODIS/061/MOD16A2", "MODIS/006/MOD16A2"], "PET"),
        "grace": _probe_ic(["NASA/GRACE/MASS_GRIDS_V04/MASCON_CRI", "NASA/GRACE/MASS_GRIDS_V04/MASCON",
                            "NASA/GRACE/MASS_GRIDS/MASCON_CRI", "NASA/GRACE/MASS_GRIDS/LAND"],
                           "lwe_thickness"),
        "smap": _probe_ic(["NASA/SMAP/SPL4SMGP/008", "NASA/SMAP/SPL4SMGP/007"], "sm_surface"),
        "worldcover": _probe_ic(["ESA/WorldCover/v200", "ESA/WorldCover/v100"], "Map"),
        "ghsl": _probe_ic(["JRC/GHSL/P2023A/GHS_BUILT_S"], "built_surface"),
        "copdem": _probe_ic(["COPERNICUS/DEM/GLO30"], "DEM"),
        "flowacc": _probe_img(["WWF/HydroSHEDS/15ACC"], "b1"),
        "condem": _probe_img(["WWF/HydroSHEDS/15CONDEM"], "b1"),
        "sand": _probe_img(["projects/soilgrids-isric/sand_mean",
                            "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02"]),
        "hysogs": _probe_img([
            "projects/sat-io/open-datasets/HiHydroSoilv2_0/Hydrologic_Soil_Group_250m",
            "projects/sat-io/open-datasets/HYSOGS250m",
            f"projects/{project}/assets/HYSOGs250m",
        ]),
    }
    return _DS


# ---------------- shared plumbing (identical to notebook) ----------------

def basin_geom(lat, lng):
    hit = AQ().filterBounds(ee.Geometry.Point([lng, lat]))
    if hit.size().getInfo() == 0:
        return None, None
    f = hit.first()
    return f.geometry(), f.get("pfaf_id").getInfo()


def aq_scores(lat, lng, keys=("bws_score", "bwd_score", "gtd_score",
                              "drr_score", "rfr_score", "cfr_score")):
    hit = AQ().filterBounds(ee.Geometry.Point([lng, lat]))
    if hit.size().getInfo() == 0:
        return {}
    d = hit.first().toDictionary(list(keys)).getInfo()
    return {k: clean(d.get(k)) for k in keys}


def yearly(col_id, band, geom, months, temporal_reducer, scale, years, mult=1.0):
    """Empty-window safe: years before a dataset starts (e.g. MOD16 PET < 2000) or in
    mission gaps (GRACE 2017-18) yield an empty filterDate -> 0-band composite, and any
    image math on that errors server-side. Each year is guarded by a lazy
    ee.Algorithms.If on the window's image count; `mult` is applied client-side."""
    col = ee.ImageCollection(col_id).select(band)

    def per_year(y):
        y = ee.Number(y)
        end = ee.Date.fromYMD(y, 12, 31)
        start = end.advance(-months, "month")
        sub = col.filterDate(start, end)
        d = sub.reduce(temporal_reducer).reduceRegion(
            ee.Reducer.mean(), geom, scale, maxPixels=1e9, bestEffort=True)
        v = ee.Algorithms.If(
            sub.size().gt(0),
            ee.Algorithms.If(d.size().gt(0), d.values().get(0), None),
            None)
        return ee.Feature(None, {"v": v})

    fc = ee.FeatureCollection(ee.List(years).map(per_year))
    return [None if (v := f["properties"].get("v")) is None else v * mult
            for f in fc.getInfo()["features"]]


def zscore(series):
    vals = [v for v in series if v is not None]
    if len(vals) < 8:
        return None
    a = np.array(vals, float)
    if a.std() == 0:
        return None
    return float((a[-1] - a.mean()) / a.std())


def gamma_spi(series):
    vals = [v for v in series if v is not None]
    if len(vals) < 12:
        return None
    x = np.array(vals, float)
    pos = x[x > 0]
    if len(pos) < 10:
        return None
    try:
        q0 = float((x <= 0).mean())
        a, loc, b = stats.gamma.fit(pos, floc=0)
        cdf = q0 + (1 - q0) * stats.gamma.cdf(max(x[-1], 1e-9), a, loc=0, scale=b)
        cdf = float(np.clip(cdf, 1e-4, 1 - 1e-4))
        return float(stats.norm.ppf(cdf))
    except Exception:
        return None


def sev_dry(z):
    return None if z is None else float(np.clip(0.5 - z / 4.0, 0, 1))


def composite(drivers):
    avail = {k: d for k, d in drivers.items() if d.get("severity") is not None}
    if not avail:
        return {"hazard_0_1": None, "hazard_0_5": None, "attribution_pct": {},
                "drivers": drivers, "excluded": list(drivers)}
    wsum = sum(d["weight"] for d in avail.values())
    hazard = sum(d["severity"] * d["weight"] for d in avail.values()) / wsum
    contrib = {k: d["severity"] * d["weight"] for k, d in avail.items()}
    total = sum(contrib.values()) or 1.0
    return {
        "hazard_0_1": round(hazard, 3),
        "hazard_0_5": round(hazard * 5, 2),
        "attribution_pct": {k: round(100 * c / total, 1) for k, c in contrib.items()},
        "attribution_note": "estimated contribution to the modelled score (not physical causation)",
        "drivers": drivers,
        "excluded": [k for k in drivers if k not in avail],
    }


def _drv(sev, weight, source, confidence, **extra):
    d = {"severity": None if sev is None else round(sev, 3),
         "weight": weight, "source": source, "confidence": confidence}
    d.update(extra)
    return d


def _pt_val(img, lat, lng, scale, band=None):
    g = ee.Geometry.Point([lng, lat]).buffer(scale)
    d = img.reduceRegion(ee.Reducer.mean(), g, scale, maxPixels=1e9, bestEffort=True).getInfo()
    if not d:
        return None
    return d.get(band) if band else (list(d.values())[0] if d else None)


# ---------------- drought ----------------

def drought_drivers(lat, lng):
    ds = DS()
    t0 = time.time()
    geom, pfaf = basin_geom(lat, lng)
    if geom is None:
        return None
    out = {}
    rain = None

    if ds["chirps"]:
        rain = yearly(ds["chirps"], "precipitation", geom, 3, ee.Reducer.sum(), 5000, CHIRPS_YEARS)
        spi = gamma_spi(rain)
        method = "gamma-SPI"
        if spi is None:
            spi = zscore(rain)
            method = "zscore-fallback"
        out["rainfall_SPI"] = _drv(sev_dry(spi), 0.175, ds["chirps"], "computed",
                                   index=None if spi is None else round(spi, 2), method=method)
    else:
        out["rainfall_SPI"] = _drv(None, 0.175, "CHIRPS unavailable", "no-data")

    if ds["chirps"] and ds["pet"] and rain is not None:
        pet = yearly(ds["pet"], "PET", geom, 3, ee.Reducer.sum(), 1000, CHIRPS_YEARS, mult=0.1)
        pmpet = [None if (r is None or p is None) else r - p for r, p in zip(rain, pet)]
        z = zscore(pmpet)
        out["water_balance_SPEI"] = _drv(sev_dry(z), 0.175, f'{ds["chirps"]} + {ds["pet"]}',
                                         "computed", index=None if z is None else round(z, 2),
                                         method="z of P-PET (SPEI-lite)")
    else:
        out["water_balance_SPEI"] = _drv(None, 0.175, "MOD16 PET unavailable", "no-data")

    if ds["gldas"]:
        z = zscore(yearly(ds["gldas"], "SoilMoi0_10cm_inst", geom, 3, ee.Reducer.mean(), 25000, COMMON_YEARS))
        out["soil_moisture"] = _drv(sev_dry(z), 0.15, ds["gldas"], "computed",
                                    index=None if z is None else round(z, 2))
        z = zscore(yearly(ds["gldas"], "Qs_acc", geom, 3, ee.Reducer.mean(), 25000, COMMON_YEARS))
        out["runoff"] = _drv(sev_dry(z), 0.175, ds["gldas"], "computed",
                             index=None if z is None else round(z, 2))
    else:
        out["soil_moisture"] = _drv(None, 0.15, "GLDAS unavailable", "no-data")
        out["runoff"] = _drv(None, 0.175, "GLDAS unavailable", "no-data")

    if ds["ndvi"]:
        z = zscore(yearly(ds["ndvi"], "NDVI", geom, 3, ee.Reducer.mean(), 1000, COMMON_YEARS))
        out["vegetation_NDVI"] = _drv(sev_dry(z), 0.15, ds["ndvi"], "computed",
                                      index=None if z is None else round(z, 2))
    else:
        out["vegetation_NDVI"] = _drv(None, 0.15, "MODIS NDVI unavailable", "no-data")

    if ds["grace"]:
        z = zscore(yearly(ds["grace"], "lwe_thickness", geom, 12, ee.Reducer.mean(), 100000, COMMON_YEARS))
        out["storage_GRACE"] = _drv(sev_dry(z), 0.175, ds["grace"], "regional",
                                    index=None if z is None else round(z, 2),
                                    caveat="~300 km resolution - basin/regional signal, never site-scale")
    else:
        out["storage_GRACE"] = _drv(None, 0.175, "GRACE unavailable", "no-data")

    res = composite(out)
    res.update({"risk": "drought", "pfaf_id": pfaf, "runtime_s": round(time.time() - t0, 1)})
    return res


# ---------------- groundwater ----------------

def _grace_trend_cm_yr(geom):
    col = (ee.ImageCollection(DS()["grace"]).select("lwe_thickness")
           .filterDate("2003-01-01", "2025-12-31"))

    def addt(img):
        t = img.date().difference(ee.Date("2003-01-01"), "year")
        return ee.Image.constant(t).float().rename("t").addBands(img)

    fit = col.map(addt).select(["t", "lwe_thickness"]).reduce(ee.Reducer.linearFit())
    d = fit.select("scale").reduceRegion(ee.Reducer.mean(), geom, 100000,
                                         maxPixels=1e9, bestEffort=True).getInfo()
    return d.get("scale")


def _recharge_index(geom):
    ds = DS()
    parts, srcs = {}, []
    if ds["chirps"]:
        p = (ee.ImageCollection(ds["chirps"]).select("precipitation")
             .filterDate("2005-01-01", "2025-01-01").sum().divide(20)
             .reduceRegion(ee.Reducer.mean(), geom, 5000, maxPixels=1e9, bestEffort=True).getInfo())
        p_ann = list(p.values())[0] if p else None
        if p_ann is not None:
            parts["rain"] = (float(np.clip(p_ann / 1500.0, 0, 1)), 0.40)
            srcs.append(ds["chirps"])
    if ds["sand"]:
        img = ee.Image(ds["sand"])
        band = img.bandNames().getInfo()[0]
        sv = img.select(band).reduceRegion(ee.Reducer.mean(), geom, 1000,
                                           maxPixels=1e9, bestEffort=True).getInfo().get(band)
        if sv is not None:
            frac = sv / 1000.0 if sv > 100 else sv / 100.0
            parts["sand"] = (float(np.clip(frac, 0, 1)), 0.25)
            srcs.append(ds["sand"])
    if ds["worldcover"]:
        lc = (ee.ImageCollection(ds["worldcover"]).first()
              .reduceRegion(ee.Reducer.mode(), geom, 1000, maxPixels=1e9, bestEffort=True)
              .getInfo().get("Map"))
        if lc is not None:
            parts["landcover"] = (LC_INFIL.get(int(lc), 0.5), 0.20)
            srcs.append(ds["worldcover"])
    dem_src = ds["copdem"] or ds["condem"]
    if dem_src:
        dem = (ee.ImageCollection(ds["copdem"]).select("DEM").mosaic()
               if ds["copdem"] else ee.Image(ds["condem"]))
        sl = ee.Terrain.slope(dem).reduceRegion(ee.Reducer.mean(), geom, 1000,
                                                maxPixels=1e9, bestEffort=True).getInfo()
        slope = list(sl.values())[0] if sl else None
        if slope is not None:
            parts["flatness"] = (float(np.clip(1 - slope / 30.0, 0, 1)), 0.15)
            srcs.append(dem_src)
    if not parts:
        return None, srcs
    wsum = sum(w for _, w in parts.values())
    return sum(v * w for v, w in parts.values()) / wsum, srcs


def groundwater_drivers(lat, lng):
    ds = DS()
    t0 = time.time()
    geom, pfaf = basin_geom(lat, lng)
    if geom is None:
        return None
    aq = aq_scores(lat, lng)
    out = {}

    ep_parts = [v for v in (aq.get("gtd_score"), aq.get("bwd_score")) if v is not None]
    ep = (sum(ep_parts) / len(ep_parts)) / 5.0 if ep_parts else None
    out["extraction_pressure"] = _drv(ep, 0.35, "WRI Aqueduct gtd+bwd", "proxy",
        caveat="proxy - site abstraction data required for full EP (CGWB / USGS NWIS in production)")

    if ds["grace"]:
        slope = _grace_trend_cm_yr(geom)
        sev = None if slope is None else float(np.clip(0.5 - slope / 4.0, 0, 1))
        out["aquifer_decline"] = _drv(sev, 0.30, ds["grace"], "regional",
                                      trend_cm_per_yr=None if slope is None else round(slope, 2),
                                      caveat="~300 km resolution - basin/regional signal")
    else:
        out["aquifer_decline"] = _drv(None, 0.30, "GRACE unavailable", "no-data")

    ri, srcs = _recharge_index(geom)
    out["recharge_worry"] = _drv(None if ri is None else 1 - ri, 0.20,
                                 " + ".join(srcs) or "unavailable",
                                 "computed" if ri is not None else "no-data",
                                 recharge_index=None if ri is None else round(ri, 3))

    out["quality_QD"] = _drv(None, 0.15, "no global groundwater-chemistry raster", "no-data",
                             caveat="excluded - weights renormalized; site lab data required")

    res = composite(out)
    res.update({"risk": "groundwater", "pfaf_id": pfaf, "runtime_s": round(time.time() - t0, 1)})
    return res


# ---------------- flood ----------------

def _hsg_class(raw):
    """HYSOGs/HiHydroSoil raw value -> HSG 1-4. Handles HiHydroSoil's x10000 scaling
    and dual classes (11-14 -> D)."""
    if raw is None:
        return None
    v = float(raw)
    if v > 100:
        v = v / 10000.0  # HiHydroSoil v2.0 rasters are scaled by 10,000
    h = int(round(v))
    if h <= 0:
        return None
    return 4 if h > 4 else h


def _wc_class(wc):
    """Snap a WorldCover buffer-mean to the nearest legal class key."""
    if wc is None:
        return None
    return min(CN_TABLE.keys(), key=lambda c: abs(c - wc))


def flood_drivers(lat, lng):
    """Each factor is individually try/except-wrapped: a server-side EE failure in one
    factor degrades THAT factor to no-data (with the error recorded) instead of
    crashing the whole engine."""
    ds = DS()
    t0 = time.time()
    geom, pfaf = basin_geom(lat, lng)
    if geom is None:
        return None
    site = ee.Geometry.Point([lng, lat])
    out = {}

    p_design = None
    try:
        if ds["chirps"]:
            mx = yearly(ds["chirps"], "precipitation", geom, 12, ee.Reducer.max(), 5000, CHIRPS_YEARS)
            vals = np.array([v for v in mx if v is not None], float)
            if len(vals) >= 10:
                p_design = float(vals.mean() + vals.std())
                out["rainfall"] = _drv(float(np.clip(p_design / 120.0, 0, 1)), 0.25,
                                       ds["chirps"], "computed",
                                       design_storm_mm=round(p_design, 1),
                                       method="mean+1std of annual 1-day maxima, /120mm ref")
    except Exception as e:
        out["rainfall"] = _drv(None, 0.25, ds["chirps"] or "CHIRPS", "no-data", error=str(e)[:160])
    if "rainfall" not in out:
        out["rainfall"] = _drv(None, 0.25, "CHIRPS unavailable", "no-data")

    try:
        if ds["hysogs"] and ds["worldcover"] and p_design:
            h = _hsg_class(_pt_val(ee.Image(ds["hysogs"]), lat, lng, 500))
            wc = _wc_class(_pt_val(ee.ImageCollection(ds["worldcover"]).first(), lat, lng, 500, "Map"))
            if h is not None and wc is not None:
                cn = CN_TABLE[wc][h - 1]
                S = 25400.0 / cn - 254.0
                P = p_design
                Q = ((P - 0.2 * S) ** 2 / (P + 0.8 * S)) if P > 0.2 * S else 0.0
                out["runoff_SCS_CN"] = _drv(float(np.clip(Q / P, 0, 1)), 0.25,
                                            f'{ds["hysogs"]} + {ds["worldcover"]}', "computed",
                                            CN=cn, HSG=h, wc_class=wc,
                                            S_mm=round(S, 1), Q_mm=round(Q, 1),
                                            method="NRCS TR-55, AMC II, dual HSG->D")
    except Exception as e:
        out["runoff_SCS_CN"] = _drv(None, 0.25, ds["hysogs"] or "HYSOGs", "no-data", error=str(e)[:160])
    if "runoff_SCS_CN" not in out:
        out["runoff_SCS_CN"] = _drv(None, 0.25,
            "HYSOGs250m pending asset (ORNL DAAC DOI 10.3334/ORNLDAAC/1566)", "no-data",
            caveat="pending asset - upload HYSOGs250m to GEE and re-run")

    try:
        if ds["flowacc"] and ds["condem"]:
            acc = _pt_val(ee.Image(ds["flowacc"]), lat, lng, 500)
            zs = _pt_val(ee.Image(ds["condem"]), lat, lng, 500)
            zmin_d = (ee.Image(ds["condem"]).reduceRegion(ee.Reducer.min(), site.buffer(1000), 500,
                      maxPixels=1e9, bestEffort=True).getInfo())
            zmin = list(zmin_d.values())[0] if zmin_d else None
            if acc is not None and zs is not None and zmin is not None:
                s_acc = float(np.clip(np.log10(acc + 1) / 6.0, 0, 1))
                s_rel = float(np.clip(1 - (zs - zmin) / 30.0, 0, 1))
                out["catchment"] = _drv(0.5 * s_acc + 0.5 * s_rel, 0.20,
                                        f'{ds["flowacc"]} + {ds["condem"]}', "computed",
                                        flow_acc_cells=int(acc), rel_elev_m=round(zs - zmin, 1))
    except Exception as e:
        out["catchment"] = _drv(None, 0.20, "HydroSHEDS", "no-data", error=str(e)[:160])
    if "catchment" not in out:
        out["catchment"] = _drv(None, 0.20, "HydroSHEDS unavailable", "no-data")

    # 3-month window: SPL4 is 3-hourly, a 12-mo x 10-yr composite can time out server-side
    try:
        if ds["smap"]:
            sm = yearly(ds["smap"], "sm_surface", geom, 3, ee.Reducer.mean(), 10000,
                        list(range(2016, 2026)))
            vals = [v for v in sm if v is not None]
            if len(vals) >= 5 and sm[-1] is not None:
                lo, hi = min(vals), max(vals)
                sev = float((sm[-1] - lo) / (hi - lo)) if hi > lo else 0.5
                out["soil_saturation"] = _drv(sev, 0.15, ds["smap"], "computed",
                                              caveat="SMAP top ~5cm; Oct-Dec window each year")
    except Exception as e:
        out["soil_saturation"] = _drv(None, 0.15, ds["smap"] or "SMAP", "no-data", error=str(e)[:160])
    if "soil_saturation" not in out:
        out["soil_saturation"] = _drv(None, 0.15, "SMAP unavailable", "no-data")

    # epoch size checked client-side BEFORE mosaic: reduceRegion on a band-less image errors
    try:
        if ds["ghsl"]:
            ghsl = ee.ImageCollection(ds["ghsl"]).select("built_surface")

            def _epoch(y0, y1):
                sub = ghsl.filterDate(f"{y0}-01-01", f"{y1}-01-01")
                if sub.size().getInfo() == 0:
                    return None
                return _pt_val(sub.mosaic(), lat, lng, 1000, "built_surface")

            b20 = _epoch(2019, 2021)
            b00 = _epoch(1999, 2001)
            if b20 is not None:
                f20 = float(np.clip(b20 / 10000.0, 0, 1))
                delta = float(np.clip((b20 - (b00 or 0)) / 10000.0, 0, 1))
                out["urbanization"] = _drv(float(np.clip(0.7 * f20 + 0.3 * delta, 0, 1)), 0.15,
                                           ds["ghsl"], "computed",
                                           built_frac_2020=round(f20, 3), built_change=round(delta, 3))
    except Exception as e:
        out["urbanization"] = _drv(None, 0.15, ds["ghsl"] or "GHSL", "no-data", error=str(e)[:160])
    if "urbanization" not in out:
        out["urbanization"] = _drv(None, 0.15, "GHSL unavailable", "no-data")

    res = composite(out)
    res.update({"risk": "flood", "pfaf_id": pfaf, "runtime_s": round(time.time() - t0, 1)})
    return res


ENGINES = {"drought": drought_drivers, "groundwater": groundwater_drivers, "flood": flood_drivers}

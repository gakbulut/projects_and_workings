import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import random
import time
from time import sleep
import re
import math

import json
import urllib.parse
import geopandas as gpd
import math
import os
import osmnx as ox
import folium
import webbrowser
from functools import partial
from IPython.display import display
import traceback

from shapely import affinity 
from shapely.geometry import shape, box, mapping, Polygon, LineString, Point, MultiLineString
from shapely.validation import explain_validity
from shapely.ops import linemerge, nearest_points, unary_union, split, polygonize, snap
from shapely.affinity import translate, scale
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from pyproj import Transformer
from typing import List
import geopandas as gpd

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pprint import pprint, PrettyPrinter

# -----------------------------
# CRS
# -----------------------------
CRS_LATLON = "EPSG:4326"  # Metre
CRS_FEET = "EPSG:2276"   # Dallas   

def geocode_nominatim(address):   
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "parcel-script"}
    r = requests.get(url, params=params, headers=headers)
    data = r.json()   
    if not data:
        raise Exception("Nominatim address not found")
    print("Nominatim kullanıldı")
    time.sleep(1)  # OSM rate limit
    lat = float(data[0]["lat"])
    lon = float(data[0]["lon"])

    return lat, lon

def geocode_mapbox(address):    
    access_token = "pk.eyJ1IjoibWFjYXIiLCJhIjoiY21tZjJhbXR0MDQxdDJxcHE2ZW9wdW5hOSJ9.RXghHdxGU1M1wp30OGarpg"     

    url = "https://api.mapbox.com/search/geocode/v6/forward"
    params = {
        "q": address,
        "limit": 1,
        "country": "us",               # ABD adresleri için
        "types": "address,street",     # yanlış sonuçları engellemek için
        "access_token": access_token
    }     
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print("Mapbox Request error:", e)
        return None
    data = r.json()
    # pprint(data)
    # print(json.dumps(data, indent=4))
    if len(data["features"]) == 0:
        raise Exception("Mapbox address not found")
    feature = data["features"][0]

    # Mapbox v6'da feature_type ve place_formatted kullan
    feature_type = feature.get("properties", {}).get("feature_type")
    # postcode veya place ise reddet
    if feature_type not in ["address", "street"]:
        print("Rejected feature_type:", feature_type)
        return None
    print("Mapbox feature_type:", feature_type)

    # Koordinatlar
    coords = feature.get("geometry", {}).get("coordinates", [None, None])
    lon, lat = coords
    print("Mapbox kullanıldı")

    return lat, lon

def geocode_opencage(address):
    OPENCAGE_TOKEN = "OPENCAGE_TOKEN"
    url = "https://api.opencagedata.com/geocode/v1/json"
    params = {"q": address, "key": OPENCAGE_TOKEN, "limit": 1}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    if len(data["results"]) == 0:
        raise Exception("OpenCage adres bulamadı")
    loc = data["results"][0]["geometry"]
    print("OpenCage kullanıldı")

    return loc["lat"], loc["lng"]

def geocode_google(address):
    GOOGLE_TOKEN = "GOOGLE_TOKEN"
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": GOOGLE_TOKEN}
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    if data["status"] != "OK":
        raise Exception("Google adres bulamadı")
    loc = data["results"][0]["geometry"]["location"]
    print("Google kullanıldı")

    return loc["lat"], loc["lng"]

def get_coordinates_multy(address):
    geocoders = [
        # geocode_google,
        # geocode_opencage,  
        geocode_mapbox,            
        geocode_nominatim        
    ]
    for g in geocoders:
        try:
            return g(address)
        except Exception as e:
            print("Geocoder hata:", e)
            print("Sonraki deneniyor...\n")

    raise Exception("Adres çözülemedi")

# Temizleme fonksiyonu
def normalize_us_address(address):
    a = address

    # ------------------------------------------------
    # 0️⃣ Çoklu house number düzelt (305-307 → 305)
    # ------------------------------------------------
    m = re.match(r"^\s*([\d\-\s/&]+)", a)
    if m:
        numbers = re.findall(r"\d+", m.group(1))
        if numbers:
            last_number = numbers[-1]
            a = re.sub(r"^\s*([\d\-\s/&]+)", last_number, a)

    # ------------------------------------------------
    # 1️⃣ Unit / Apt / Lot temizle
    # ------------------------------------------------
    a = re.sub(r"#\s*\w+", "", a, flags=re.IGNORECASE)
    a = re.sub(r"\b(APT|UNIT|STE|SUITE|LOT|BLDG|BUILDING)\s*\w+", "", a, flags=re.IGNORECASE)
    # ------------------------------------------------
    # 2️⃣ yön kısaltmaları
    # ------------------------------------------------
    directions = {
        "NORTH":"N",
        "SOUTH":"S",
        "EAST":"E",
        "WEST":"W"
    }
    for k,v in directions.items():
        a = re.sub(rf"\b{k}\b", v, a, flags=re.IGNORECASE)
    # ------------------------------------------------
    # 3️⃣ street type kısaltmaları
    # ------------------------------------------------
    street_types = {
        "STREET":"St",
        "AVENUE":"Ave",
        "ROAD":"Rd",
        "DRIVE":"Dr",
        "LANE":"Ln",
        "BOULEVARD":"Blvd",
        "COURT":"Ct",
        "PLACE":"Pl",
        "TERRACE":"Ter",
        "PARKWAY":"Pkwy"
    }
    for k, v in street_types.items():
        a = re.sub(rf"\b{k}\b", v, a, flags=re.IGNORECASE)
    # ------------------------------------------------
    # 4️⃣ virgül boşluk düzelt
    # ------------------------------------------------
    a = re.sub(r"\s+,", ",", a)
    # ------------------------------------------------
    # 5️⃣ fazla boşluk temizle
    # ------------------------------------------------
    a = re.sub(r"\s+", " ", a).strip()

    return a

# Varyasyon Fonksiyonu
def street_variants(address):
    variants = [address]
    directions = ["N","S","E","W"]
    street_types = [
        "ST","STREET",
        "AVE","AVENUE",
        "RD","ROAD",
        "DR","DRIVE",
        "LN","LANE",
        "BLVD","BOULEVARD",
        "CT","COURT",
        "PL","PLACE",
        "TER","TERRACE",
        "PKWY","PARKWAY"
    ]
    words = address.split()
    # direction varsa birleşme yapma
    if any(w.upper() in directions for w in words):
        return variants

    # street type varsa onu birleştirmeye dahil etme
    for i,w in enumerate(words):
        if w.upper().strip(",") in street_types and i >= 2:
            merged = words.copy()
            # Valley Dale → Valleydale
            merged[i-2] = merged[i-2] + merged[i-1]
            del merged[i-1]
            variants.append(" ".join(merged))
            break

    return list(set(variants))  

# Hepsini(Temizleme+Varyasyon) birleştiren fonksiyon
def generate_address_candidates(address):
    base = normalize_us_address(address)
    candidates = [base]
    for v in street_variants(base):
        candidates.append(v)    
    # print("list(set(candidates)):::", list(set(candidates)))        
    return list(set(candidates))

# Get Coordinates
def get_coordinates_cleaned_addressed(address):
    for a in generate_address_candidates(address):
        try:
            lat, lon = get_coordinates_multy(a)
            print("Found:", a)
            return lat, lon
        except:
            pass
    raise Exception("Address not found")

# Parcel Polygon Finder - Koordinat ile
def get_parcel_polygon(lon, lat):

    url = "https://gis.dallascityhall.com/arcgis/rest/services/Basemap/DallasTaxParcels/FeatureServer/0/query"

    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "returnCentroid": "true",
        "f": "json"
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if "features" in data and len(data["features"]) > 0:

            feature = data["features"][0]
            attr = feature["attributes"]
            geom = feature["geometry"]

            acct = attr.get("ACCT")
            area = round(attr.get("Shape__Area") or attr.get("SHAPE.STArea()"), 2)
            perimeter = round(attr.get("Shape__Length") or attr.get("SHAPE.STLength()"), 2)

            geometry = geom.get("rings", [[]])[0]

            # centroid hesapla
            centroidx, centroidy = None, None

            # 1️⃣ API centroid            
            centroid = feature.get("centroid")
            if centroid:
                centroidx = centroid["x"]
                centroidy = centroid["y"]
                print("API centroid kullanıldı.")

            # 2️⃣ fallback shapely
            elif geometry:
                polygon = Polygon(geometry)
                c = polygon.centroid
                centroidx = c.x
                centroidy = c.y
                print("Shapely ile centroid hesaplandı.")

            return acct, area, perimeter, centroidx, centroidy, geometry, data

        else:
            print("⚠️ Feature bulunamadı:", data)

    except Exception as e:
        print("Query error:", e)

    return None, None, None, None, None, None, None

def get_parcel_polygon2(lon, lat):

    # global session (önerilir)
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    url = "https://gis.dallascityhall.com/arcgis/rest/services/Basemap/DallasTaxParcels/FeatureServer/0/query"

    params = {
        # ArcGIS için daha doğru format (tek string yerine geometry JSON önerilir ama bu endpoint bunu kabul ediyor)
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "returnCentroid": "true",
        "f": "json"
    }

    try:
        r = session.get(url, params=params, timeout=(5, 30))
        r.raise_for_status()

        data = r.json()

        if not data or "features" not in data or len(data["features"]) == 0:
            print("⚠️ Feature bulunamadı")
            return None, None, None, None, None, None, None

        feature = data["features"][0]
        attr = feature.get("attributes", {})
        geom = feature.get("geometry", {})

        acct = attr.get("ACCT")

        area = attr.get("Shape__Area") or attr.get("SHAPE.STArea()")
        perimeter = attr.get("Shape__Length") or attr.get("SHAPE.STLength()")

        area = round(float(area), 2) if area else None
        perimeter = round(float(perimeter), 2) if perimeter else None

        geometry = None
        centroidx, centroidy = None, None

        # geometry parse
        if geom and "rings" in geom:
            geometry = geom["rings"][0]

        # centroid (API)
        centroid = feature.get("centroid")
        if centroid:
            centroidx = centroid.get("x")
            centroidy = centroid.get("y")
            print("API centroid kullanıldı.")

        # fallback centroid
        elif geometry:
            try:
                polygon = Polygon(geometry)
                c = polygon.centroid
                centroidx, centroidy = c.x, c.y
                print("Shapely ile centroid hesaplandı.")
            except Exception as ge:
                print("Geometri centroid hatası:", ge)

        return acct, area, perimeter, centroidx, centroidy, geometry, data

    except requests.exceptions.RequestException as e:
        print("Query error (network):", e)
    except ValueError as e:
        print("JSON parse error:", e)
    except Exception as e:
        print("Unexpected error:", e)

    return None, None, None, None, None, None, None

# Parcel Polygon Finder - Adres ile
def get_parcel_polygon_address(address):

    url = "https://gis.dallascityhall.com/arcgis/rest/services/Basemap/DallasTaxParcels/FeatureServer/0/query"
   
    # def parse_address(address):
    #     # "1500 Fairview Ave, Dallas, TX 75223"
        
    #     first_part = address.split(",")[0]  # "1500 Fairview Ave"
    #     parts = first_part.strip().split()

    #     st_num = parts[0]  # 1500
    #     st_name = " ".join(parts[1:]).upper()  # FAIRVIEW AVE

    #     return st_num, st_name

    def normalize_street_type(word):
        mapping = {
            "STREET": "ST",
            "ST": "ST",
            "AVENUE": "AVE",
            "AVE": "AVE",
            "ROAD": "RD",
            "RD": "RD",
            "DRIVE": "DR",
            "DR": "DR",
            "LANE": "LN",
            "LN": "LN",
            "BOULEVARD": "BLVD",
            "BLVD": "BLVD"
        }
        return mapping.get(word.upper(), word.upper())


    def parse_address(address):
        first_part = address.split(",")[0]
        parts = first_part.strip().split()

        st_num = parts[0]

        # son kelime genelde street type
        street_type = normalize_street_type(parts[-1])
        street_name = " ".join(parts[1:-1]).upper()

        st_name = f"{street_name} {street_type}"
        print("st_name:", st_name)

        return st_num, st_name
    
    st_num, st_name = parse_address(address)

    params = {
        "where": f"ST_NUM = '{st_num}' AND ST_NAME = '{st_name}'",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "json"
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if "features" in data and len(data["features"]) > 0:

            feature = data["features"][0]
            attr = feature["attributes"]
            geom = feature["geometry"]

            acct = attr.get("ACCT")
            area = round(attr.get("Shape__Area") or attr.get("SHAPE.STArea()"), 2)
            perimeter = round(attr.get("Shape__Length") or attr.get("SHAPE.STLength()"), 2)

            geometry = geom.get("rings", [[]])[0]

            # centroid hesapla
            centroidx, centroidy = None, None

            # 1️⃣ API centroid            
            centroid = feature.get("centroid")
            if centroid:
                centroidx = centroid["x"]
                centroidy = centroid["y"]
                print("API centroid kullanıldı.")

            # 2️⃣ fallback shapely
            elif geometry:
                polygon = Polygon(geometry)
                c = polygon.centroid
                centroidx = c.x
                centroidy = c.y
                print("Shapely ile centroid hesaplandı.")

            return acct, area, perimeter, centroidx, centroidy, geometry, data

        else:
            print("⚠️ Feature bulunamadı:", data)

    except Exception as e:
        print("Query error:", e)

    return None, None, None, None, None, None, None

# Zoning Finder
def get_zoning(lon, lat):
    # zoning_url = "https://services6.arcgis.com/eaXMnnhlTkGbwQYU/ArcGIS/rest/services/City_of_Dallas_Master_Landbase_Map4/FeatureServer/14/query"
    zoning_url = "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/Dallas_Zoning/FeatureServer/15/query"

    # ArcGIS point geometry JSON formatı
    point_geom = {
        "x": lon,
        "y": lat,
        "spatialReference": {"wkid": 4326}
    }

    params = {
        "f": "json",
        "geometry": json.dumps(point_geom),  # Burada önemli!
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*"
    }

    try:
        r = requests.get(zoning_url, params=params, timeout=15)
        data = r.json()

        if "features" in data and data["features"]:
            zoning = data["features"][0]["attributes"].get("ZONE_DIST")
            zoning_district = data["features"][0]["geometry"].get("rings")
        else:
            zoning = None
            print("⚠️ Zoning bulunamadı:", data)

        return zoning, zoning_district, data

    except Exception as e:
        print("Zoning query error:", e)
        return None, None

# Dallas_Zoning FeatureServer Katman Listesi
def layer_map_information():
    print("Dallas_Zoning FeatureServer Katman Listesi")
    # Dallas_Zoning FeatureServer Katman Listesi
    # Layer ID	Layer Adı	                            Ne için
    # 0	        Deed_restrictions	                    Tapu kısıtlama (deed restriction) polygon’ları
    # 1	        Dry_Overlay	                            “Dry zone” overlay alanları
    # 2	        Historic_Overlay	                    Historic zoning overlay alanları
    # 3	        Historic_Subdistricts	                Historic alt bölgeleri
    # 4	        SUP	                                    Special Use Permits (özel kullanım izinleri)
    # 5	        NSO_Overlay	                            Neighborhood Stabilization Overlay alanları
    # 6	        NSO_Subdistricts	                    NSO alt bölgeleri
    # 7	        MD_Overlay	                            Medical District (MD) overlay
    # 8	        CD_Subdistricts	                        Community District alt bölgeleri
    # 9	        PD_Subdistricts	                        Planned Development alt bölgeleri
    # 10	    PD193_Oaklawn	                        Oaklawn PD (Planlı Gelişim) alanı
    # 11	    PDS_Subdistricts	                    PD alt bölge layer’ı
    # 12	    Height_Map_Overlay	                    Bina yükseklik haritası overlay
    # 13	    Shop_Front_Overlay	                    Shopfront overlay alanları
    # 14	    Parking_Managment_Overlay	            Otopark yönetimi overlay
    # 15	    Base_Zoning	                            Ana zoning polygon layer’i (ZONE_DIST gibi zoning kodları burada)
    # 16	    SPSD_Overlay	                        SPSD overlay alanları
    # 17	    Pedestrian_Overlay	                    Yaya yolları overlay alanları
    # 18	    Turtle_Creek_Setback_Corridor	        Turtle Creek set-back koridoru
    # 19	    Demolotion_Delay_Overlay	            Yıkım geciktirme overlay’i


    # LAYER_MAP = {
    #     0: "Deed_Restrictions",
    #     1: "Dry_Overlay",
    #     2: "Historic_Overlay",
    #     3: "Historic_Subdistricts",
    #     4: "SUP",
    #     5: "NSO_Overlay",
    #     6: "NSO_Subdistricts",
    #     7: "MD_Overlay",
    #     8: "CD_Subdistricts",
    #     9: "PD_Subdistricts",
    #     10: "PD193_Oaklawn",    
    #     11: "PDS_Subdistricts",
    #     12: "Height_Map_Overlay",
    #     13: "Shop_Front_Overlay",
    #     14: "Parking_Managment_Overlay",
    #     15: "Base_Zoning",
    #     16: "SPSD_Overlay",
    #     17: "Pedestrian_Overlay",
    #     18: "Turtle_Creek_Setback_Corridor",
    #     19: "Demolotion_Delay_Overlay"
    # }

# Tek fonksiyon: Parcel + Zoning + PD Subdistricts
def get_parcel_and_zoning(lon, lat):

    # ----------------------------------------------------
    # Layer map
    # ----------------------------------------------------
    LAYER_MAP = {    
        9: "PD_Subdistricts",   
        15: "Base_Zoning"  
    }
    FEATURESERVER_BASE = "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/Dallas_Zoning/FeatureServer"

    # ---------------------------
    # 1️⃣ Parcel sorgusu
    # ---------------------------
    parcel_url = "https://gis.dallascityhall.com/arcgis/rest/services/Basemap/DallasTaxParcels/FeatureServer/0/query"
    parcel_params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "returnCentroid": "true",
        "f": "json"
    }

    try:
        r = requests.get(parcel_url, params=parcel_params, timeout=15)
        parcel_data = r.json()

        if "features" in parcel_data and len(parcel_data["features"]) > 0:
            feature = parcel_data["features"][0]
            attr = feature["attributes"]
            geom = feature["geometry"]

            acct = attr.get("ACCT")
            area = round(attr.get("Shape__Area") or attr.get("SHAPE.STArea()"), 2)
            perimeter = round(attr.get("Shape__Length") or attr.get("SHAPE.STLength()"), 2)
            geometry = geom.get("rings", [[]])[0]

            # centroid
            centroidx, centroidy = None, None
            centroid = geom.get("centroid")
            if centroid:
                centroidx = centroid["x"]
                centroidy = centroid["y"]
            elif geometry:
                polygon = Polygon(geometry)
                c = polygon.centroid
                centroidx = c.x
                centroidy = c.y
        else:
            print("⚠️ Parcel bulunamadı:", parcel_data)
            acct, area, perimeter, centroidx, centroidy, geometry = [None]*6

    except Exception as e:
        print("Parcel query error:", e)
        acct, area, perimeter, centroidx, centroidy, geometry, parcel_data = [None]*7

    # ---------------------------
    # 2️⃣ Zoning & PD Subdistricts sorgusu
    # ---------------------------
    point_geom = {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}
    zoning_result = {}

    for layer_id, layer_name in LAYER_MAP.items():
        url = f"{FEATURESERVER_BASE}/{layer_id}/query"
        params = {
            "f": "json",
            "geometry": json.dumps(point_geom),
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*"
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            if "features" in data and data["features"]:                
                zoning_result[layer_name] = data["features"][0]["attributes"]
            else:                
                zoning_result[layer_name] = None
                print(f"⚠️ Zoning {layer_name} bulunamadı:", data)
        except Exception as e:
            print(f"⚠️ Zoning query error {layer_name} ({layer_id}): {e}")
            zoning_result[layer_name] = None

    # ---------------------------
    # PD kontrolü
    # ---------------------------
    # pd_info = [None, None, None]  # zoning, SUBDIST1, SUBDIST2
    # base_zoning = zoning_result.get("Base_Zoning")
    # pd_sub = zoning_result.get("PD_Subdistricts")

    # if base_zoning and base_zoning.get("ZONE_DIST") == "PD" and pd_sub:
    #     pd_info[0] = f"PD-{pd_sub.get("PD_NUM")}"         
    #     if pd_sub.get("SUBDIST1") and pd_sub.get("SUBDIST1") is not None:
    #         pd_info[1] = pd_sub.get("SUBDIST1") if pd_sub.get("SUBDIST1") is not None else None
    #     if pd_sub.get("SUBDIST2") and pd_sub.get("SUBDIST2") is not None:
    #         pd_info[2] = pd_sub.get("SUBDIST2") if pd_sub.get("SUBDIST2") is not None else None   
    #     long_zoning = base_zoning.get("LONG_ZONE_DIST")
    #     zoning = base_zoning.get("ZONE_DIST")
        
    # else: 
    #     long_zoning = base_zoning.get("LONG_ZONE_DIST")
    #     zoning = base_zoning.get("ZONE_DIST")
    
    pd_info = [None, None, None]  # zoning, SUBDIST1, SUBDIST2
    base_zoning = zoning_result.get("Base_Zoning") if zoning_result else None
    pd_sub = zoning_result.get("PD_Subdistricts") if zoning_result else None
    long_zoning = None
    zoning = None
    
    # Base zoning varsa    
    if base_zoning:
        long_zoning = base_zoning.get("LONG_ZONE_DIST")
        zoning = base_zoning.get("ZONE_DIST")
        
        # PD ise    
        if zoning == "PD" and pd_sub:
            pd_info[0] = f"PD-{pd_sub.get('PD_NUM')}"
            sub1 = pd_sub.get("SUBDIST1")
            sub2 = pd_sub.get("SUBDIST2")
            if sub1:
                pd_info[1] = sub1
            if sub2:
                pd_info[2] = sub2
  

    # ---------------------------
    # Return
    # ---------------------------
    return {
        "acct": acct,
        "area": area,
        "perimeter": perimeter,
        "centroidx": centroidx,
        "centroidy": centroidy,
        "parcel_polygon": geometry,
        "parcel_data": parcel_data,
        "long_zoning": long_zoning,
        "zoning": zoning,
        "zoning_layers": zoning_result,
        "pd_info": pd_info  # [PD_NUM, SUBDIST1, SUBDIST2]
    }

# Zoning + PD Subdistricts
def get_zoning_and_pd_subdistricts2(lon, lat):

    LAYER_MAP = {    
        9: "PD_Subdistricts",   
        15: "Base_Zoning"  
    }

    FEATURESERVER_BASE = "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/Dallas_Zoning/FeatureServer"

    point_geom = {
        "x": lon,
        "y": lat,
        "spatialReference": {"wkid": 4326}
    }

    zoning_result = {}

    for layer_id, layer_name in LAYER_MAP.items():
        url = f"{FEATURESERVER_BASE}/{layer_id}/query"

        params = {
            "f": "json",
            "geometry": json.dumps(point_geom),
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*"
        }

        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()

            if "features" in data and data["features"]:
                zoning_result[layer_name] = data["features"][0]["attributes"]
            else:
                zoning_result[layer_name] = None
                print(f"⚠️ Zoning {layer_name} bulunamadı:", data)

        except Exception as e:
            print(f"⚠️ Zoning query error {layer_name} ({layer_id}): {e}")
            zoning_result[layer_name] = None

    pd_info = [None, None, None]

    base_zoning = zoning_result.get("Base_Zoning")
    pd_sub = zoning_result.get("PD_Subdistricts")

    # ✅ Base zoning yoksa akış kesilmesin
    if base_zoning is None:
        return None, None, pd_info

    long_zoning = base_zoning.get("LONG_ZONE_DIST")
    zoning = base_zoning.get("ZONE_DIST")

    # ✅ PD varsa detayları doldur
    if zoning == "PD" and pd_sub is not None:
        pd_num = pd_sub.get("PD_NUM")

        if pd_num is not None:
            pd_info[0] = f"PD-{pd_num}"

        pd_info[1] = pd_sub.get("SUBDIST1")
        pd_info[2] = pd_sub.get("SUBDIST2")

    return long_zoning, zoning, pd_info

def get_zoning_and_pd_subdistricts(lon, lat):

    # ----------------------------------------------------
    # Layer map
    # ----------------------------------------------------
    LAYER_MAP = {    
        9: "PD_Subdistricts",   
        15: "Base_Zoning"  
    }
    FEATURESERVER_BASE = "https://services2.arcgis.com/rwnOSbfKSwyTBcwN/arcgis/rest/services/Dallas_Zoning/FeatureServer"

    # ---------------------------
    # 2️⃣ Zoning & PD Subdistricts sorgusu
    # ---------------------------
    point_geom = {"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}
    zoning_result = {}

    for layer_id, layer_name in LAYER_MAP.items():
        url = f"{FEATURESERVER_BASE}/{layer_id}/query"
        params = {
            "f": "json",
            "geometry": json.dumps(point_geom),
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*"
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            # display("data:::", data)
            if "features" in data and data["features"]:                
                zoning_result[layer_name] = data["features"][0]["attributes"]
            else:                
                zoning_result[layer_name] = None
                print(f"⚠️ Zoning {layer_name} bulunamadı:", data)
        except Exception as e:
            print(f"⚠️ Zoning query error {layer_name} ({layer_id}): {e}")
            zoning_result[layer_name] = None

    # ---------------------------
    # PD kontrolü
    # ---------------------------
    pd_info = [None, None, None]  # zoning, SUBDIST1, SUBDIST2
    base_zoning = zoning_result.get("Base_Zoning")
    # display("base_zoning:::", base_zoning)
    pd_sub = zoning_result.get("PD_Subdistricts")

    # ✅ Base zoning yoksa akış kesilmesin
    if base_zoning is None:
        return None, None, pd_info

    if base_zoning and base_zoning.get("ZONE_DIST") == "PD" and pd_sub:
        pd_info[0] = f"PD-{pd_sub.get('PD_NUM')}"         
        if pd_sub.get("SUBDIST1") and pd_sub.get("SUBDIST1") is not None:
            pd_info[1] = pd_sub.get("SUBDIST1") if pd_sub.get("SUBDIST1") is not None else None
        if pd_sub.get("SUBDIST2") and pd_sub.get("SUBDIST2") is not None:
            pd_info[2] = pd_sub.get("SUBDIST2") if pd_sub.get("SUBDIST2") is not None else None   
        long_zoning = base_zoning.get("LONG_ZONE_DIST")
        zoning = base_zoning.get("ZONE_DIST")
        
    else: 
        long_zoning = base_zoning.get("LONG_ZONE_DIST")
        zoning = base_zoning.get("ZONE_DIST")

    # ---------------------------
    # Return
    # ---------------------------
    return long_zoning, zoning, pd_info

# İç açı hesaplama
def calculate_angle(p0, p1, p2):
    v0 = np.array(p0) - np.array(p1)
    v1 = np.array(p2) - np.array(p1)
    norm_v0 = np.linalg.norm(v0)
    norm_v1 = np.linalg.norm(v1)
    if norm_v0 == 0 or norm_v1 == 0:
        return 180.0  # Ardışık noktalar aynıysa düz açı kabul et
    v0_norm = v0 / norm_v0
    v1_norm = v1 / norm_v1
    cos_angle = np.clip(np.dot(v0_norm, v1_norm), -1.0, 1.0)
    angle_rad = np.arccos(cos_angle)
    angle_deg = np.degrees(angle_rad)    
    return angle_deg  # İç açı döndürülüyor

# Önemli(Eşik Değere Göre) köşe tespiti
def get_whole_and_significant_angles(polygon_coords, max_angle_deg):   
    whole_angles = []
    significant_angles = []
    indices = []
    n = len(polygon_coords)     
    for i in range(n):
        p0 = polygon_coords[i - 1]
        p1 = polygon_coords[i]
        p2 = polygon_coords[(i + 1) % n]        
        angle_inner = calculate_angle(p0, p1, p2)  # iç açı  
        whole_angles.append((p1, angle_inner))           
        # print(f"angle-{i+1}: {angle_inner:.2f}")        
        if angle_inner < max_angle_deg:
            significant_angles.append((p1, angle_inner)) 
            indices.append(i)       
    return whole_angles, significant_angles, indices

# Düz kenar uzunluğu
def calculate_edges_straight(significant_angles):
    edges = []
    for i in range(len(significant_angles)):
        p1 = significant_angles[i][0]
        p2 = significant_angles[(i + 1) % len(significant_angles)][0]
        dist_ft = geodesic((p1[1], p1[0]), (p2[1], p2[0])).ft 
        edges.append((p1, p2, dist_ft))  
    return edges

# Gerçek kenar uzunluğu (segment toplamı)
def calculate_edges_segmentTotal(coords, corner_indices):
    edges = []
    n = len(coords)

    segment_to_edge = {}   # 🔥 reverse map

    for i in range(len(corner_indices)):
        start = corner_indices[i]
        end = corner_indices[(i + 1) % len(corner_indices)]

        dist_ft = 0
        j = start

        source_ids = []

        while j != end:
            p1 = coords[j]
            p2 = coords[(j + 1) % n]

            dist_ft += geodesic((p1[1], p1[0]), (p2[1], p2[0])).ft

            source_ids.append(j)

            # 🔥 REVERSE MAPPING
            segment_to_edge[j] = i

            j = (j + 1) % n   

        edges.append((
            coords[start],
            coords[end],
            dist_ft,
            source_ids,
            i   # 🔥 edge_id eklendi
        ))    

    return edges, segment_to_edge

# Görselleştirme Fonksiyonu - Karşılaştırmalı
def visualize_parcel_comparison(parcel_polygon_GIS, max_angle_deg):

    # Polygon objeleri (son tekrar eden noktayı çıkarıyoruz)
    coords = parcel_polygon_GIS[:-1]
    poly_GIS = Polygon(coords) 

    # parsel köşeleri
    angles_GIS, sig_GIS, indices = get_whole_and_significant_angles(coords, max_angle_deg)

    # kenarlar   
    edges_whole = calculate_edges_straight(angles_GIS)
    edges_straight = calculate_edges_straight(sig_GIS)
    edges_real_raw, segment_to_edge = calculate_edges_segmentTotal(coords, indices) 
    
    edges_real = []

    for i, e in enumerate(edges_real_raw):
        p1, p2, length, source_ids, edge_id = e

        edges_real.append((
            p1,
            p2,
            length,
            source_ids,
            edge_id
        ))

    # -----------------------------
    # DEBUG PRINTS
    # -----------------------------
    print("Parcel coords:", len(coords))
    print("Total angles:", len(angles_GIS))
    print("Significant angles:", len(sig_GIS))
    print("Corner indices:", indices)
    print("Edges real count:", len(edges_real))
    print("Segment_to_edge:", segment_to_edge)   

    return edges_whole, edges_real, coords, segment_to_edge

# Parsel Kenarları Tespiti Fonksiyonu
def real_edges(address, max_angle_deg):
    print("Adres:", address)
    parcel_polygon = None
    # -------------------------------------------------
    # 1️⃣ Önce koordinat ile dene
    # -------------------------------------------------
    try:
        lat, lon = get_coordinates_cleaned_addressed(address)
        print("Coordinates(Lat/Lon):", lat, lon)
        acct, area, perimeter, centroidx, centroidy, parcel_polygon, data = get_parcel_polygon(lon, lat)
        print("KOORDİNAT ile polygon bulundu.")
        # print("parcel_polygon:::", parcel_polygon)
        # print("data:::", data)
    except Exception as e:
        print("⚠️ Coordinate method failed:", e)
        lat, lon = None, None

    # -------------------------------------------------
    # 2️⃣ Eğer başarısızsa → address query
    # -------------------------------------------------
    if parcel_polygon is None:
        try:
            print("🔄 Trying address-based parcel query...")
            acct, area, perimeter, centroidx, centroidy, parcel_polygon, data = get_parcel_polygon_address(address)
            # centroid'tan lat/lon üretelim
            lat, lon = centroidy, centroidx
            print("ADRES ile polygon bulundu.")
            # print("parcel_polygon:::", parcel_polygon)
            # print("data:::", data)
        except Exception as e:
            print("❌ Address method also failed:", e)
            return None, None, None, None, None

    # -------------------------------------------------
    # 3️⃣ zoning çek
    # -------------------------------------------------
    long_zoning, zoning, pd_info = get_zoning_and_pd_subdistricts(lon, lat)
    print("long_zoning:", long_zoning)
    print("zoning:", zoning)
    print("pd_info:", pd_info)

    # -------------------------------------------------
    # 3️⃣ edges
    # -------------------------------------------------    
    edges_whole, edges_real, coords, segment_to_edge = visualize_parcel_comparison(parcel_polygon, max_angle_deg)

    edges_real_with_id = []
    # display("edges_whole:::::", edges_whole)
    # display("edges_real:::::", edges_real)   

    for p1, p2, length, source_ids, edge_id in edges_real:
        edges_real_with_id.append((
            p1,
            p2,
            length,
            source_ids,
            edge_id
        ))

    # debug
    for e in edges_real_with_id:
        print(f"edge {e[4]} | length: {e[2]:.1f} | source_ids {e[3]}")

    return (
        lat, lon, acct, area, perimeter,
        parcel_polygon,
        coords,
        edges_real_with_id,
        edges_whole,
        segment_to_edge,
        long_zoning,
        zoning,
        pd_info,
    )

# ZIP kodu ile geocode edilen bölgenin yollarını çekme ve kaydetme (GPKG)
def get_roads_for_zip(address):
    """
    Verilen adres için OSM yollarını getirir ve CRS feet'e çevirir.
    roads_dir / city / roads_zipcode.gpkg
    Eğer dosya yoksa OSM'den çeker ve kaydeder.
    
    Args:
        address (str): "street, city, zip, state, country"
        network_type (str): "drive", "walk", vb.
        crs_feet (str): CRS feet (Dallas için EPSG:2276)
        roads_dir (str): Ana klasör

    Returns:
        roads_gdf (GeoDataFrame): CRS feet'e dönüştürülmüş yollar
    """  

    # -----------------------------
    # 1️⃣ Adresten city ve zip çek
    # -----------------------------
    state = "Texas"
    country = "USA"
    parts = [p.strip() for p in address.split(",")]
    city = parts[1].lower()          # 'dallas'
    zip_code = parts[2].split()[-1]  # '75230'
    address_part = f"{parts[2].split()[-1]}, {parts[1]}, {state}, {country}"
    # print(f"Adres: {address}")
    # print(f"Adres_part: {address_part}")
    # print(f"City: {city}")
    # print(f"ZIP: {zip_code}")

    # -----------------------------
    # 2️⃣ Klasör ve dosya yolu
    # -----------------------------
    roads_dir="roads"
    city_dir = os.path.join(roads_dir, city)
    os.makedirs(city_dir, exist_ok=True)
    file_path = os.path.join(city_dir, f"roads_{zip_code}.gpkg")
    print(f"file_path: {file_path}")

    # -----------------------------
    # 3️⃣ Dosya varsa oku
    # -----------------------------
    if os.path.exists(file_path):
        print(f"✅ Daha önce çekilmiş dosya bulundu: {file_path}")
        roads_gdf = gpd.read_file(file_path, layer="roads")
    
    else:
        # print(f"⚡ Dosya bulunamadı. OSM'den çekiliyor: {address_part}")
        # # ZIP kodunu polygon olarak al
        # gdf_zip = ox.geocoder.geocode_to_gdf(address_part) # GeoDataFrame döner      
        # polygon_zip = gdf_zip.iloc[0].geometry
        # # Graph oluştur
        # G_zip = ox.graph_from_polygon(polygon_zip, network_type="drive")
        # # Kenarlara uzunluk ekle (opsiyonel)
        # # G_zip = ox.distance.add_edge_lengths(G_zip)

        G_zip = None

        # -----------------------------
        # 1) ZIP POLYGON
        # -----------------------------
        try:
            gdf_zip = ox.geocoder.geocode_to_gdf(address_part)
            polygon_zip = gdf_zip.iloc[0].geometry

            if polygon_zip.geom_type not in ["Polygon", "MultiPolygon"]:
                raise TypeError(f"ZIP polygon değil: {polygon_zip.geom_type}")

            G_zip = ox.graph_from_polygon(
                polygon_zip,
                network_type="drive",
                simplify=True
            )

            print("✅ graph_from_polygon başarılı")

        except Exception as e:
            print("⚠️ graph_from_polygon başarısız:", e)
            print("⚠️ graph_from_address deneniyor")            


        # -----------------------------
        # 2) ADDRESS BUFFER
        # -----------------------------
        if G_zip is None:
            try:
                G_zip = ox.graph_from_address(
                    address_part,
                    dist=8000,          # metre
                    network_type="drive",
                    simplify=True
                )

                print("✅ graph_from_address başarılı")

            except Exception as e:
                print("⚠️ graph_from_address başarısız:", e)


        # -----------------------------
        # 3) POINT BUFFER
        # -----------------------------
        if G_zip is None:
            try:
                lat, lon = ox.geocoder.geocode(address_part)

                G_zip = ox.graph_from_point(
                    (lat, lon),
                    dist=8000,          # metre
                    network_type="drive",
                    simplify=True
                )

                print("✅ graph_from_point başarılı")

            except Exception as e:
                print("❌ graph_from_point de başarısız:", e)


        # -----------------------------
        # 4) SON KONTROL
        # -----------------------------
        if G_zip is None:
            raise ValueError(f"OSM road data alınamadı: {address_part}")


        # -----------------------------
        # ROADS GDF + SAVE
        # -----------------------------
        roads_gdf = ox.graph_to_gdfs(G_zip, nodes=False, edges=True)        

        # GPKG olarak kaydet
        roads_gdf.to_file(file_path, layer="roads", driver="GPKG")
        print(f"✅ OSM verisi çekildi ve kaydedildi: {file_path}")   
        print("roads count:", len(roads_gdf))     
    
    return roads_gdf

# Road Tespiti ZIP kodu Geoframe den çekme yöntemiyle - Tek adres ile
def visualize_road_detection_from_zipCodeRoads(address, max_angle_deg, buffer_ft, MIN_FRONTAGE_FT):   

    lat, lon, parcel_polygon, coords, edges_real, edges_whole = real_edges(address, max_angle_deg)

    # -----------------------------
    # 1️⃣ CRS
    # -----------------------------
    # CRS_LATLON = "EPSG:4326"
    # CRS_FEET   = "EPSG:2276"   # Dallas    

    # -----------------------------
    # 2️⃣ PARSEL POLYGON
    # -----------------------------
    poly = Polygon(coords)
    gdf_poly = gpd.GeoDataFrame(geometry=[poly], crs=CRS_LATLON)
    # CRS_PROJECTED = gdf_poly.estimate_utm_crs()
    # print("Önerilen UTM CRS:", CRS_PROJECTED)
    # print("Manuel CRS_FEET:", CRS_FEET)
    # CRS_FEET = CRS_PROJECTED.to_string()  # Otomatik önerilen CRS'yi kullan
    # print("Kullanılan CRS_FEET:", CRS_FEET)
    gdf_poly_feet = gdf_poly.to_crs(CRS_FEET)

    parcel_proj = gdf_poly_feet.geometry.iloc[0]

    # -----------------------------
    # 3️⃣ BUFFER (ROAD SEARCH AREA)
    # -----------------------------
    parcel_buffer = parcel_proj.buffer(buffer_ft)
    buffer_latlon = gpd.GeoSeries([parcel_buffer], crs=CRS_FEET).to_crs(CRS_LATLON)


    # -----------------------------
    # 1️⃣ Daha önce çektiğin yolları oku yoksa çek (GPKG)
    # -----------------------------
    roads_gdf = get_roads_for_zip(address)    

    # CRS feet’e dönüştür
    roads_gdf = roads_gdf.to_crs(CRS_FEET)
    roads_gdf = roads_gdf[roads_gdf.intersects(parcel_buffer)].copy()   

    # opsiyonel: osmid normalize (artık gerekli değil)
    # if "osmid" not in roads_gdf.columns:
    #     roads_gdf["osmid"] = range(len(roads_gdf))

    # -----------------------------
    # 5️⃣ PARCEL EDGES (CRITICAL 🔥)
    # -----------------------------
    parcel_edges = []
    for e in edges_real:
        p1, p2, _ = e
        line = LineString([p1, p2])
        parcel_edges.append(line)

    edges_gdf_parcel = gpd.GeoDataFrame(geometry=parcel_edges, crs=CRS_LATLON).to_crs(CRS_FEET)

    # -----------------------------
    # 6️⃣ LENGTH FUNCTION
    # -----------------------------
    def get_length(geom):
        if geom is None or geom.is_empty:
            return 0.0
        if geom.geom_type == "LineString":
            return float(geom.length)
        if geom.geom_type == "MultiLineString":
            return float(sum(g.length for g in geom.geoms))
        if geom.geom_type == "GeometryCollection":
            return float(sum(
                g.length for g in geom.geoms
                if g.geom_type in ["LineString", "MultiLineString"]
            ))
        return 0.0

    # -----------------------------
    # 7️⃣ FRONTAGE DETECTION (NEW 🔥)
    # -----------------------------
    frontage_results = []

    for idx, edge in enumerate(edges_gdf_parcel.geometry):

        edge_buffer = edge.buffer(buffer_ft)

        for _, road_row in roads_gdf.iterrows():
            road = road_row.geometry

            if not edge_buffer.intersects(road):
                continue

            inter = edge_buffer.intersection(road)
            inter_len = get_length(inter)

            if inter_len > MIN_FRONTAGE_FT:
                frontage_results.append({
                    "edge_id": idx,
                    "edge_geom": edge,
                    "road_geom": road,
                    "intersection": inter,
                    "length_ft": inter_len,
                    "road_name": road_row.get("name") or road_row.get("highway")
                })

    frontage_gdf = gpd.GeoDataFrame(frontage_results, geometry="intersection", crs=CRS_FEET)

    # duplicate edge temizle (en uzun eşleşmeyi al)
    if not frontage_gdf.empty:
        frontage_gdf = frontage_gdf.sort_values("length_ft", ascending=False)
        frontage_gdf = frontage_gdf.drop_duplicates(subset="edge_id")

    print("Frontage bulunan edge sayısı:", len(frontage_gdf))

    # -----------------------------
    # 8️⃣ MAP
    # -----------------------------
    poly_latlon = gdf_poly.to_crs(CRS_LATLON)
    roads_latlon = roads_gdf.to_crs(CRS_LATLON)
    edges_latlon = edges_gdf_parcel.to_crs(CRS_LATLON)
    frontage_latlon = frontage_gdf.to_crs(CRS_LATLON) if not frontage_gdf.empty else None

    center = poly_latlon.geometry.iloc[0].centroid
    m = folium.Map(location=[center.y, center.x], zoom_start=20)

    # parcel
    folium.GeoJson(poly_latlon.geometry.iloc[0]).add_to(m)

    # all roads (blue)
    for r in roads_latlon.geometry:
        folium.GeoJson(r, style_function=lambda x: {"color": "blue", "weight": 2}).add_to(m)

    # parcel edges (green)
    for geom in edges_latlon.geometry:
        folium.GeoJson(geom, style_function=lambda x: {"color": "green", "weight": 3}).add_to(m)

    # frontage (dark red)
    if frontage_latlon is not None:
        for geom in frontage_latlon.geometry:
            folium.GeoJson(geom, style_function=lambda x: {"color": "darkred", "weight": 6}).add_to(m)

    # buffer
    buffer_latlon_geom = gpd.GeoSeries([parcel_buffer], crs=CRS_FEET).to_crs(CRS_LATLON).iloc[0]
    folium.GeoJson(
        buffer_latlon_geom,
        style_function=lambda x: {
            "color": "orange",
            "weight": 2,
            "fillOpacity": 0.1
        }
    ).add_to(m)

    # center
    folium.CircleMarker(
        location=[center.y, center.x],
        radius=6,
        color="black",
        fill=True,
        fill_opacity=1
    ).add_to(m)

    file_name = "road_detection_EDGE_BASED.html"
    m.save(file_name)
    print("✅ Harita oluşturuldu:", file_name)

    webbrowser.open(file_name)

# Road Tespiti + Parsel Edges (ZIP kodu Geoframe den çekme yöntemiyle)
def road_and_edge_detection_scoring(address, max_angle_deg, poly_buffer_ft, EDGE_BUFFER, MIN_FRONTAGE_FT):

    # -----------------------------
    # 🔧 HELPER FUNCTIONS
    # -----------------------------
    def create_directional_buffer(edge, parcel_polygon, buffer_dist):
        midpoint = edge.interpolate(0.5, normalized=True)
        centroid = parcel_polygon.centroid

        dx = midpoint.x - centroid.x
        dy = midpoint.y - centroid.y

        length = math.hypot(dx, dy)
        if length == 0:
            return edge.buffer(buffer_dist)

        dx /= length
        dy /= length

        dx *= buffer_dist
        dy *= buffer_dist

        buff = edge.buffer(buffer_dist)
        return translate(buff, xoff=dx, yoff=dy)

    def calculate_angle(line1, line2):
        x1, y1 = line1.coords[0]
        x2, y2 = line1.coords[-1]

        x3, y3 = line2.coords[0]
        x4, y4 = line2.coords[-1]

        a1 = math.atan2(y2 - y1, x2 - x1)
        a2 = math.atan2(y4 - y3, x4 - x3)

        ang = abs(math.degrees(a1 - a2))
        return min(ang, 180 - ang)

    def get_length(geom):
        if geom is None or geom.is_empty:
            return 0.0
        if geom.geom_type == "LineString":
            return geom.length
        if geom.geom_type == "MultiLineString":
            return sum(g.length for g in geom.geoms)
        return 0.0
    
    # -----------------------------
    # 📍 PARSEL
    # -----------------------------
    def get_parcel_data(address, max_angle_deg):
        lat, lon, acct, area, perimeter, parcel_polygon, coords, edges_real, edges_whole, segment_to_edge, long_zoning, zoning, pd_info = real_edges(address, max_angle_deg)

        if parcel_polygon is None:  # parcel_polygon
            print("🚫 get_parcel_data: parcel yok → pipeline skip")
            return None

        # CRS_LATLON = "EPSG:4326"
        # CRS_FEET = "EPSG:2276"

        poly = Polygon(coords)

        gdf_poly = gpd.GeoDataFrame(geometry=[poly], crs=CRS_LATLON).to_crs(CRS_FEET)
        parcel_proj = gdf_poly.geometry.iloc[0]

        return {
            "lat": lat,
            "lon": lon,
            "acct": acct,    
            "area": area,    
            "perimeter": perimeter,
            "coords": coords,
            "edges_real": edges_real,
            "edges_whole": edges_whole,
            "segment_to_edge": segment_to_edge,
            "long_zoning": long_zoning,
            "zoning": zoning,
            "pd_info": pd_info,                     
            "CRS_LATLON": CRS_LATLON,
            "CRS_FEET": CRS_FEET,
            "gdf_poly": gdf_poly,
            "parcel_proj": parcel_proj,
        }

    # -----------------------------
    # 🛣️ ROADS
    # -----------------------------   
    def get_roads_data(address, parcel_data, poly_buffer_ft):

        parcel_proj = parcel_data["parcel_proj"]
        CRS_FEET = parcel_data["CRS_FEET"]

        # -----------------------------
        # BUFFER
        # -----------------------------
        parcel_buffer = parcel_proj.buffer(poly_buffer_ft)

        # -----------------------------
        # ROADS (RAW)
        # -----------------------------
        roads_gdf = get_roads_for_zip(address).to_crs(CRS_FEET)       

        # sadece buffer ile kesişenleri al
        roads_gdf = roads_gdf[roads_gdf.intersects(parcel_buffer)]
        print("Before clip(roads_gdf):", len(roads_gdf))

        roads_raw_gdf = roads_gdf.copy()        

        # -----------------------------
        # 🛣️ CLIP (EN KRİTİK ADIM)
        # -----------------------------
        roads_clipped_gdf = gpd.clip(
            roads_gdf,
            gpd.GeoSeries([parcel_buffer], crs=CRS_FEET)
        )
        
        print("After clip(roads_clipped_gdf):", len(roads_clipped_gdf))       

        # -----------------------------
        # 🛣️ DISSOLVE (CLIP'TEN SONRA!)
        # -----------------------------
        roads_clipped_gdf["road_id"] = roads_clipped_gdf["name"].fillna(
            roads_clipped_gdf["highway"]
        )

        roads_dissolved_gdf = roads_clipped_gdf.dissolve(by="road_id").reset_index()

        # debug
        multi_count = sum(
            1 for g in roads_dissolved_gdf.geometry
            if g.geom_type == "MultiLineString"
        )
        print(f"MultiLineString road sayısı: {multi_count}")   


        # -----------------------------
        # RETURN
        # -----------------------------
        return {            
            "roads_raw": roads_raw_gdf,       # 🔵 raw
            "roads_clipped": roads_clipped_gdf,   # 🔴 clipped
            "roads_dissolved": roads_dissolved_gdf,
            "parcel_buffer": parcel_buffer
        }   

    # -----------------------------
    # 🔲 EDGES
    # -----------------------------   
    def get_edges_data(parcel_data):

        CRS_LATLON = parcel_data["CRS_LATLON"]
        CRS_FEET = parcel_data["CRS_FEET"]

        segment_to_edge = parcel_data.get("segment_to_edge", None)

        parcel_edges = []
        edge_ids = []
        edge_lengths = []
        source_map = []       

        for e in parcel_data["edges_real"]:
            p1, p2, length, source_ids, edge_id = e

            parcel_edges.append(LineString([p1, p2]))
            edge_ids.append(edge_id)
            edge_lengths.append(round(length, 1))

            # 🔥 SOURCE OF TRUTH CHECK
            if segment_to_edge is not None:
                # segment_to_edge doğruysa bunu kullan
                validated_sources = [
                    seg for seg in source_ids
                    if segment_to_edge.get(seg) == edge_id
                ]
                source_map.append(validated_sources)
            else:
                # fallback (eski sistem)
                source_map.append(source_ids)
        print("source_map:", source_map)

        edges_gdf = gpd.GeoDataFrame(
            {   "edge_id": edge_ids,
                "geometry": parcel_edges,
                "length": edge_lengths,
                "source_edges": source_map
            }, crs=CRS_LATLON).to_crs(CRS_FEET)
        
        # -----------------------------
        # CLOCKWISE ORDER
        # -----------------------------
        # Parsel centroid'i
        parcel_centroid = edges_gdf.unary_union.centroid

        angles = []
        for _, row in edges_gdf.iterrows():
            geom = row.geometry
            midpoint = geom.interpolate(0.5, normalized=True)
            dx = midpoint.x - parcel_centroid.x
            dy = midpoint.y - parcel_centroid.y
            angle = math.degrees(math.atan2(dy, dx))
            if angle < 0:
                angle += 360
            angles.append(angle)

        edges_gdf["angle"] = angles

        # Saat yönünde sıralama (clockwise)
        edges_gdf = edges_gdf.sort_values(by="angle", ascending=False).reset_index(drop=True)

        # Order kolonunu ekle
        edges_gdf["order"] = np.arange(len(edges_gdf))

        # -----------------------------
        # SOURCE GEOMETRY EKLE
        # -----------------------------
        edges_whole = parcel_data["edges_whole"]
        edges_whole_gdf = gpd.GeoDataFrame(
            [{"geometry": LineString([p1, p2])}
                for p1, p2, length in edges_whole], crs=CRS_LATLON).to_crs(CRS_FEET)
        edges_whole_dict = edges_whole_gdf.to_dict("records")
        def get_source_geoms(source_ids):
            return [edges_whole_dict[i] for i in source_ids if i < len(edges_whole_dict)] 
        edges_gdf["geometry_whole_edges"] = edges_gdf["source_edges"].apply(get_source_geoms)  
        # display("edges_gdf:::", edges_gdf)
        # display("geometry:::", edges_gdf.geometry[0])
        # display("geometry_whole_edges:::", edges_gdf.geometry_whole_edges[0])

        return {
            "edges_gdf": edges_gdf
        }      

    # -----------------------------
    # 🔥 STEP 1: EDGE → BEST MATCH
    # -----------------------------  
    def match_edges_to_roads(edges_data, roads_data, parcel_data, EDGE_BUFFER, MIN_FRONTAGE_FT):      

        edges_gdf = edges_data["edges_gdf"]
        roads = roads_data["roads_dissolved"]
        parcel_proj = parcel_data["parcel_proj"]

        # base_max_dist = max(30, parcel_proj.area ** 0.5 * 0.5)
        base_max_dist = max(50, math.sqrt(parcel_proj.area) * 0.7)
        # base_max_dist = max(40, parcel_proj.area ** 0.6)
        print(f"BASE MAX_DIST: {base_max_dist:.2f} ft")

        # ----------------------------------
        # HELPER FUNCTIONS
        # ----------------------------------
        def create_result(edge_id, edge, score, angle, dist, inter_len):
            return {
                "edge_id": edge_id,
                "edge_geom": edge,      
                "score": round(score, 2),
                "angle": round(angle, 2) if angle is not None else None,
                "dist": round(dist, 2),
                "length": round(inter_len, 2)
            }

        def run_frontage_pass(edges_gdf, roads, parcel_proj,
                            EDGE_BUFFER, MIN_FRONTAGE_FT,
                            MAX_DIST, angle_limit, min_score,
                            allow_proximity):
            results = []
            edge_buffers = {}
            nearest_points_list = []            

            for _, edge_row in edges_gdf.iterrows():
                edge = edge_row.geometry
                edge_id = edge_row.edge_id          

                edge_buffer = create_directional_buffer(edge, parcel_proj, EDGE_BUFFER)
                edge_buffers[edge_id] = edge_buffer

                for _, row in roads.iterrows():
                    geom = row.geometry
                    road_list = geom.geoms if geom.geom_type == "MultiLineString" else [geom]

                    for road in road_list:
                        dist = edge.distance(road)
                        if dist > MAX_DIST:
                            continue

                        angle = abs(calculate_angle(edge, road))

                        if angle > angle_limit:
                            continue

                        # 🔹 nearest points debug
                        p1, p2 = nearest_points(edge, road)
                        nearest_points_list.append((p1, p2))

                        inter = edge_buffer.intersection(road)
                        inter_len = get_length(inter)

                        # ❌ Ignore point intersections
                        if inter.geom_type == "Point":
                            continue

                        # ❌ Coverage filter
                        edge_len = edge.length
                        coverage_ratio = inter_len / edge_len if edge_len > 0 else 0
                        if coverage_ratio < 0.2:
                            continue

                        length_score = min(inter_len / 50, 1)
                        score = 0.4 * (1 / (dist + 1)) + 0.3 * max(0, (30 - angle)/30) + 0.3 * length_score

                        road_name = row.get('name', row.get('highway', 'Unknown'))
                        print(f"Edge:{edge_id} | Road:'{road_name}' | dist:{dist:.2f} | angle:{angle:.2f} | inter_len:{inter_len:.2f} | score:{score:.2f}")


                        # ✅ Strict frontage criteria
                        if inter_len > MIN_FRONTAGE_FT:
                            results.append(create_result(edge_id, edge, score, angle, dist, inter_len))
                            continue

                        # ✅ Score-based relaxed
                        if score > min_score and dist < 25:
                            results.append(create_result(edge_id, edge, score, angle, dist, inter_len))
                            continue

                        # ✅ Proximity fallback (RELAXED mode)
                        if allow_proximity and dist < 15:
                            results.append(create_result(edge_id, edge, score, angle, dist, inter_len))
                            continue
                        
            if not results:
                return None, None

            debug_data = {
                "edge_buffers": edge_buffers,
                "nearest_points": nearest_points_list
            }
            return results, debug_data

        # ----------------------------------
        # FALLBACK (en yakın road)
        # ----------------------------------
        def fallback_nearest_road(edges_gdf, roads):
            results = []
            for _, edge_row in edges_gdf.iterrows(): 
                edge = edge_row.geometry
                edge_id = edge_row.edge_id              
                best_dist = float("inf")
                best_road = None

                for _, row in roads.iterrows():
                    geom = row.geometry
                    road_list = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
                    for road in road_list:
                        dist = edge.distance(road)
                        if dist < best_dist:
                            best_dist = dist
                            best_road = road

                if best_road is not None:
                    results.append({
                        "edge_id": edge_id,
                        "edge_geom": edge,                   
                        "score": round(1/(best_dist+1),2),
                        "angle": None,
                        "dist": round(best_dist,2),
                        "length": 0
                    })
            return results if results else None

        # ----------------------------------
        # DIRECTION FILTERING + GROUPING + BEST GROUP
        # ----------------------------------
        def find_dominant_direction(results):
            angles = [abs(r["angle"]) for r in results if r["angle"] is not None]
            if not angles:
                return None
            angles.sort()
            return angles[len(angles)//2]  # median

        def filter_by_dominant_direction(results, tolerance=25):
            dominant = find_dominant_direction(results)
            if dominant is None:
                return results
            filtered = [r for r in results if r["angle"] is not None and abs(abs(r["angle"]) - dominant) <= tolerance]
            return filtered

        def group_connected_edges(results):
            groups = []
            used = set()
            for i, r1 in enumerate(results):
                if i in used:
                    continue
                group = [r1]
                used.add(i)
                for j, r2 in enumerate(results):
                    if j in used:
                        continue
                    if r1["edge_id"] == r2["edge_id"]:
                        continue
                    if abs(r1["angle"] - r2["angle"]) < 20:
                        group.append(r2)
                        used.add(j)
                groups.append(group)
            return groups

        def select_best_group(groups):
            best_group = None
            best_score = -1
            for g in groups:
                total_score = sum(x["score"] for x in g)
                total_length = sum(x["length"] for x in g)
                score = total_score + total_length*0.05
                if score > best_score:
                    best_score = score
                    best_group = g
            return best_group

        # ----------------------------------
        # 🟢 STRICT MODE
        # ----------------------------------
        results, debug = run_frontage_pass(edges_gdf, roads, parcel_proj,
                                        EDGE_BUFFER, MIN_FRONTAGE_FT,
                                        MAX_DIST=base_max_dist,
                                        angle_limit=40,
                                        min_score=0.2,
                                        allow_proximity=False)
        if results:
            results = filter_by_dominant_direction(results)
            groups = group_connected_edges(results)
            print(f"DEBUG | STRICT MODE | Groups: {len(groups)}")
            for i, g in enumerate(groups):
                print(f"  Group {i+1}: {[r['edge_id'] for r in g]}")
            best_group = select_best_group(groups)
            print(f"DEBUG | STRICT MODE | Best Group: {[r['edge_id'] for r in best_group]}")
            if best_group:
                return best_group, debug

        # ----------------------------------
        # 🟡 RELAXED MODE
        # ----------------------------------
        results, debug = run_frontage_pass(edges_gdf, roads, parcel_proj,
                                        EDGE_BUFFER*1.3, MIN_FRONTAGE_FT*0.7,
                                        MAX_DIST=base_max_dist+25,
                                        angle_limit=75,
                                        min_score=0.1,
                                        allow_proximity=True)
        if results:
            results = filter_by_dominant_direction(results)
            groups = group_connected_edges(results)
            print(f"DEBUG | RELAXED MODE | Groups: {len(groups)}")
            for i, g in enumerate(groups):
                print(f"  Group {i+1}: {[r['edge_id'] for r in g]}")
            best_group = select_best_group(groups)
            print(f"DEBUG | RELAXED MODE | Best Group: {[r['edge_id'] for r in best_group]}")
            if best_group:
                return best_group, debug

        # ----------------------------------
        # 🔴 FALLBACK MODE
        # ----------------------------------
        best_group = fallback_nearest_road(edges_gdf, roads)
        if best_group:
            debug = {"edge_buffers": {}, "nearest_points": []}
            return best_group, debug

        return [], {}
    
    # -----------------------------
    # 🔥 STEP 2: FILTER
    # -----------------------------
    def filter_results(results):
        filtered = [r for r in results if r["score"] > 0.25]
        print("results after filtering:", len(results))
        # print("filtered:", filtered)
        return filtered  
    
    # Aynı edge birden fazla kez gelecek bunu normalize edelim 
    def collapse_by_edge(results):
        best_per_edge = {}
        for r in results:
            eid = r["edge_id"]
            if eid not in best_per_edge or r["score"] > best_per_edge[eid]["score"]:
                best_per_edge[eid] = r
        best_per_edge = list(best_per_edge.values())
        print("results after collapse filtering:", len(best_per_edge))
        return best_per_edge
     
    # -----------------------------
    # 🔴 FRONTAGE GDF (EDGE BAZLI)
    # ----------------------------- 
    def build_frontage(roads_data, debug_data, filtered_results):
        frontage_list = []
        roads = roads_data["roads_clipped"]
        edge_buffers = debug_data["edge_buffers"]

        seen_edges = set()

        def extract_lines(geom):
            lines = []

            if geom is None or geom.is_empty:
                return lines

            if geom.geom_type == "LineString":
                lines.append(geom)

            elif geom.geom_type == "MultiLineString":
                lines.extend(list(geom.geoms))

            elif geom.geom_type == "GeometryCollection":
                for g in geom.geoms:
                    lines.extend(extract_lines(g))

            return lines

        for r in filtered_results:
            edge_id = r["edge_id"]

            if edge_id in seen_edges:
                continue

            if edge_id not in edge_buffers:
                continue

            edge_buffer = edge_buffers[edge_id]
            geoms_to_merge = []

            for _, row in roads.iterrows():
                geom = row.geometry
                road_list = geom.geoms if geom.geom_type == "MultiLineString" else [geom]

                for road in road_list:
                    inter = edge_buffer.intersection(road)

                    if inter.is_empty:
                        continue

                    # sadece line geometrileri al
                    geoms_to_merge.extend(extract_lines(inter))

            if geoms_to_merge:
                try:
                    merged_geom = linemerge(geoms_to_merge)
                except Exception:
                    merged_geom = unary_union(geoms_to_merge)

                frontage_list.append({
                    "edge_id": edge_id,
                    "geometry": merged_geom
                })

                seen_edges.add(edge_id)

        if frontage_list:
            frontage_gdf = gpd.GeoDataFrame(frontage_list, crs=roads.crs)
        else:
            frontage_gdf = gpd.GeoDataFrame(
                columns=["edge_id", "geometry"],
                crs=roads.crs
            )

        return frontage_gdf

    # -----------------------------
    # 🔴 SIDE / REAR TESPİTİ
    # -----------------------------
    def classify_edges_single_frontage(edges_gdf, frontage_gdf):

        # -----------------------------
        # yardımcı fonksiyonlar
        # -----------------------------
        def get_angle(line):
            x1, y1 = line.coords[0]
            x2, y2 = line.coords[-1]
            return math.degrees(math.atan2(y2 - y1, x2 - x1))

        def angle_diff(a, b):
            diff = abs(a - b) % 180
            return min(diff, 180 - diff)

        # -----------------------------
        # FRONT EDGE
        # -----------------------------
        if frontage_gdf.empty:
            raise ValueError("Frontage bulunamadı")

        if len(frontage_gdf) > 1:
            raise ValueError("Bu fonksiyon sadece tek frontage için kullanılmalı")

        front_edge_id = frontage_gdf.iloc[0]["edge_id"]

        front_row = edges_gdf[edges_gdf["edge_id"] == front_edge_id].iloc[0]
        front_geom = front_row.geometry
        front_angle = get_angle(front_geom)
        front_center = front_geom.centroid

        parcel_centroid = edges_gdf.unary_union.centroid

        # -----------------------------
        # 🔥 MULTI-REAR DETECTION (L-shape SAFE)
        # -----------------------------
        other_edges = edges_gdf[edges_gdf["edge_id"] != front_edge_id]

        rear_candidates = []

        for _, row in other_edges.iterrows():
            geom = row.geometry
            edge_id = row.edge_id

            ang = get_angle(geom)
            diff = angle_diff(front_angle, ang)

            # ✅ paralel kontrolü (çok kritik)
            if not (diff < 30 or diff > 150):
                continue

            # ✅ mesafe
            dist = geom.distance(front_geom)

            # ✅ yön kontrolü (front'un arkasında mı?)
            edge_center = geom.centroid

            front_vec_x = front_center.x - parcel_centroid.x
            front_vec_y = front_center.y - parcel_centroid.y

            edge_vec_x = edge_center.x - parcel_centroid.x
            edge_vec_y = edge_center.y - parcel_centroid.y

            dot = front_vec_x * edge_vec_x + front_vec_y * edge_vec_y

            # 👉 sadece arka tarafta olanları al
            if dot > 0:
                continue

            rear_candidates.append((edge_id, dist))

        # -----------------------------
        # 🎯 REAR SEÇİMİ (multi allowed)
        # -----------------------------
        rear_edge_ids = []

        if rear_candidates:
            # en uzak edge'i referans al
            rear_candidates.sort(key=lambda x: x[1], reverse=True)
            best_dist = rear_candidates[0][1]

            # 🔥 threshold ile birden fazla rear seç
            rear_edge_ids = [
                eid for eid, dist in rear_candidates
                if dist > best_dist * 0.6   # ayarlanabilir (0.5–0.8 arası oynayabilirsin)
            ]

        # -----------------------------
        # SIDE = kalanlar
        # -----------------------------
        side_edge_ids = [
            eid for eid in edges_gdf["edge_id"]
            if eid not in [front_edge_id] + rear_edge_ids
        ]

        # -----------------------------
        # sonucu yaz
        # -----------------------------
        edges_gdf["edge_type"] = "side"

        edges_gdf.loc[
            edges_gdf["edge_id"] == front_edge_id, "edge_type"
        ] = "front"

        if rear_edge_ids:
            edges_gdf.loc[
                edges_gdf["edge_id"].isin(rear_edge_ids),
                "edge_type"
            ] = "rear"

        # -----------------------------
        # DEBUG
        # -----------------------------
        print("\n--- EDGE CLASSIFICATION (MULTI-REAR) ---")
        print("Front edge:", front_edge_id)
        print("Rear edges:", rear_edge_ids)
        print("Side edges:", side_edge_ids)

        if "order" in edges_gdf.columns:
            print("\nOrder info:")
            print(edges_gdf[["edge_id", "order", "edge_type", "length"]])
        else:
            print("\nNo ordering used")
            print(edges_gdf[["edge_id", "edge_type", "length"]])

        return edges_gdf

    def detect_rear_edges_corner_for_edges_double_frontage(
                                            edges_gdf, frontage_gdf,
                                            angle_threshold=30,
                                            min_length_ratio=0.2):   

        def get_angle(line):
            x1, y1 = line.coords[0]
            x2, y2 = line.coords[-1]
            return math.degrees(math.atan2(y2 - y1, x2 - x1))

        def angle_diff(a, b):
            diff = abs(a - b) % 180
            return min(diff, 180 - diff)

        if len(frontage_gdf) != 2:
            raise ValueError("Bu fonksiyon sadece 2 frontage için")

        front_ids = list(frontage_gdf["edge_id"])

        front_rows = [
            edges_gdf[edges_gdf["edge_id"] == fid].iloc[0]
            for fid in front_ids
        ]

        front_angles = [get_angle(r.geometry) for r in front_rows]
        front_centers = [r.geometry.centroid for r in front_rows]

        parcel_centroid = edges_gdf.unary_union.centroid

        # Ortalama uzunluk (küçük edge'leri elemek için)
        avg_length = edges_gdf["length"].mean()

        rear_candidates = []

        for _, row in edges_gdf.iterrows():
            eid = row.edge_id

            if eid in front_ids:
                continue

            geom = row.geometry
            ang = get_angle(geom)
            length = row.length

            # -----------------------------
            # 1. LENGTH FILTER
            # -----------------------------
            if length < avg_length * min_length_ratio:
                continue

            # -----------------------------
            # 2. PARALLEL TO ANY FRONT
            # -----------------------------
            is_parallel = any(
                angle_diff(ang, f_ang) < angle_threshold or
                angle_diff(ang, f_ang) > 180 - angle_threshold
                for f_ang in front_angles
            )

            if not is_parallel:
                continue

            # -----------------------------
            # 3. YÖN KONTROLÜ (KRİTİK!)
            # -----------------------------
            edge_center = geom.centroid

            # her front için dot kontrolü
            is_behind = False

            for fc in front_centers:
                front_vec_x = fc.x - parcel_centroid.x
                front_vec_y = fc.y - parcel_centroid.y

                edge_vec_x = edge_center.x - parcel_centroid.x
                edge_vec_y = edge_center.y - parcel_centroid.y

                dot = front_vec_x * edge_vec_x + front_vec_y * edge_vec_y

                # herhangi bir front'un arkasındaysa yeterli
                if dot < 0:
                    is_behind = True
                    break

            if not is_behind:
                continue

            # -----------------------------
            # 4. DISTANCE SCORE
            # -----------------------------
            dist_score = max(
                geom.distance(fc) for fc in front_centers
            )

            rear_candidates.append((eid, dist_score))

        # -----------------------------
        # 🎯 REAR SELECTION (MULTI)
        # -----------------------------
        if not rear_candidates:
            print("🚫 Rear YOK (true corner lot)")
            return []

        rear_candidates.sort(key=lambda x: x[1], reverse=True)
        best_score = rear_candidates[0][1]

        rear_ids = [
            eid for eid, score in rear_candidates
            if score > best_score * 0.6   # 🔥 ayarlanabilir
        ]

        print("✅ Rear VAR:", rear_ids)

        return rear_ids

    def determine_lot_type(edges_gdf, frontage_gdf, angle_group_tol=25, corner_angle_threshold=35):
        def get_edge_angle(line):
            x1, y1 = line.coords[0]
            x2, y2 = line.coords[-1]
            return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180

        def angle_diff(a, b):
            diff = abs(a - b) % 180
            return min(diff, 180 - diff)

        def side_value_with_global_normal(line, parcel_centroid, group_angle):
            # group_angle'a göre ortak normal üret
            theta = math.radians(group_angle)
            ux = math.cos(theta)
            uy = math.sin(theta)

            nx = -uy
            ny = ux

            mid = line.interpolate(0.5, normalized=True)

            vx = mid.x - parcel_centroid.x
            vy = mid.y - parcel_centroid.y

            return vx * nx + vy * ny

        if frontage_gdf is None or frontage_gdf.empty:
            return {
                "lotType": "unknown",
                "frontage_count": 0,
                "frontage_ids": [],
                "frontage_direction_count": 0,
                "frontage_direction_groups": [],
                "frontage_angle_diffs": []
            }

        frontage_ids = list(frontage_gdf["edge_id"].unique())

        frontage_rows = edges_gdf[
            edges_gdf["edge_id"].isin(frontage_ids)
        ].copy()

        parcel_centroid = edges_gdf.unary_union.centroid

        frontage_rows["frontage_angle"] = frontage_rows.geometry.apply(get_edge_angle)

        # -----------------------------
        # 1) SADECE AÇIYA GÖRE ANA GRUPLAR
        # -----------------------------
        angle_groups = []

        for _, row in frontage_rows.iterrows():
            eid = int(row["edge_id"])
            ang = row["frontage_angle"]
            length = row.get("length", row.geometry.length)

            placed = False

            for g in angle_groups:
                if angle_diff(ang, g["mean_angle"]) <= angle_group_tol:
                    g["rows"].append(row)
                    g["edge_ids"].append(eid)
                    g["angles"].append(ang)
                    g["lengths"].append(length)
                    g["mean_angle"] = sum(g["angles"]) / len(g["angles"])
                    placed = True
                    break

            if not placed:
                angle_groups.append({
                    "rows": [row],
                    "edge_ids": [eid],
                    "angles": [ang],
                    "lengths": [length],
                    "mean_angle": ang
                })

        # -----------------------------
        # 2) HER AÇI GRUBUNU GLOBAL NORMAL İLE SIDE'A BÖL
        # -----------------------------
        groups = []

        for ag in angle_groups:
            group_angle = ag["mean_angle"]

            side_pos = {
                "edge_ids": [],
                "angles": [],
                "lengths": [],
                "side_values": [],
                "mean_angle": group_angle,
                "side_sign": 1
            }

            side_neg = {
                "edge_ids": [],
                "angles": [],
                "lengths": [],
                "side_values": [],
                "mean_angle": group_angle,
                "side_sign": -1
            }

            for row in ag["rows"]:
                eid = int(row["edge_id"])
                ang = row["frontage_angle"]
                length = row.get("length", row.geometry.length)

                sv = side_value_with_global_normal(
                    row.geometry,
                    parcel_centroid,
                    group_angle
                )

                target = side_pos if sv >= 0 else side_neg

                target["edge_ids"].append(eid)
                target["angles"].append(ang)
                target["lengths"].append(length)
                target["side_values"].append(sv)

            if side_pos["edge_ids"]:
                groups.append(side_pos)

            if side_neg["edge_ids"]:
                groups.append(side_neg)

        groups = sorted(groups, key=lambda g: sum(g["lengths"]), reverse=True)

        frontage_direction_groups = [
            {
                "edge_ids": g["edge_ids"],
                "mean_angle": round(g["mean_angle"], 2),
                "side_sign": g["side_sign"],
                "avg_side_value": round(sum(g["side_values"]) / len(g["side_values"]), 2),
                "total_length": round(sum(g["lengths"]), 2)
            }
            for g in groups
        ]

        direction_count = len(groups)

        # -----------------------------
        # 3) LOT TYPE KARARI
        # -----------------------------
        if direction_count == 1:
            lot_type = "interior"
            angle_diffs = []

        elif direction_count == 2:
            g1, g2 = groups[0], groups[1]

            diff = angle_diff(g1["mean_angle"], g2["mean_angle"])
            opposite_side = g1["side_sign"] != g2["side_sign"]

            angle_diffs = [round(diff, 2)]

            if diff <= corner_angle_threshold and opposite_side:
                lot_type = "through"
            elif diff <= corner_angle_threshold and not opposite_side:
                lot_type = "interior"
            else:
                lot_type = "corner"

        else:
            main_groups = groups[:2]
            other_groups = groups[2:]

            main_length = sum(sum(g["lengths"]) for g in main_groups)
            other_length = sum(sum(g["lengths"]) for g in other_groups)
            total_length = main_length + other_length
            other_ratio = other_length / total_length if total_length > 0 else 0

            g1, g2 = main_groups
            diff = angle_diff(g1["mean_angle"], g2["mean_angle"])
            opposite_side = g1["side_sign"] != g2["side_sign"]

            angle_diffs = [round(diff, 2)]

            if other_ratio < 0.20:
                if diff <= corner_angle_threshold and opposite_side:
                    lot_type = "through"
                elif diff <= corner_angle_threshold and not opposite_side:
                    lot_type = "interior"
                else:
                    lot_type = "corner"
            else:
                lot_type = "multi_frontage"

        return {
            "lotType": lot_type,
            "frontage_count": len(frontage_ids),
            "frontage_ids": [int(x) for x in frontage_ids],
            "frontage_direction_count": direction_count,
            "frontage_direction_groups": frontage_direction_groups,
            "frontage_angle_diffs": angle_diffs
        }

    def classify_edges(edges_gdf, frontage_gdf):

        n_front = len(frontage_gdf)

        print(f"\n📊 Frontage count: {n_front}")

        # -----------------------------
        # SINGLE FRONTAGE → SENİN LOGIC (TOUCH YOK)
        # -----------------------------
        if n_front == 1:
            print("➡️ Using SINGLE FRONTAGE logic")
            return classify_edges_single_frontage(edges_gdf, frontage_gdf)

        # -----------------------------
        # DOUBLE FRONTAGE → CORNER LOT (AI LOGIC)
        # -----------------------------
        elif n_front == 2:
            print("➡️ Using DOUBLE FRONTAGE logic (SMART REAR)")

            # FRONT işaretle
            edges_gdf["edge_type"] = "side"
            front_ids = list(frontage_gdf["edge_id"])

            edges_gdf.loc[
                edges_gdf["edge_id"].isin(front_ids),
                "edge_type"
            ] = "front"

            # 🔥 SMART REAR DETECTION
            rear_ids = detect_rear_edges_corner_for_edges_double_frontage(edges_gdf, frontage_gdf)

            if rear_ids:
                edges_gdf.loc[
                    edges_gdf["edge_id"].isin(rear_ids),
                    "edge_type"
                ] = "rear"
            else:
                print("⚠️ Rear edge bulunamadı (true corner lot)")

            # DEBUG
            print("\n--- FINAL EDGE TYPES ---")           
            if "order" in edges_gdf.columns:
                print(edges_gdf[["edge_id", "order", "edge_type", "length"]])
            else:
                print(edges_gdf[["edge_id", "edge_type", "length"]])

            return edges_gdf

        # -----------------------------
        # 3+ FRONTAGE → RARE CASE
        # -----------------------------
        else:
            print("⚠️ 3+ frontage detected → fallback")

            edges_gdf["edge_type"] = "side"
            edges_gdf.loc[
                edges_gdf["edge_id"].isin(frontage_gdf["edge_id"]),
                "edge_type"
            ] = "front"

            return edges_gdf
       
    # TYPE + ANGLE BASED GROUPING
    def group_edges_by_type_and_direction(edges_gdf, angle_tol=20):

        def get_angle(line):
            x1, y1 = line.coords[0]
            x2, y2 = line.coords[-1]
            return math.degrees(math.atan2(y2 - y1, x2 - x1))

        grouped = {
            "front": [],
            "rear": [],
            "side": []
        }

        grouped_source = {
            "front": [],
            "rear": [],
            "side": []
        }

        for edge_type in ["front", "rear", "side"]:

            subset = edges_gdf[edges_gdf["edge_type"] == edge_type].reset_index(drop=True)

            groups = []
            groups_source = []

            used = set()

            for i, row1 in subset.iterrows():
                if i in used:
                    continue

                g1 = row1.geometry
                a1 = get_angle(g1)

                group_ids = [row1["edge_id"]]         

                used.add(i)

                for j, row2 in subset.iterrows():
                    if j in used:
                        continue

                    g2 = row2.geometry
                    a2 = get_angle(g2)

                    diff = abs(a1 - a2) % 180
                    diff = min(diff, 180 - diff)

                    if diff < angle_tol:
                        group_ids.append(row2["edge_id"])                
                        used.add(j)

                groups.append(group_ids)

            grouped[edge_type] = groups

        return grouped

    # -----------------------------
    # 🟦 PREPARE MAP DATA (LAT/LON)
    # -----------------------------   
    def prepare_map_layers(parcel_data, roads_data, edges_data, frontage_list, debug_data):

        CRS_LATLON = parcel_data["CRS_LATLON"]
        CRS_FEET = parcel_data["CRS_FEET"]

        # -----------------------------
        # 📦 PARCEL
        # -----------------------------
        gdf_poly = parcel_data["gdf_poly"]
        parcel_proj = parcel_data["parcel_proj"]

        poly_latlon = gdf_poly.to_crs(CRS_LATLON)

        # -----------------------------
        # 🛣️ ROADS
        # -----------------------------
        roads_raw = roads_data["roads_raw"]
        roads_clipped = roads_data["roads_clipped"]
        roads_dissolved = roads_data["roads_dissolved"]
        parcel_buffer = roads_data["parcel_buffer"]

        roads_raw_latlon = roads_raw.to_crs(CRS_LATLON)
        roads_clipped_latlon = roads_clipped.to_crs(CRS_LATLON)
        roads_dissolved_latlon = roads_dissolved.to_crs(CRS_LATLON)

        # buffer latlon
        buffer_latlon_geom = gpd.GeoSeries([parcel_buffer], crs=CRS_FEET).to_crs(CRS_LATLON).iloc[0]

        # -----------------------------
        # 🔲 EDGES
        # -----------------------------
        edges_gdf = edges_data["edges_gdf"]
        edges_latlon = edges_gdf.to_crs(CRS_LATLON).copy()

        # frontage flag yoksa default ekle
        if "is_frontage" not in edges_gdf.columns:
            edges_gdf["is_frontage"] = False

        # -----------------------------
        # 🔴 FRONTAGE
        # -----------------------------
        frontage_gdf = frontage_list  # build_frontage zaten GeoDataFrame döndürüyor
        if frontage_gdf is not None and not frontage_gdf.empty:
            frontage_latlon = frontage_gdf.to_crs(CRS_LATLON)
        else:
            frontage_latlon = None

        # -----------------------------
        # 🟧 EDGE BUFFERS
        # -----------------------------    
        edge_buffers_dict = debug_data["edge_buffers"]  # dict: edge_id -> buffer
        edge_buffers_gdf = gpd.GeoDataFrame(
            {
                "edge_id": list(edge_buffers_dict.keys()),      # edge_id kolonunu ekle
                "geometry": list(edge_buffers_dict.values())   # buffer geometrilerini al
            },
            crs=CRS_FEET
        )
        edge_buffers_latlon = edge_buffers_gdf.to_crs(CRS_LATLON)
       

        # print("\n🗺️ prepare_map_layers - edges_gdf:")
        # print(edges_gdf[["edge_id", "edge_type"]])

        # print("\n🗺️ prepare_map_layers - edges_latlon:")
        # print(edges_latlon[["edge_id", "edge_type"]])

        # -----------------------------
        # 🔵 NEAREST POINTS + LINES
        # -----------------------------
        nearest_points_list = debug_data["nearest_points"]

        nearest_points = []
        for p1, p2 in nearest_points_list:
            nearest_points.append(p1)
            nearest_points.append(p2)

        nearest_points_gdf = gpd.GeoDataFrame(geometry=nearest_points, crs=CRS_FEET)
        nearest_points_latlon = nearest_points_gdf.to_crs(CRS_LATLON)

        # connecting lines
        lines = [LineString([p1, p2]) for p1, p2 in nearest_points_list]
        lines_gdf = gpd.GeoDataFrame(geometry=lines, crs=CRS_FEET)
        lines_latlon = lines_gdf.to_crs(CRS_LATLON)

        # -----------------------------
        # 📍 CENTER
        # -----------------------------
        center = poly_latlon.geometry.iloc[0].centroid

        # -----------------------------
        # 📦 RETURN
        # -----------------------------
        return {
            "center": center,

            "poly": poly_latlon,
            "buffer": buffer_latlon_geom,

            "roads_raw": roads_raw_latlon,
            "roads_clipped": roads_clipped_latlon,
            "roads_dissolved": roads_dissolved_latlon,

            "edges": edges_latlon,
            "edges_gdf": edges_gdf,   # flag için lazım

            "frontage": frontage_latlon,

            "edge_buffers": edge_buffers_latlon,

            "nearest_points": nearest_points_latlon,
            "nearest_lines": lines_latlon
        }

    # -----------------------------
    # 🔲 MAP
    # -----------------------------  
    def create_map(map_data):        

        m = folium.Map(
            location=[map_data["center"].y, map_data["center"].x],
            zoom_start=20
        )

        # PARCEL
        folium.GeoJson(map_data["poly"].geometry.iloc[0],
                    style_function=lambda x: {"color": "black", "weight": 2}).add_to(m)

        # BUFFER
        folium.GeoJson(map_data["buffer"],
                    style_function=lambda x: {"color": "orange", "weight": 2, "fillOpacity": 0.05}).add_to(m)
        
        
        # 🔵 RAW ROADS (CLIP ÖNCESİ- tireli mavi)        
        for _, row in map_data["roads_raw"].iterrows():
            folium.GeoJson(
                row.geometry,
                style_function=lambda x: {
                    "color": "blue",
                    "weight": 2,
                    "dashArray": "5,5"
                }
            ).add_to(m)

     
        # 🔴 CLIPPED ROADS (BUFFER İÇİ- kırmızı)  
        for _, row in map_data["roads_clipped"].iterrows():
            folium.GeoJson(
                row.geometry,
                style_function=lambda x: {
                    "color": "red",
                    "weight": 4
                }
            ).add_to(m)
        

        # # EDGES        
        for idx, row in map_data["edges"].iterrows():  
            geom = row.geometry  
            edge_type = row.get("edge_type", "side")   # 🔥 direkt buradan

            if edge_type == "front":
                color = "red"
            elif edge_type == "rear":
                color = "blue"
            else:
                color = "green"

            folium.GeoJson(
                geom,
                style_function=lambda x, c=color: {"color": c, "weight": 4}
            ).add_to(m)
        
                    
       
        # EDGE LABELS          
        for idx, row in map_data["edges"].iterrows():            
            geom = row.geometry
            edge_id = row["edge_id"]   # 🔥 gerçek ID bu           

            try:
                midpoint = geom.interpolate(0.5, normalized=True)

                folium.Marker(
                    location=[midpoint.y, midpoint.x],
                    icon=folium.DivIcon(
                        html=f"""
                        <div style='
                            font-size:12px;
                            color:black;
                            font-weight:bold;
                            background:white;
                            border:1px solid black;
                            border-radius:3px;
                            padding:2px;
                        '>{edge_id}</div>   <!-- 🔥 idx değil -->
                        """
                    )
                ).add_to(m)

            except Exception as e:
                print(f"Edge {edge_id} label çizilemedi: {e}")

        # print("\n🎨 create_map - edges:")
        # print(map_data["edges"][["edge_id", "edge_type"]])

        
        # FRONTAGE     
        if map_data["frontage"] is not None and not map_data["frontage"].empty:
            for geom in map_data["frontage"].geometry:
                folium.GeoJson(
                    geom,
                    style_function=lambda x: {"color": "darkred", "weight": 6}
                ).add_to(m) 


        # EDGE BUFFERS (Sarı, yarı şeffaf) - sadece yola kesişen  
        if map_data["frontage"] is not None and not map_data["frontage"].empty:
            frontage_edge_ids = set(map_data["frontage"]["edge_id"])

            for _, row in map_data["edge_buffers"].iterrows():
                edge_id = row["edge_id"]
                if edge_id in frontage_edge_ids:  # artık doğru eşleşiyor
                    folium.GeoJson(
                        row.geometry,
                        style_function=lambda x: {"color": "yellow", "weight": 2, "fillOpacity": 0.2}
                    ).add_to(m)               
                     
        
        # NEAREST EDGE ↔ ROAD POINTS
        for pt in map_data["nearest_points"].geometry:
            folium.CircleMarker(location=[pt.y, pt.x], radius=4, color="black", fill=True, fill_opacity=1).add_to(m)
        for line in map_data["nearest_lines"].geometry:
            folium.GeoJson(line, style_function=lambda x: {"color": "black", "weight": 1, "dashArray": "5,5"}).add_to(m)

        # SAVE AND VİSUALIZE        
        file_name = "road_detection_EDGE_FRONTAGE_BASED.html"
        m.save(file_name)
        print("Harita oluşturuldu:", file_name)
        webbrowser.open(file_name)

        return m

    # -----------------------------
    # 🔲 PIPELINE
    # ----------------------------- 
    def pipeline():

        parcel_data = get_parcel_data(address, max_angle_deg)
        if parcel_data is None:
            print("🚫 Pipeline durduruldu (parcel yok)")
            return

        roads_data = get_roads_data(address, parcel_data, poly_buffer_ft)

        edges_data = get_edges_data(parcel_data)

        step1_results, debug_data = match_edges_to_roads(
            edges_data, roads_data, parcel_data, EDGE_BUFFER, MIN_FRONTAGE_FT
        )        

        # -----------------------------
        # 🔥 STEP 2: FILTER
        # -----------------------------
        filtered = filter_results(step1_results)  

        filtered = collapse_by_edge(filtered)  # aynı edge için en iyi sonucu bırak 

        # -----------------------------
        # 🎯 EDGE FLAG + SCORE
        # -----------------------------
        edges_gdf = edges_data["edges_gdf"]

        edges_gdf["is_frontage"] = False
        edges_gdf["score"] = 0.0

        frontage_ids = list(set(r["edge_id"] for r in filtered))  # 🔥 kritik
       
        edges_gdf.loc[edges_gdf["edge_id"].isin(frontage_ids), "is_frontage"] = True

        for r in filtered:            
            edges_gdf.loc[edges_gdf["edge_id"] == r["edge_id"], "score"] = r["score"]

        print("✅ FRONTAGE EDGE IDS:", frontage_ids)
        print(edges_gdf[["edge_id", "is_frontage", "score"]])

        
        # -----------------------------
        # 🔴 FRONTAGE BUILD (ALL)
        # -----------------------------        
        frontage_gdf = build_frontage(roads_data, debug_data, filtered)
        # -----------------------------
        # 🏷️ LOT TYPE DETECTION
        # -----------------------------
        lot_info = determine_lot_type(edges_gdf, frontage_gdf)
        lotType = lot_info["lotType"]

        print("\n🏷️ LOT TYPE INFO")
        print("lotType:", lot_info["lotType"])
        print("frontage_count:", lot_info["frontage_count"])
        print("frontage_ids:", lot_info["frontage_ids"])
        print("frontage_direction_count:", lot_info["frontage_direction_count"])
        print("frontage_direction_groups:", lot_info["frontage_direction_groups"])
        print("frontage_angle_diffs:", lot_info["frontage_angle_diffs"])

        # edge classification
        edges_gdf = classify_edges(edges_gdf, frontage_gdf)

        # lotType kolon olarak da edges_gdf içine yazılsın
        edges_gdf["lotType"] = lotType

        # 🔥 YENİ
        edge_groups = group_edges_by_type_and_direction(edges_gdf)
        print("\n🧩 EDGE GROUPS:")
        for k, v in edge_groups.items():
            print(f"{k.upper()}: {v}")         

        total_frontage = sum(
            edges_gdf[edges_gdf.edge_id.isin(group)]["length"].sum()
            for group in edge_groups["front"]
        )
        print(f"📏 Total Frontage Length: {total_frontage:.2f} ft") 

        frontage_lengths = [
            float(edges_gdf[edges_gdf.edge_id.isin(group)]["length"].sum())
            for group in edge_groups["front"]
        ]
        print("📏 Frontage groups lengths:", frontage_lengths)

        edges_data["edges_gdf"] = edges_gdf 
        # display("edges_gdf___:", edges_gdf)  

        # -----------------------------
        # 🎯 SOURCE EDGE GDF
        # -----------------------------
        # def build_source_edges_gdf(edges_gdf):
        #     rows = []
        #     for _, row in edges_gdf.iterrows():
        #         edge_id = row["edge_id"]
        #         edge_type = row["edge_type"]
        #         parent_geom = row["geometry"]
        #         source_ids = row["source_edges"]
        #         source_geoms = row["geometry_whole_edges"]
        #         for idx, item in zip(source_ids, source_geoms):
        #             rows.append({
        #                 # "edge_id": edge_id,
        #                 "edge_id": idx,                     # # source edges ids
        #                 "edge_type": edge_type,
        #                 "geometry": item["geometry"],              # source segments geometry
        #                 # "parent_edge_geom": parent_geom            # ana edge
        #             })
        #     source_edges_gdf = gpd.GeoDataFrame(rows, crs=edges_gdf.crs)[["edge_id", "edge_type", "geometry"]]    
        #     return source_edges_gdf
        # source_edges_gdf = build_source_edges_gdf(edges_gdf) 
        # # display("source_edges_gdf___:", source_edges_gdf)    
              
        
        # -----------------------------
        # 🗺️ MAP
        # -----------------------------
        map_data = prepare_map_layers(parcel_data, roads_data, edges_data, frontage_gdf, debug_data) 
        create_map(map_data)

        # -----------------------------
        # Gerekenleri Döndür
        # -----------------------------
        # edges_real = parcel_data["edges_real"]
        # edges_whole = parcel_data["edges_whole"]
        # long_zoning = parcel_data["long_zoning"]
        # zoning = parcel_data["zoning"]
        # pd_info = parcel_data["pd_info"]       

        # keys = ["acct", "area", "perimeter", "edges_real", "edges_whole", "long_zoning", "zoning", "pd_info"]
        keys = ["acct", "area", "perimeter", "long_zoning", "zoning", "pd_info"]
        result = {k: parcel_data[k] for k in keys}

        return {
            "address": address,   

            "parcel": result,
            "parcel_geom": parcel_data["parcel_proj"],   # 🔥 footprint için şart
            "edges_gdf": edges_gdf,                      # 🔥 edge_type içeriyor
            # "source_edges_gdf": source_edges_gdf,        # 🔥 source_edges_gdf içeriyor
            "edge_groups": edge_groups,                  # 🔥 front/side/rear grouping  

            "lotType": lotType,
            "lot_info": lot_info,  

            "frontage_ids": frontage_ids,
            "total_frontage": total_frontage,
            "frontage_lengths": frontage_lengths,
            "map_data": map_data
        }
    
    return pipeline()

# ----- Helper Functions
def run_road_and_edge_detection_all(
        addresses,
        max_angle_deg=170,
        poly_buffer_ft=80,
        EDGE_BUFFER=30,
        MIN_FRONTAGE_FT=15
    ):
        results = []

        for address in addresses:
            try:
                result = road_and_edge_detection_scoring(
                    address,
                    max_angle_deg=max_angle_deg,
                    poly_buffer_ft=poly_buffer_ft,
                    EDGE_BUFFER=EDGE_BUFFER,
                    MIN_FRONTAGE_FT=MIN_FRONTAGE_FT
                )

                if result is None:
                    result = {
                        "address": address,
                        "parcel": {},
                        "parcel_geom": None,
                        "edges_gdf": None,
                        "lotType": None,
                        "lot_info": None,
                        "map_data": {},
                        "error": "road_and_edge_detection_scoring returned None"
                    }
                else:
                    result["address"] = address
                    result.setdefault("error", None)

                results.append(result)

            except Exception as e:
                print(f"❌ Detection hata: {address}")
                print(e)

                results.append({
                    "address": address,
                    "parcel": {},
                    "parcel_geom": None,
                    "edges_gdf": None,
                    "lotType": None,
                    "lot_info": None,
                    "map_data": {},
                    "error": str(e)
                })

        return results
    
def run_road_and_edge_detection_all2(
    addresses,
    max_angle_deg=170,
    poly_buffer_ft=80,
    EDGE_BUFFER=30,
    MIN_FRONTAGE_FT=15
):
    results = []

    for address in addresses:
        try:
            result = road_and_edge_detection_scoring(
                address,
                max_angle_deg=max_angle_deg,
                poly_buffer_ft=poly_buffer_ft,
                EDGE_BUFFER=EDGE_BUFFER,
                MIN_FRONTAGE_FT=MIN_FRONTAGE_FT
            )

            if result is None:
                result = {
                    "address": address,
                    "parcel": {},
                    "parcel_geom": None,
                    "edges_gdf": None,
                    "lotType": None,
                    "lot_info": None,
                    "edge_groups": {"front": [], "rear": [], "side": []},
                    "frontage_ids": [],
                    "total_frontage": None,
                    "frontage_lengths": [],
                    "map_data": {},
                    "error": "road_and_edge_detection_scoring returned None"
                }
            else:
                result["address"] = address
                result.setdefault("parcel", {})
                result.setdefault("parcel_geom", None)
                result.setdefault("edges_gdf", None)
                result.setdefault("lotType", None)
                result.setdefault("lot_info", None)
                result.setdefault("edge_groups", {"front": [], "rear": [], "side": []})
                result.setdefault("frontage_ids", [])
                result.setdefault("total_frontage", None)
                result.setdefault("frontage_lengths", [])
                result.setdefault("map_data", {})
                result.setdefault("error", None)

            results.append(result)

        except Exception as e:
            error_msg = repr(e)
            traceback_msg = traceback.format_exc()

            print(f"❌ Detection hata: {address}")
            print("error:", error_msg)
            print(traceback_msg)

            results.append({
                "address": address,
                "parcel": {},
                "parcel_geom": None,
                "edges_gdf": None,
                "lotType": None,
                "lot_info": None,
                "edge_groups": {"front": [], "rear": [], "side": []},
                "frontage_ids": [],
                "total_frontage": None,
                "frontage_lengths": [],
                "map_data": {},
                "error": error_msg,
                "traceback": traceback_msg
            })

    return results

def make_results_by_address(results):
    return {
        r["address"]: r
        for r in results
        if r is not None and r.get("address") is not None
    }

def make_empty_road_row(address, error=None):
    return {
        "address": address,
        "acct": None,
        "area": None,
        "perimeter": None,
        "long_zoning": None,
        "zoning": None,
        "pd_info": None,
        "lot_type": None,
        "frontage_length": None,
        "depth_ratio": None,
        "depth": None,
        "min_frontage_ft": None,
        "edges_geojson": None,
        "error": error
    }

# ----- Manuel güncelleme için Helper Functions
def edges_to_geojson_str(edges_gdf):
    if edges_gdf is None or edges_gdf.empty:
        return None

    features = []

    for _, row in edges_gdf.iterrows():
        props = {}

        for col in edges_gdf.columns:
            if col == "geometry":
                continue

            value = row[col]

            # GeoJSON'a yazılamayan karmaşık kolonları atla
            if col in ["geometry_whole_edges"]:
                continue

            try:
                json.dumps(value)
                props[col] = value
            except Exception:
                props[col] = str(value)

        features.append({
            "type": "Feature",
            "geometry": mapping(row.geometry),
            "properties": props
        })

    return json.dumps({
        "type": "FeatureCollection",
        "features": features
    })

def edges_from_geojson_str(edges_geojson, crs=CRS_FEET):
    if edges_geojson is None or pd.isna(edges_geojson):
        return None

    data = json.loads(edges_geojson)
    edges = gpd.GeoDataFrame.from_features(data["features"], crs=crs)

    return edges

def update_result_edges_from_df(results_by_address, df_land_edges_road, address):
    row_match = df_land_edges_road[df_land_edges_road["address"] == address]

    if row_match.empty:
        raise ValueError(f"df_land_edges_road içinde adres bulunamadı: {address}")

    result = results_by_address.get(address)

    if result is None:
        raise ValueError(f"results_by_address içinde adres bulunamadı: {address}")

    edges_geojson = row_match.iloc[0]["edges_geojson"]
    edited_edges = edges_from_geojson_str(edges_geojson, crs=CRS_FEET)

    if edited_edges is None or edited_edges.empty:
        raise ValueError(f"edges_geojson boş: {address}")

    old_edges = result.get("edges_gdf")

    if old_edges is not None and not old_edges.empty:
        old_edges = old_edges.copy()

        # sadece manuel değişebilecek kolonları eski edges_gdf içine yaz
        update_cols = [
            "edge_type",
            "lotType",
            "is_frontage",
            "score",
            "length",
            "angle",
            "order"
        ]

        for col in update_cols:
            if col in edited_edges.columns:
                mapper = edited_edges.set_index("edge_id")[col].to_dict()
                old_edges[col] = old_edges["edge_id"].map(mapper).combine_first(old_edges.get(col))

        final_edges = old_edges

    else:
        final_edges = edited_edges

    result["edges_gdf"] = final_edges

    # lotType güncelle
    if "lotType" in final_edges.columns and not final_edges.empty:
        result["lotType"] = final_edges["lotType"].dropna().iloc[0] if len(final_edges["lotType"].dropna()) else result.get("lotType")

    # edge_groups yeniden hesapla
    result["edge_groups"] = group_edges_by_type_and_direction_simple(final_edges)

    # frontage bilgilerini yeniden hesapla
    front_edges = final_edges[final_edges["edge_type"] == "front"] if "edge_type" in final_edges.columns else final_edges.iloc[0:0]

    result["frontage_ids"] = front_edges["edge_id"].tolist()
    result["total_frontage"] = float(front_edges["length"].sum()) if "length" in front_edges.columns else float(front_edges.geometry.length.sum())
    result["frontage_lengths"] = [
        float(final_edges[final_edges.edge_id.isin(group)]["length"].sum())
        for group in result["edge_groups"].get("front", [])
    ]

    results_by_address[address] = result

    return results_by_address

def group_edges_by_type_and_direction_simple(edges_gdf, angle_tol=20): 
    def get_angle(line):
        x1, y1 = line.coords[0]
        x2, y2 = line.coords[-1]
        return math.degrees(math.atan2(y2 - y1, x2 - x1))

    grouped = {
        "front": [],
        "rear": [],
        "side": []
    }

    if edges_gdf is None or edges_gdf.empty or "edge_type" not in edges_gdf.columns:
        return grouped

    for edge_type in ["front", "rear", "side"]:
        subset = edges_gdf[edges_gdf["edge_type"] == edge_type].reset_index(drop=True)

        used = set()
        groups = []

        for i, row1 in subset.iterrows():
            if i in used:
                continue

            a1 = get_angle(row1.geometry)
            group_ids = [row1["edge_id"]]
            used.add(i)

            for j, row2 in subset.iterrows():
                if j in used:
                    continue

                a2 = get_angle(row2.geometry)

                diff = abs(a1 - a2) % 180
                diff = min(diff, 180 - diff)

                if diff < angle_tol:
                    group_ids.append(row2["edge_id"])
                    used.add(j)

            groups.append(group_ids)

        grouped[edge_type] = groups

    return grouped


# Maximum Building Footprint
def building_footprint(results_by_address, 
                       address, 
                       front_setback_ft, 
                       rear_setback_ft, 
                       side_setback_ft,
                       lotCoverageLimit                     
                       ):

    def line_to_vector(line):
        x1, y1 = line.coords[0]
        x2, y2 = line.coords[-1]
        return np.array([x2 - x1, y2 - y1])

    def normalize(v):
        
        norm = np.linalg.norm(v)
        if norm == 0:
            return v
        return v / norm

    # -----------------------------
    # GEOMETRY METRICS HELPER
    # -----------------------------
    def get_main_polygon(geom):
        if geom is None or geom.is_empty:
            return None

        try:
            geom = geom.buffer(0)
        except Exception:
            pass

        if geom.is_empty:
            return None

        if geom.geom_type == "Polygon":
            return geom

        if geom.geom_type == "MultiPolygon":
            return max(geom.geoms, key=lambda g: g.area)

        if geom.geom_type == "GeometryCollection":
            polys = [g for g in geom.geoms if g.geom_type == "Polygon"]
            if polys:
                return max(polys, key=lambda g: g.area)

        return None

    def get_geom_metrics(geom):
        main_geom = get_main_polygon(geom)

        if main_geom is None:
            return {
                "geometry": None,
                "area": 0.0,
                "perimeter": 0.0
            }

        return {
            "geometry": main_geom,
            "area": main_geom.area,
            "perimeter": main_geom.length
        }

    def make_true_half_plane(edge, parcel_geom, setback, scale=1000):

        if edge is None or edge.is_empty:
            return None

        try:
            # -----------------------------
            # 1. edge direction
            # -----------------------------
            v = line_to_vector(edge)
            v = normalize(v)

            # perpendicular (normal vector)
            normal = np.array([-v[1], v[0]])

            # -----------------------------
            # 2. midpoint
            # -----------------------------
            mid = edge.interpolate(0.5, normalized=True)

            centroid = parcel_geom.centroid

            # direction sign (parcel tarafı)
            to_centroid = np.array([centroid.x - mid.x, centroid.y - mid.y])

            if np.dot(normal, to_centroid) < 0:
                normal = -normal  # flip inward

            # -----------------------------
            # 3. offset line shift
            # -----------------------------
            offset_point = np.array([mid.x, mid.y]) + normal * setback

            # -----------------------------
            # 4. build BIG half-plane polygon
            # -----------------------------
            dx = v * scale
            dy = normal * scale

            p1 = offset_point - dx + dy
            p2 = offset_point + dx + dy
            p3 = offset_point + dx - dy
            p4 = offset_point - dx - dy

            return Polygon([p1, p2, p3, p4])

        except Exception:
            return None

    def calculate_max_building_footprint_exact(parcel_geom, edges_gdf, zoning_rules):

        front_sb = zoning_rules.get("front_setback", 25)
        rear_sb  = zoning_rules.get("rear_setback", 20)
        side_sb  = zoning_rules.get("side_setback", 10)

        if parcel_geom is None or parcel_geom.is_empty:
            return {
                "geometry": None,
                "area": 0.0,
                "perimeter": 0.0
            }

        buildable = parcel_geom.buffer(0)
        constraints = []

        for _, row in edges_gdf.iterrows():

            edge = row.geometry
            if edge is None or edge.is_empty:
                continue

            edge_type = row.get("edge_type", "side")

            setback = {
                "front": front_sb,
                "rear": rear_sb,
                "side": side_sb
            }.get(edge_type, side_sb)

            half_plane = make_true_half_plane(edge, parcel_geom, setback)

            if half_plane is not None and not half_plane.is_empty:
                constraints.append(half_plane)

        # -----------------------------
        # SAFE UNION (NO CASCADING FAIL)
        # -----------------------------
        if not constraints:
            return get_geom_metrics(buildable)

        constraint_union = unary_union(constraints)

        try:
            result = buildable.intersection(constraint_union)
        except Exception:
            result = buildable

        # -----------------------------
        # CLEAN GEOMETRY
        # -----------------------------
        if result is None or result.is_empty:
            return get_geom_metrics(buildable)

        # result = result.buffer(0)

        return get_geom_metrics(result)

    def plot_building_footprint_exact(
            parcel_geom, 
            edges_gdf, 
            roads_clipped=None, 
            lotCoverageLimit=None
            ):
        print("Plotting lotCoverageLimit:", lotCoverageLimit)

        def build_source_edges_gdf(edges_gdf):
            rows = []
            for _, row in edges_gdf.iterrows():
                edge_id = row["edge_id"]
                edge_type = row["edge_type"]                
                source_ids = row["source_edges"]
                source_geoms = row["geometry_whole_edges"]

                for idx, item in zip(source_ids, source_geoms):
                    rows.append({                        
                        "edge_id": idx,                     # # source edges ids
                        "edge_type": edge_type,
                        "geometry": item["geometry"],              # source segments geometry                        
                    })
            source_edges_gdf = gpd.GeoDataFrame(rows, crs=edges_gdf.crs)[["edge_id", "edge_type", "geometry"]]    
            return source_edges_gdf
        
        source_edges_gdf = build_source_edges_gdf(edges_gdf) 
        # display("source_edges_gdf___:", source_edges_gdf

        fig, ax = plt.subplots(figsize=(8, 8))
        
        # -----------------------------
        # CRS normalize (tek sefer)
        # -----------------------------
        if edges_gdf.crs is not None:
            edges_plot = edges_gdf.to_crs(CRS_FEET)
        else:
            edges_plot = edges_gdf   

        if source_edges_gdf.crs is not None:
            source_edges_plot = source_edges_gdf.to_crs(CRS_FEET)
        else:
            source_edges_plot = source_edges_gdf       

        # print("edges_plot.columns:::", edges_plot.columns)
        # display("edges_plot:::", edges_plot) 
        # display("source_edges_plot:::", source_edges_plot)                 
        
        # # 🔥 ORDER GARANTİ
        # edges_plot = edges_plot.sort_values("order").reset_index(drop=True)            

        # parcel da aynı CRS'e çekilmeli
        parcel_series = gpd.GeoSeries([parcel_geom], crs=edges_gdf.crs)
        parcel_plot = parcel_series.to_crs(crs=CRS_FEET).iloc[0]

        # roads da aynı
        if roads_clipped is not None and not roads_clipped.empty:
            roads_plot = roads_clipped.to_crs(crs=CRS_FEET)
        else:
            roads_plot = None

       
        # -----------------------------
        # 1️⃣ Parcel
        # -----------------------------
        x, y = parcel_plot.exterior.xy
        ax.plot(x, y, color="black", linewidth=2, label="Parcel")

        # -----------------------------
        # 2️⃣ Roads (CLIPPED)
        # -----------------------------
        # if roads_plot is not None:
        #     for i, geom in enumerate(roads_plot.geometry):

        #         if geom.geom_type == "LineString":
        #             x, y = geom.xy
        #             ax.plot(x, y, color="darkred", linewidth=3, alpha=0.7,
        #                     label="Road" if i == 0 else "")

        #         elif geom.geom_type == "MultiLineString":
        #             for line in geom.geoms:
        #                 x, y = line.xy
        #                 ax.plot(x, y, color="darkred", linewidth=3, alpha=0.7)

        used_labels = set()
        if roads_plot is not None:
            for geom in roads_plot.geometry:

                label = None
                if "Road" not in used_labels:
                    label = "Road"
                    used_labels.add("Road")

                if geom.geom_type == "LineString":
                    x, y = geom.xy
                    ax.plot(x, y, color="darkred", linewidth=3, alpha=0.7, label=label)

                elif geom.geom_type == "MultiLineString":
                    for line in geom.geoms:
                        x, y = line.xy
                        ax.plot(x, y, color="darkred", linewidth=3, alpha=0.7, label=label)
                        label = None  # sadece ilkinde label


        # -----------------------------
        # 3️⃣ Edges (TYPE RENKLİ 🔥)
        # -----------------------------
        used_labels = set()
        for i, row in source_edges_plot.iterrows():

            edge = row.geometry           
            edge_type = row.get("edge_type", "side")
    
            if edge_type == "front":
                color = "red"
            elif edge_type == "rear":
                color = "blue"
            else:
                color = "green"            

            label = None
            if edge_type not in used_labels:
                label = edge_type.capitalize()
                used_labels.add(edge_type)

            x, y = edge.xy
            ax.plot(x, y, color=color, linewidth=3, label=label)

        
        # -----------------------------
        # 4️⃣ Offsetline(edges_real)
        # -----------------------------
        def offsetline_edges_real():

            centroid = parcel_plot.centroid
            raw_offsets = []

            for i, row in edges_plot.iterrows():

                edge = row.geometry
                edge_type = row.get("edge_type", "side")           

                setback = {"front":25, "rear":20, "side":10}.get(edge_type, 10)
                

                try:
                    left_offset = edge.parallel_offset(setback, "left")
                    right_offset = edge.parallel_offset(setback, "right")
                except Exception:
                    continue

                if left_offset.geom_type == "MultiLineString":
                    left_offset = list(left_offset.geoms)[0]
                if right_offset.geom_type == "MultiLineString":
                    right_offset = list(right_offset.geoms)[0]

                def is_inside(line):
                    return line.distance(centroid) < edge.distance(centroid)

                offset_line = left_offset if is_inside(left_offset) else right_offset

                # 🔥 LINE UZAT (çok önemli)
                offset_line = scale(offset_line, xfact=5, yfact=5, origin='center')

                raw_offsets.append(offset_line)   
            
            # -----------------------------
            # 2️⃣ Komşularla kesiştir (ASIL OLAY)
            # -----------------------------
            final_lines = []

            n = len(raw_offsets)

            for i in range(n):

                prev_line = raw_offsets[i - 1]
                curr_line = raw_offsets[i]
                next_line = raw_offsets[(i + 1) % n]

                try:
                    p1 = curr_line.intersection(prev_line)
                    p2 = curr_line.intersection(next_line)

                    if p1.is_empty or p2.is_empty:
                        continue

                    # intersection point al
                    if p1.geom_type != "Point":
                        p1 = list(p1.geoms)[0]
                    if p2.geom_type != "Point":
                        p2 = list(p2.geoms)[0]

                    clipped = LineString([p1, p2])
                    final_lines.append(clipped)

                except Exception:
                    continue
            
            # -----------------------------
            # 3️⃣ Çizim
            # -----------------------------   
            ax.set_title("Maximum Building Footprint")
            # ax.set_aspect('equal')
            ax.axis("equal")
            ax.axis("off")    
            for i, line in enumerate(final_lines):
                x, y = line.xy
                ax.plot(x, y,
                        color="#4da6ff",
                        linestyle="--",
                        linewidth=2,
                        label="Footprint" if i == 0 else "")  
        
            # handles, labels = ax.get_legend_handles_labels()
            # unique = dict(zip(labels, handles))
            # ax.legend(unique.values(), unique.keys()) 
            #    
            handles, labels = ax.get_legend_handles_labels()
            unique = {}
            for h, l in zip(handles, labels):
                if l and l not in unique:
                    unique[l] = h
            ax.legend(unique.values(), unique.keys())
            # plt.show()  
        #  offsetline_edges_real()      

        # -----------------------------
        # 4️⃣ Offsetline(edges_whole)
        # -----------------------------          
        def offsetline_edges_whole10_final(
                parcel_plot, 
                source_edges_plot, 
                ax, 
                lotCoverageLimit
                ):
        
            lotCoverage_geom = None

            # -----------------------------
            # 1️⃣ EDGE SIRALAMA
            # -----------------------------
            def sort_edges(edges_gdf):
                edges_gdf = edges_gdf.copy()
                center = edges_gdf.unary_union.centroid

                def angle(line):
                    mid = line.interpolate(0.5, normalized=True)
                    return np.arctan2(mid.y - center.y, mid.x - center.x)

                edges_gdf["angle_sort"] = edges_gdf.geometry.apply(angle)
                return edges_gdf.sort_values("angle_sort").reset_index(drop=True)

            edges_sorted = sort_edges(source_edges_plot.copy())
            centroid = parcel_plot.centroid

            # -----------------------------
            # 2️⃣ YARDIMCI FONKSİYONLAR
            # -----------------------------
            def extend_line(line, distance=1000):
                x1, y1 = line.coords[0]
                x2, y2 = line.coords[-1]

                dx = x2 - x1
                dy = y2 - y1
                length = (dx**2 + dy**2) ** 0.5

                if length == 0:
                    return line

                ux = dx / length
                uy = dy / length

                new_start = (x1 - ux * distance, y1 - uy * distance)
                new_end = (x2 + ux * distance, y2 + uy * distance)

                return LineString([new_start, new_end])

            def pick_longest_line(geom):
                if geom.is_empty:
                    return None
                if geom.geom_type == "LineString":
                    return geom
                if geom.geom_type == "MultiLineString":
                    return max(geom.geoms, key=lambda g: g.length)
                return None

            def is_inside(line, edge):
                return line.distance(centroid) < edge.distance(centroid)

            def get_offset_lines(extend=False, extend_dist=50):
                raw_offsets = []

                for _, row in edges_sorted.iterrows():
                    edge = row.geometry
                    edge_type = row.get("edge_type", "side")

                    # setback = {"front": 35, "rear": 10, "side": 10}.get(edge_type, 10)
                    setback = {
                        "front": front_setback_ft,
                        "rear": rear_setback_ft,
                        "side": side_setback_ft
                    }.get(edge_type, side_setback_ft)
                    try:
                        left_offset = edge.parallel_offset(setback, "left")
                        right_offset = edge.parallel_offset(setback, "right")
                    except Exception:
                        continue

                    left_offset = pick_longest_line(left_offset)
                    right_offset = pick_longest_line(right_offset)

                    if left_offset is None or right_offset is None:
                        continue

                    offset_line = left_offset if is_inside(left_offset, edge) else right_offset

                    if extend:
                        offset_line = extend_line(offset_line, extend_dist)

                    raw_offsets.append(offset_line)

                return raw_offsets
   
            def lot_coverage_polygon(
                footprint,
                lotCoverageLimit,
                parcel_plot=None
            ):

                if footprint is None or lotCoverageLimit is None:
                    return None

                try:
                    target_area = float(lotCoverageLimit)

                    if footprint.area <= 0:
                        return None

                    # -----------------------------------------
                    # Alan bazlı ölçek katsayısı
                    # -----------------------------------------
                    scale_factor = (target_area / footprint.area) ** 0.5

                    # -----------------------------------------
                    # Polygon büyüt
                    # -----------------------------------------
                    lotCoverage_geom = affinity.scale(
                        footprint,
                        xfact=scale_factor,
                        yfact=scale_factor,
                        origin="center"
                    )

                    # -----------------------------------------
                    # Parcel sınırını aşmasın
                    # -----------------------------------------
                    if parcel_plot is not None:
                        lotCoverage_geom = lotCoverage_geom.intersection(parcel_plot)

                    # boş geometri kontrolü
                    if lotCoverage_geom.is_empty:
                        return None

                    return lotCoverage_geom

                except Exception as e:
                    print("coverage error:", e)
                    return None
        
            def lot_coverage_polygon2(
                footprint,
                lotCoverageLimit,
                parcel_plot=None,
                tolerance=1.0,
                max_iter=60
            ):
                """
                footprint         : başlangıç polygonu
                lotCoverageLimit  : hedef alan (sq ft)
                parcel_plot       : sınır polygonu
                tolerance         : alan toleransı
                max_iter          : binary search iterasyon sayısı
                """

                if footprint is None or lotCoverageLimit is None:
                    return None

                try:

                    target_area = float(lotCoverageLimit)

                    if footprint.area <= 0:
                        return None

                    # --------------------------------------------------
                    # Eğer parcel yoksa normal scale
                    # --------------------------------------------------
                    if parcel_plot is None:

                        scale_factor = (target_area / footprint.area) ** 0.5

                        return affinity.scale(
                            footprint,
                            xfact=scale_factor,
                            yfact=scale_factor,
                            origin="center"
                        )

                    # --------------------------------------------------
                    # Binary Search
                    # Amaç:
                    # - parcel dışına taşmasın
                    # - alan target_area'ya en yakın olsun
                    # --------------------------------------------------

                    low = 1.0
                    high = 100.0

                    best_geom = footprint
                    best_diff = abs(footprint.area - target_area)

                    for _ in range(max_iter):

                        mid = (low + high) / 2.0

                        candidate = affinity.scale(
                            footprint,
                            xfact=mid,
                            yfact=mid,
                            origin="center"
                        )

                        # parcel içine kırp
                        clipped = candidate.intersection(parcel_plot)

                        if clipped.is_empty:
                            high = mid
                            continue

                        current_area = clipped.area

                        diff = abs(current_area - target_area)

                        # en iyi sonucu sakla
                        if diff < best_diff:
                            best_geom = clipped
                            best_diff = diff

                        # hedefe yeterince yakınsa çık
                        if diff <= tolerance:
                            best_geom = clipped
                            break

                        # alan küçük -> daha büyüt
                        if current_area < target_area:
                            low = mid

                        # alan büyük -> küçült
                        else:
                            high = mid

                    return best_geom

                except Exception as e:
                    print("coverage error:", e)
                    return None

            def draw_result(footprint, lotCoverage_geom, building_area, building_perimeter, method_name):

                ax.set_title(f"Maximum Building Footprint ({method_name})")
                ax.axis("equal")
                ax.axis("off")

                # --------------------------------------------------
                # Geometrileri alana göre sırala (büyük önce)
                # --------------------------------------------------
                geoms_to_draw = []

                if footprint is not None:
                    geoms_to_draw.append({
                        "geom": footprint,
                        "area": footprint.area,
                        "edge_color": "#4da6ff",
                        "fill_color": "yellow",
                        "fill_alpha": 0.25,
                        "label_line": "Setbacks Footprint",
                        "label_fill": "Setbacks Area"
                    })

                if lotCoverage_geom is not None and not lotCoverage_geom.is_empty:
                    geoms_to_draw.append({
                        "geom": lotCoverage_geom,
                        "area": lotCoverage_geom.area,
                        "edge_color": "blue",
                        "fill_color": "cyan",
                        "fill_alpha": 0.20,
                        "label_line": "LotCoverage Footprint",
                        "label_fill": "LotCoverage Area"
                    })

                # büyük alan önce çizilsin
                geoms_to_draw = sorted(
                    geoms_to_draw,
                    key=lambda g: g["area"],
                    reverse=True
                )

                # --------------------------------------------------
                # Çizim
                # --------------------------------------------------
                for item in geoms_to_draw:

                    geom = item["geom"]

                    x, y = geom.exterior.xy

                    ax.plot(
                        x,
                        y,
                        color=item["edge_color"],
                        linestyle="--",
                        linewidth=2,
                        label=item["label_line"]
                    )

                    ax.fill(
                        x,
                        y,
                        alpha=item["fill_alpha"],
                        color=item["fill_color"],
                        label=item["label_fill"]
                    )

                # --------------------------------------------------
                # Yazılar
                # --------------------------------------------------
                c = footprint.centroid
                ax.text(
                    c.x,
                    c.y + 10,
                    f"Setbacks_Area: {building_area:.2f} sq ft\nSetbacks_Perimeter: {building_perimeter:.2f} ft",
                    ha="left",
                    va="baseline",
                    fontsize=10,
                )

                d = lotCoverage_geom.centroid
                ax.text(
                    d.x,
                    d.y - 10,
                    f"LotCoverage_Area: {lotCoverage_geom.area:.2f} sq ft\nLotCoverage_Perimeter: {lotCoverage_geom.length:.2f} ft",
                    ha="left",
                    va="baseline",
                    fontsize=10,
                )

                # --------------------------------------------------
                # Legend tekrarlarını temizle
                # --------------------------------------------------
                handles, labels = ax.get_legend_handles_labels()

                unique = {}

                for h, l in zip(handles, labels):
                    if l and l not in unique:
                        unique[l] = h

                ax.legend(unique.values(), unique.keys())

                plt.tight_layout()
            

            # =========================================================
            # 3️⃣ PRIMARY
            # offsetline_edges_whole7_final_lines__linemerge_düzeltilmis
            # =========================================================
            raw_offsets = get_offset_lines(extend=True, extend_dist=50)

            final_lines = []
            n = len(raw_offsets)

            for i in range(n):
                prev_line = raw_offsets[i - 1]
                curr_line = raw_offsets[i]
                next_line = raw_offsets[(i + 1) % n]

                try:
                    p1 = curr_line.intersection(prev_line)
                    p2 = curr_line.intersection(next_line)

                    if p1.is_empty or p2.is_empty:
                        continue

                    if p1.geom_type != "Point":
                        p1 = list(p1.geoms)[0]
                    if p2.geom_type != "Point":
                        p2 = list(p2.geoms)[0]

                    if p1.distance(p2) < 1:
                        continue

                    clipped = LineString([p1, p2])
                    final_lines.append(clipped)

                except Exception:
                    continue

            polygons = []
            if final_lines:
                try:
                    merged = unary_union(final_lines)
                    merged = linemerge(merged)
                    polygons = list(polygonize(merged))
                except Exception:
                    polygons = []

            if polygons:
                footprint = max(polygons, key=lambda p: p.area)
                footprint = footprint.intersection(parcel_plot)
                footprint = get_main_polygon(footprint)

                if footprint is not None and not footprint.is_empty:
                    # if footprint.geom_type == "MultiPolygon":
                    #     footprint = max(footprint.geoms, key=lambda g: g.area)

                    building_area = footprint.area
                    building_perimeter = footprint.length
                    print("✅ method used: extend_line + final_lines + linemerge")
                    print(f"SetBacks Area: {building_area:.2f} sq ft")
                    print(f"SetBacks Perimeter: {building_perimeter:.2f} ft")

                    lotCoverage_geom = lot_coverage_polygon(
                                            footprint=footprint,
                                            lotCoverageLimit=lotCoverageLimit,
                                            parcel_plot=parcel_plot
                                        )
                    lotCoverage_area = getattr(lotCoverage_geom, "area", 0) or 0
                    lotCoverage_perimeter = getattr(lotCoverage_geom, "length", 0) or 0
                    print("lotCoverageLimit:", lotCoverageLimit)
                    print(f"lotCoverage Area: {lotCoverage_area:.2f} sq ft")
                    print(f"lotCoverage Perimeter: {lotCoverage_perimeter:.2f} ft") 

                    draw_result(footprint, lotCoverage_geom, building_area, building_perimeter, "extend_line + final_lines + linemerge")
                    return {    
                        "footprint": footprint,
                        "lotCoverage_geom": lotCoverage_geom,
                        "building_area": building_area,
                        "building_perimeter": building_perimeter,
                        "raw_offsets": raw_offsets,
                        "final_lines": final_lines,
                        "method": "extend_line + final_lines + linemerge"
                    }

            print("⚠️ primary method polygon oluşturamadı, fallback çalışıyor...")

            # =========================================================
            # 4️⃣ FALLBACK
            # offsetline_edges_whole4_linemerge_extend_line
            # =========================================================
            raw_offsets = get_offset_lines(extend=True, extend_dist=50)

            polygons = []
            if raw_offsets:
                try:
                    merged = unary_union(raw_offsets)
                    merged = linemerge(merged)
                    polygons = list(polygonize(merged))
                except Exception:
                    polygons = []

            if not polygons:
                print("❌ polygon oluşmadı")
                return None, 0.0

            footprint = max(polygons, key=lambda p: p.area)
            footprint = footprint.intersection(parcel_plot)
            footprint = get_main_polygon(footprint)

            if footprint.is_empty:
                print("❌ footprint boş")
                return None, 0.0

            if footprint.geom_type == "MultiPolygon":
                footprint = max(footprint.geoms, key=lambda g: g.area)

            building_area = footprint.area
            building_perimeter = footprint.length
            print("✅ method used: extend_line + final_lines + linemerge")
            print(f"SetBacks Area: {building_area:.2f} sq ft")
            print(f"SetBacks Perimeter: {building_perimeter:.2f} ft")

            lotCoverage_geom = lot_coverage_polygon(
                                            footprint=footprint,
                                            lotCoverageLimit=lotCoverageLimit,
                                            parcel_plot=parcel_plot
                                        )
            lotCoverage_area = getattr(lotCoverage_geom, "area", 0) or 0
            lotCoverage_perimeter = getattr(lotCoverage_geom, "length", 0) or 0
            print("lotCoverageLimit:", lotCoverageLimit)
            print(f"lotCoverage Area: {lotCoverage_area:.2f} sq ft")
            print(f"lotCoverage Perimeter: {lotCoverage_perimeter:.2f} ft") 

            draw_result(footprint, lotCoverage_geom, building_area, building_perimeter, "extend_line + raw_offsets + linemerged")
            return {
                "footprint": footprint,
                "lotCoverage_geom": lotCoverage_geom,
                "building_area": building_area,
                "building_perimeter": building_perimeter,
                "raw_offsets": raw_offsets,
                "final_lines": [],
                "method": "extend_line + raw_offsets + linemerged"
            }
                
                
        result = offsetline_edges_whole10_final(
            parcel_plot, 
            source_edges_plot, 
            ax, 
            lotCoverageLimit=lotCoverageLimit
            )
        if result is None:
            return {
                "footprint": None,
                "lotCoverage_geom": None, 
                "building_area": 0.0,
                "building_perimeter": 0.0,
                "parcel_plot": parcel_plot,
                "edges_plot": edges_plot,
                "source_edges_gdf": source_edges_gdf,                
                "source_edges_plot": source_edges_plot,
                "roads_plot": roads_plot,
                "raw_offsets": [],
                "final_lines": [],
                "method": None,
                "figure": fig,
                "ax": ax
            }
        result.update({
            "parcel_plot": parcel_plot,
            "edges_plot": edges_plot,
            "source_edges_gdf": source_edges_gdf, 
            "source_edges_plot": source_edges_plot,
            "roads_plot": roads_plot,
            "figure": fig,
            "ax": ax
        })
        return result
    
    def pipeline_max_building_footprint(
            address, 
            front_setback_ft, 
            rear_setback_ft, 
            side_setback_ft,
            lotCoverageLimit
        ):

        data = results_by_address.get(address)
        if data is None:
            raise ValueError(f"Bu adres için detection sonucu bulunamadı: {address}")   
        
        footprint_halfplane = calculate_max_building_footprint_exact(
                            parcel_geom=data["parcel_geom"], 
                            edges_gdf=data["edges_gdf"], 
                            zoning_rules={
                                "front_setback": front_setback_ft, 
                                "rear_setback": rear_setback_ft, 
                                "side_setback": side_setback_ft}
                                )
        
        # print("DATA:", data)
        frontage_gdf = data.get("map_data", {}).get("frontage")   
        # frontage_gdf = frontage_gdf.to_crs(data["edges_gdf"].crs)         
        # roads_clipped = data.get("map_data", {}).get("roads_clipped")
        # roads_clipped = roads_clipped.to_crs(data["edges_gdf"].crs)

        # VSCode plot  
        plot_result = plot_building_footprint_exact(
                parcel_geom=data["parcel_geom"],
                edges_gdf=data["edges_gdf"],      
                roads_clipped=frontage_gdf,
                lotCoverageLimit=lotCoverageLimit
            )
        print("plot_result:", plot_result["source_edges_gdf"])

        return {
             "address": address,            

            "parcel": data["parcel"], 
            "lotType": data["lotType"],
            "lot_info": data["lot_info"],              

            # hesap verileri
            "parcel_geom": data["parcel_geom"],
            "edges_gdf": data["edges_gdf"],
            "source_edges_gdf": plot_result["source_edges_gdf"],
            "frontage_gdf": frontage_gdf,
            
            # half-plane sonucu
            "footprint_geom_halfplane": footprint_halfplane["geometry"],
            "footprint_area_halfplane": footprint_halfplane["area"],
            "footprint_perimeter_halfplane": footprint_halfplane["perimeter"],

            # çizim için hazır plot layer'ları
            "parcel_plot": plot_result["parcel_plot"],
            "edges_plot": plot_result["edges_plot"],
            "source_edges_plot": plot_result["source_edges_plot"],
            "roads_plot": plot_result["roads_plot"],
            "footprint": plot_result["footprint"],
            "lotCoverage_geom": plot_result["lotCoverage_geom"],
            
            "building_area": plot_result["building_area"],
            "building_perimeter": plot_result["building_perimeter"],

            # debug / footprint oluşturma layer'ları
            "raw_offsets": plot_result["raw_offsets"],
            "final_lines": plot_result["final_lines"],
            "method": plot_result["method"],

            # ister tekrar kullan
            "figure": plot_result["figure"],
            "ax": plot_result["ax"]
        }

    result = pipeline_max_building_footprint(
        address,
        front_setback_ft,
        rear_setback_ft,
        side_setback_ft,
        lotCoverageLimit
    )
    return result


# Redraw Building Footprint
def reDraw(address, row):
    """
    CSV içindeki:
    * edges_geojson
    * roads_geojson
    * parcel_geojson
    * footprint_geojson
    * lotCoverageLimit

    alanlarını okuyup çizim yapar.
    """

    # --------------------------------------------------
    # GEOJSON -> GDF
    # --------------------------------------------------
    def geojson_to_gdf(geojson_str):

        if pd.isna(geojson_str):
            return None

        geo = json.loads(geojson_str)

        if "features" not in geo:
            return None

        return gpd.GeoDataFrame.from_features(geo["features"])

    def ensure_projected(gdf):
        if gdf is None:
            return None

        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")

        # if looks like lat/lon
        minx, miny, maxx, maxy = gdf.total_bounds

        if abs(maxx) <= 180 and abs(maxy) <= 90:
            # it's lon/lat → project
            return gdf.to_crs("EPSG:2276")

        return gdf

    # --------------------------------------------------
    # LOAD
    # --------------------------------------------------
    parcel_gdf = geojson_to_gdf(row["parcel_geojson"])
    edges_gdf = geojson_to_gdf(row["edges_geojson"])
    roads_gdf = geojson_to_gdf(row["roads_geojson"])
    setbacks_gdf = geojson_to_gdf(row["setbacks_geojson"])

    parcel_gdf = ensure_projected(parcel_gdf)
    edges_gdf = ensure_projected(edges_gdf)
    roads_gdf = ensure_projected(roads_gdf)
    setbacks_gdf = ensure_projected(setbacks_gdf)

    print("parcel_gdf   :", parcel_gdf.total_bounds)
    print("edges_gdf    :", edges_gdf.total_bounds)
    print("roads_gdf    :", roads_gdf.total_bounds)
    print("setbacks_gdf :", setbacks_gdf.total_bounds)

    # --------------------------------------------------
    # CRS FIX
    # --------------------------------------------------
    if parcel_gdf is not None:

        if parcel_gdf.crs is None:
            parcel_gdf = parcel_gdf.set_crs("EPSG:2276")

        target_crs = parcel_gdf.crs

        for gdf_name in ["edges_gdf", "roads_gdf", "setbacks_gdf"]:

            gdf = locals()[gdf_name]

            if gdf is None:
                continue

            if gdf.crs is None:
                gdf = gdf.set_crs(target_crs)
            else:
                gdf = gdf.to_crs(target_crs)

            locals()[gdf_name] = gdf

    # --------------------------------------------------
    # LOT COVERAGE POLYGON
    # --------------------------------------------------
    lotCoverage_geom = None

    lot_coverage_limit = row.get("lotCoverageLimit", None)

    if parcel_gdf is not None and lot_coverage_limit is not None:

        parcel_geom = parcel_gdf.geometry.iloc[0]

        if not parcel_geom.is_valid:
            parcel_geom = parcel_geom.buffer(0)

        parcel_area = parcel_geom.area

        print("parcel_area:", parcel_area)
        print("lotCoverageLimit:", lot_coverage_limit)

        # hedef alan / parcel alanı
        coverage_ratio = float(lot_coverage_limit) / parcel_area

        # scale factor
        scale_factor = coverage_ratio ** 0.5

        print("coverage_ratio:", coverage_ratio)
        print("scale_factor:", scale_factor)

        # merkezden küçült
        lotCoverage_geom = affinity.scale(
            parcel_geom,
            xfact=scale_factor,
            yfact=scale_factor,
            origin='center'
        )

        print("coverage_geom_area:", lotCoverage_geom.area)

    # --------------------------------------------------
    # ÇİZİM
    # --------------------------------------------------
    fig, ax = plt.subplots(figsize=(8,8))

    # parcel
    if parcel_gdf is not None:
        parcel_gdf.plot(
            ax=ax,
            facecolor="none",
            edgecolor="black",
            linewidth=2,
            label="Parcel"
        )

    # roads
    if roads_gdf is not None:
        roads_gdf.plot(
            ax=ax,
            color="gray",
            linewidth=3,
            label="Roads"
        )

    # edges
    if edges_gdf is not None:

        color_map = {
            "front": "red",
            "rear": "blue",
            "side": "green"
        }

        for _, r in edges_gdf.iterrows():

            edge_type = r.get("edge_type", "side")
            color = color_map.get(edge_type, "green")

            gpd.GeoSeries(
                [r.geometry],
                crs=edges_gdf.crs
            ).plot(
                ax=ax,
                color=color,
                linewidth=3
            )

    # footprint
    if setbacks_gdf is not None:
        setbacks_gdf.plot(
            ax=ax,
            facecolor="yellow",
            edgecolor="#4da6ff",
            alpha=0.4,
            linewidth=2,
            label="Footprint"
        )

    # --------------------------------------------------
    # LOT COVERAGE POLYGON ÇİZ
    # --------------------------------------------------
    if lotCoverage_geom is not None:

        gpd.GeoSeries(
            [lotCoverage_geom],
            crs=parcel_gdf.crs
        ).plot(
            ax=ax,
            facecolor="cyan",
            edgecolor="blue",
            alpha=0.35,
            linewidth=2,
            linestyle="--",
            label="Lot Coverage Limit"
        )

    # --------------------------------------------------
    # GÖRSEL AYARLAR
    # --------------------------------------------------
    ax.set_title(address)

    ax.set_aspect("equal")

    ax.axis("off")

    handles, labels = ax.get_legend_handles_labels()

    unique = {}

    for h, l in zip(handles, labels):
        if l not in unique:
            unique[l] = h

    ax.legend(
        unique.values(),
        unique.keys()
    )

    plt.tight_layout()
    plt.show()
































































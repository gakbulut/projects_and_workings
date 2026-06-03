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





























































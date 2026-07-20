import os

# Fix: Set the PROJ database path before importing libraries that use pyproj
# os.environ["PROJ_DATA"] = r"D:\VS-file\Digitization\env\Library\share\proj"

import matplotlib
matplotlib.use("Agg")  # Force non-interactive backend BEFORE anything else imports

import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import osmnx as ox
from shapely.geometry import shape
import tempfile
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection, LineCollection
from geopy.geocoders import Nominatim

# --- Page Setup & Styling ---
st.set_page_config(page_title="OSM Data Extractor", page_icon="🌍", layout="wide")

# Custom CSS for a more eye-catching UI
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #000080;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #34495e;
        margin-bottom: 2rem;
    }
    .stButton>button {
        background-color: #27ae60;
        color: white;
        font-weight: 600;
        border-radius: 8px;
        padding: 0.5rem 2rem;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #2ecc71;
        box-shadow: 0 4px 12px rgba(46, 204, 113, 0.3);
        color: white;
    }
    .success-text {
        color: #27ae60;
        font-weight: 600;
    }
    .sidebar-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #121a21;
        margin-bottom: 1rem;
    }
            .search-box {
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🌍 Auto Digitization</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Select an area on the map and extract OpenStreetMap data seamlessly.</div>', unsafe_allow_html=True)

# --- Sidebar UI ---
st.sidebar.markdown('<div class="sidebar-header">🛠️ Options</div>', unsafe_allow_html=True)
st.sidebar.markdown("Draw a polygon on the map, select features, and extract.")

get_roads = st.sidebar.checkbox("🛣️ Roads (Network)", value=True)
get_buildings = st.sidebar.checkbox("🏢 Buildings")
get_rivers = st.sidebar.checkbox("🌊 Rivers/Waterways")
get_parks = st.sidebar.checkbox("🌳 Parks/Gardens/Forests")

st.sidebar.markdown("---")
st.sidebar.markdown('<div class="sidebar-header">📥 Downloads</div>', unsafe_allow_html=True)

# Container for download buttons in the sidebar
download_container = st.sidebar.container()

# --- Helper: Add features to Folium map ---
def add_roads_to_map(G, folium_map):
    """Add road edges to the folium map as red polylines."""
    road_group = folium.FeatureGroup(name="Roads")
    for u, v, data in G.edges(data=True):
        coords = [
            (G.nodes[u]["y"], G.nodes[u]["x"]),
            (G.nodes[v]["y"], G.nodes[v]["x"]),
        ]
        folium.PolyLine(
            coords, color="#e74c3c", weight=2, opacity=0.8
        ).add_to(road_group)
    road_group.add_to(folium_map)


def add_gdf_to_map(gdf, folium_map, color, layer_name):
    """Add a GeoDataFrame's geometries to the folium map."""
    feature_group = folium.FeatureGroup(name=layer_name)
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type in ['Point', 'MultiPoint']:
            continue
        try:
            geo_json = folium.GeoJson(
                geom.__geo_interface__,
                style_function=lambda x, c=color: {
                    "fillColor": c,
                    "color": c,
                    "weight": 1.5,
                    "fillOpacity": 0.5,
                },
            )
            geo_json.add_to(feature_group)
        except Exception:
            continue
    feature_group.add_to(folium_map)

    # --- 🔍 Map Search Feature ---
st.write("### 🔍 Find & Target Location")

# Establish defaults
default_lat, default_lon = 30.1011, 71.1555
zoom_level = 13

with st.container():
    st.markdown('<div class="search-box">', unsafe_allow_html=True)
    search_type = st.radio("Choose search method:", ["📍 Search by Address / City", "🌐 Input Map Coordinates"], horizontal=True)

    if search_type == "📍 Search by Address / City":
        search_query = st.text_input("Enter location name (e.g., Islamabad, Pakistan):", placeholder="Type to search...")
        if search_query:
            try:
                geolocator = Nominatim(user_agent="osm_digitizer_app")
                location_data = geolocator.geocode(search_query)
                if location_data:
                    default_lat, default_lon = location_data.latitude, location_data.longitude
                    zoom_level = 14
                    st.success(f"Found: {location_data.address} ({default_lat:.4f}, {default_lon:.4f})")
                else:
                    st.error("Location not found. Please try a different name.")
            except Exception as e:
                st.error(f"Geocoding service busy or offline: {e}")
                
    else:
        col1, col2 = st.columns(2)
        with col1:
            default_lat = st.number_input("Target Latitude", value=default_lat, format="%.5f")
        with col2:
            default_lon = st.number_input("Target Longitude", value=default_lon, format="%.5f")
        zoom_level = 15
        
    st.markdown('</div>', unsafe_allow_html=True)


# --- Display Map ---
st.write("### 1️⃣ Draw your area of interest")

# Center dynamically based on search
m = folium.Map(location=[default_lat, default_lon], zoom_start=zoom_level)

# Add a subtle locator pin for reference if user searched or targeted coordinates
folium.Marker(
    [default_lat, default_lon],  
    icon=folium.Icon(color="darkblue", icon="info-sign")
).add_to(m)

# Add drawing tools
draw = Draw(
    export=False,
    position='topleft',
    draw_options={'polyline': False, 'circle': False, 'circlemarker': False, 'marker': False}
)
draw.add_to(m)

# Display input map
output = st_folium(
    m, 
    width=1000, 
    height=500, 
    key="input_map",
    returned_objects=["last_active_drawing"]
)

# --- Processing Logic ---
st.write("### 2️⃣ Process Data")

if st.button("Extract Data"):
    last_drawing = output.get("last_active_drawing") if output else None
    
    if last_drawing is None:
        st.warning("⚠️ Please draw a polygon or rectangle on the map first!")
    else:
        with st.spinner("🔄 Extracting data from OpenStreetMap... Please wait."):
            try:
                # Buffer by 0 to fix any random self-intersecting drawn polygons
                geom = shape(last_drawing["geometry"]).buffer(0)

                with tempfile.TemporaryDirectory() as tmpdir:
                    gpkg_path = os.path.join(tmpdir, "extracted_data.gpkg")
                    png_path = os.path.join(tmpdir, "map_plot.png")

                    # Create results map centered on the drawn area
                    centroid = geom.centroid
                    result_map = folium.Map(location=[centroid.y, centroid.x], zoom_start=13)

                    # Create matplotlib figure for PNG export (avoids crash using manual plotting)
                    fig, ax = plt.subplots(figsize=(10, 10))
                    ax.set_facecolor("white")

                    # 1. Process Roads
                    if get_roads:
                        try:
                            # truncate_by_edge=True ensures edges are cut exactly at the boundary
                            G = ox.graph_from_polygon(geom, network_type="all", truncate_by_edge=True)
                            gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)
                            gdf_edges.to_file(gpkg_path, layer="roads", driver="GPKG")
                            add_roads_to_map(G, result_map)
                            
                            # Plot roads on matplotlib ax
                            edge_lines = []
                            for u, v, data in G.edges(data=True):
                                # Sometimes 'geometry' is present for true edge shapes in OSMnx
                                if 'geometry' in data:
                                    edge_lines.append(list(data['geometry'].coords))
                                else:
                                    x1, y1 = G.nodes[u]["x"], G.nodes[u]["y"]
                                    x2, y2 = G.nodes[v]["x"], G.nodes[v]["y"]
                                    edge_lines.append([(x1, y1), (x2, y2)])
                            if edge_lines:
                                lc = LineCollection(edge_lines, colors="#333333", linewidths=0.8, alpha=0.9)
                                ax.add_collection(lc)
                        except Exception as e:
                            st.warning("⚠️ Could not extract Roads (No matching features found in area).")

                    # 2. Process Buildings
                    if get_buildings:
                        try:
                            buildings = ox.features_from_polygon(geom, tags={"building": True})
                            if not buildings.empty:
                                # Clip EXACTLY to the polygon boundary (100% accuracy)
                                buildings = gpd.clip(buildings, geom)
                                buildings.to_file(gpkg_path, layer="buildings", driver="GPKG")
                                add_gdf_to_map(buildings, result_map, "orange", "Buildings")
                                
                                # Plot buildings on matplotlib ax
                                patches = []
                                for _, row in buildings.iterrows():
                                    g = row.geometry
                                    if g is None or g.is_empty: continue
                                    if g.geom_type == "Polygon":
                                        patches.append(MplPolygon(list(g.exterior.coords), closed=True))
                                    elif g.geom_type == "MultiPolygon":
                                        for poly in g.geoms:
                                            patches.append(MplPolygon(list(poly.exterior.coords), closed=True))
                                if patches:
                                    pc = PatchCollection(patches, facecolor="orange", alpha=0.7, edgecolor="none")
                                    ax.add_collection(pc)
                        except Exception as e:
                            st.warning("⚠️ Could not extract Buildings (No matching features found in area).")

                    # 3. Process Rivers
                    if get_rivers:
                        try:
                            rivers = ox.features_from_polygon(geom, tags={"waterway": True, "natural": "water"})
                            if not rivers.empty:
                                # Clip EXACTLY to the polygon boundary (100% accuracy)
                                rivers = gpd.clip(rivers, geom)
                                rivers.to_file(gpkg_path, layer="rivers", driver="GPKG")
                                add_gdf_to_map(rivers, result_map, "#3498db", "Rivers/Waterways")
                                
                                # Plot rivers on matplotlib ax
                                river_lines, river_patches = [], []
                                for _, row in rivers.iterrows():
                                    g = row.geometry
                                    if g is None: continue
                                    if g.geom_type == "LineString":
                                        river_lines.append(list(g.coords))
                                    elif g.geom_type == "MultiLineString":
                                        for line in g.geoms:
                                            river_lines.append(list(line.coords))
                                    elif g.geom_type == "Polygon":
                                        river_patches.append(MplPolygon(list(g.exterior.coords), closed=True))
                                    elif g.geom_type == "MultiPolygon":
                                        for poly in g.geoms:
                                            river_patches.append(MplPolygon(list(poly.exterior.coords), closed=True))
                                if river_lines:
                                    rlc = LineCollection(river_lines, colors="blue", linewidths=1.0, alpha=0.7)
                                    ax.add_collection(rlc)
                                if river_patches:
                                    rpc = PatchCollection(river_patches, facecolor="blue", alpha=0.7, edgecolor="none")
                                    ax.add_collection(rpc)
                        except Exception as e:
                            st.warning("⚠️ Could not extract Rivers (No matching features found in area).")

                    # 4. Process Parks / Gardens / Forests
                    if get_parks:
                        try:
                            parks = ox.features_from_polygon(
                                geom,
                                tags={
                                    "leisure": ["park", "garden", "nature_reserve"],
                                    "landuse": ["forest", "grass", "meadow"],
                                    "natural": ["wood", "scrub", "heath"],
                                },
                            )
                            if not parks.empty:
                                # Clip EXACTLY to the polygon boundary
                                parks = gpd.clip(parks, geom)
                                parks.to_file(gpkg_path, layer="parks", driver="GPKG")
                                add_gdf_to_map(parks, result_map, "#2ecc71", "Parks/Gardens/Forests")

                                # Plot parks on matplotlib ax
                                park_patches = []
                                for _, row in parks.iterrows():
                                    g = row.geometry
                                    if g is None or g.is_empty:
                                        continue
                                    if g.geom_type == "Polygon":
                                        park_patches.append(MplPolygon(list(g.exterior.coords), closed=True))
                                    elif g.geom_type == "MultiPolygon":
                                        for poly in g.geoms:
                                            park_patches.append(MplPolygon(list(poly.exterior.coords), closed=True))
                                if park_patches:
                                    ppc = PatchCollection(
                                        park_patches,
                                        facecolor="#2ecc71",
                                        alpha=0.6,
                                        edgecolor="#27ae60",
                                        linewidths=0.5,
                                    )
                                    ax.add_collection(ppc)
                        except Exception as e:
                            st.warning("⚠️ Could not extract Parks (No matching features found in area).")

                    # Finalize matplotlib plot and save
                    ax.autoscale_view()
                    ax.set_aspect("equal")
                    ax.set_axis_off()
                    fig.savefig(png_path, dpi=300, bbox_inches="tight", facecolor="white")
                    plt.close(fig)

                    folium.LayerControl().add_to(result_map)
                    
                    st.markdown('<div class="success-text">✅ Extraction complete! Scroll down for preview. Download files from the sidebar.</div>', unsafe_allow_html=True)

                    # Save data to session state for download buttons
                    if os.path.exists(gpkg_path):
                        with open(gpkg_path, "rb") as f:
                            st.session_state['gpkg_data'] = f.read()
                    
                    if os.path.exists(png_path):
                        with open(png_path, "rb") as f:
                            st.session_state['png_data'] = f.read()

                    # Save results map HTML to session state so it survives reruns
                    st.session_state['result_map_html'] = result_map._repr_html_()

            except Exception as e:
                st.error(f"An error occurred during extraction: {e}")

# --- Show Results Preview (Outside Button Block) ---
if 'result_map_html' in st.session_state:
    st.write("---")
    st.write("### 3️⃣ Results Preview")
    import streamlit.components.v1 as components
    components.html(st.session_state['result_map_html'], width=1000, height=500)

# Render download buttons in sidebar if data is in session state
if 'gpkg_data' in st.session_state:
    download_container.download_button(
        label="🗺️ Download GeoPackage (.gpkg)",
        data=st.session_state['gpkg_data'],
        file_name="extracted_data.gpkg",
        mime="application/geopackage+sqlite3"
    )

if 'png_data' in st.session_state:
    download_container.download_button(
        label="🖼️ Download Image (.png)",
        data=st.session_state['png_data'],
        file_name="map_plot.png",
        mime="image/png"
    )
    
if 'gpkg_data' not in st.session_state and 'png_data' not in st.session_state:
    download_container.info("Run extraction to see download options.")

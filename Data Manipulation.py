import pandas as pd
import streamlit as st
import plotly.express as px
import warnings
import googlemaps
import datetime
import os
warnings.filterwarnings('ignore')

gmaps = googlemaps.Client(key='AIzaSyA1EedkC8LZp8J3n3vCrAvFCBFoC2flaNs')

px.set_mapbox_access_token("pk.eyJ1IjoiZW1tYW51ZWw1NTMiLCJhIjoiY21iMHo2NHR0MHByNDJqc2ExbW9tYXIxdyJ9.ZpoelGXM50x8AoLAPU6V9Q")

# --- PAGE CONFIG ---
st.set_page_config(page_title="UK Air Passenger Demand", page_icon=":bar_chart:", layout="wide")
st.title(" :bar_chart: UK Population")
st.markdown('<style>div.block-container{padding-top:3rem;}</style>', unsafe_allow_html=True)

# FILE UPLOAD
fl = st.file_uploader(":file_folder: Upload a file", type=["csv", "txt", "xlsx", "xls"])

if fl is not None:
    filename = fl.name
    st.write(filename)
    if filename.endswith(".csv"):
        townpop = pd.read_csv(fl, encoding="ISO-8859-1")
    else:
        townpop = pd.read_excel(fl)
else:
    townpop = pd.read_excel("2023popestimates.xlsx")

# ---------------------------------------------------------------------------------------------
# --- Data Cleaning ---
# CLEAN HEADERS & VALUES
townpop.columns = townpop.columns.str.strip()
townpop['Geography'] = townpop['Geography'].str.strip()

# REGION / COUNTY ASSIGNMENT
townpop['Region'] = None
townpop['County'] = None

current_region = None
current_county = None

for i, row in townpop.iterrows():
    geo_type = row['Geography']
    name = row['Name']

    if geo_type == "Region":
        current_region = name
        current_county = None  #  Reset county when region changes
    elif geo_type == "County":
        current_county = name

    if geo_type not in ["Region", "County"]:
        townpop.at[i, 'Region'] = current_region
        townpop.at[i, 'County'] = current_county

# FILTER TO RELEVANT LOCAL AUTHORITIES
townpop = townpop[townpop['Geography'].isin([
    "Unitary Authority", "Metropolitan District", "Non-metropolitan District", "London Borough"
])]

# Define region multipliers
region_multipliers = {
    "LONDON": 2.6,
    "SOUTH EAST": 1.85,
    "SOUTH WEST": 1.45,
    "EAST": 1.65,
    "WEST MIDLANDS": 1.3,
    "EAST MIDLANDS": 1.4,
    "YORKSHIRE AND THE HUMBER": 1.3,
    "NORTH WEST": 1.5,
    "NORTH EAST": 1.1,
    "WALES": 1.05
}

# Add multiplier column based on Region
townpop['Multiplier'] = townpop['Region'].map(region_multipliers)

# Make column showing Air travel demand
townpop['Annual Air Travel Demand'] = (townpop['Multiplier'] * townpop['Mid-2023'])

# --- Cache Setup ---
# Get Travel times to Heathrow using google maps API
CACHE_PATH = "travel_time_cache.csv"

# Load cache if it exists
if os.path.exists(CACHE_PATH):
    cache_df = pd.read_csv(CACHE_PATH)
    try:
        travel_time_cache = cache_df.set_index("Town")[["Driving", "Transit"]].to_dict(orient="index")
    except:
        travel_time_cache = {}
else:
    travel_time_cache = {}

# COORDINATE CACHE SETUP
COORD_CACHE_PATH = "coordinates_cache.csv"

# Load existing coordinate cache
coord_cache = {}
if os.path.exists(COORD_CACHE_PATH):
    try:
        coord_df = pd.read_csv(COORD_CACHE_PATH)
        if 'Town' in coord_df.columns and 'Latitude' in coord_df.columns and 'Longitude' in coord_df.columns:
            coord_cache = dict(zip(coord_df['Town'], zip(coord_df['Latitude'], coord_df['Longitude'])))
    except Exception as e:
        print(f"Warning: Could not load coordinate cache: {e}")
        coord_cache = {}



# Define get_coordinates BEFORE it's used

def get_coordinates(town):
    if town in coord_cache:
        return coord_cache[town]
    try:
        result = gmaps.geocode(f"{town}, UK")
        if result:
            location = result[0]["geometry"]["location"]
            lat, lon = location["lat"], location["lng"]
            coord_cache[town] = (lat, lon)
            return lat, lon
    except Exception as e:
        print(f"Error for {town}: {e}")
    return None, None

# Track printed errors
seen_errors = set()

# Define a function for getting Driving and Public transport travel time to Heathrow and store it as a dictionary

def get_travel_times(town):
    if town in travel_time_cache:
        return travel_time_cache[town]  # {'Driving': x, 'Transit': y}

    times = {}
    try:
        # --- Driving ---
        driving_result = gmaps.distance_matrix(
            f"{town}, UK",
            "Heathrow Airport, London, UK",
            mode="driving",
            departure_time = datetime.datetime.now() + datetime.timedelta(hours=1)
        )
        element = driving_result['rows'][0]['elements'][0]
        if element.get('status') == 'OK':
            times['Driving'] = element['duration']['value'] // 60
        else:
            msg = f"No driving route for {town}: {element.get('status')}"
            if msg not in seen_errors:
                print(msg)
                seen_errors.add(msg)
            times['Driving'] = None

        # --- Public Transport (Transit) ---
        transit_result = gmaps.distance_matrix(
            f"{town}, UK",
            "Heathrow Airport, London, UK",
            mode="transit",
            departure_time = datetime.datetime.now() + datetime.timedelta(hours=1)
        )
        element = transit_result['rows'][0]['elements'][0]
        if element.get('status') == 'OK':
            times['Transit'] = element['duration']['value'] // 60
        else:
            msg = f"No transit route for {town}: {element.get('status')}"
            if msg not in seen_errors:
                print(msg)
                seen_errors.add(msg)
            times['Transit'] = None

        # Cache and return
        travel_time_cache[town] = times
        return times

    except Exception as e:
        msg = f"Error for {town}: {e}"
        if msg not in seen_errors:
            print(msg)
            seen_errors.add(msg)
        return {'Driving': None, 'Transit': None}

@st.cache_data(show_spinner=False)
def get_coordinates_cached(town):
    return get_coordinates(town)

@st.cache_data(show_spinner=False)
def get_travel_times_cached(town):
    return get_travel_times(town)


    
# -----------------------------------------------
# Ensure columns exist to avoid KeyErrors
if 'Latitude' not in townpop.columns:
    townpop['Latitude'] = None
if 'Longitude' not in townpop.columns:
    townpop['Longitude'] = None

# Apply to your dataframe
missing_coords = townpop[townpop['Latitude'].isna() | townpop['Longitude'].isna()]

for idx, row in missing_coords.iterrows():
    lat, lon = get_coordinates_cached(row['Name'])
    townpop.at[idx, 'Latitude'] = lat
    townpop.at[idx, 'Longitude'] = lon


# -----------------------------------------------
# Get travel times (Driving + Transit) only for towns missing them
# -----------------------------------------------

# Ensure travel time columns exist before updating
if "Driving Time (mins)" not in townpop.columns:
    townpop["Driving Time (mins)"] = None
if "Transit Time (mins)" not in townpop.columns:
    townpop["Transit Time (mins)"] = None

# Identify towns missing either driving or transit times
missing_times = townpop[
    townpop['Driving Time (mins)'].isna() | townpop['Transit Time (mins)'].isna()
]

# Only calculate for those towns
for idx, row in missing_times.iterrows():
    times = get_travel_times_cached(row['Name'])
    if isinstance(times, dict):
        townpop.at[idx, 'Driving Time (mins)'] = times.get('Driving')
        townpop.at[idx, 'Transit Time (mins)'] = times.get('Transit')


# Save updated travel time cache to CSV
travel_cache_rows = []
for town, time_data in travel_time_cache.items():
    if isinstance(time_data, dict):
        travel_cache_rows.append({
            "Town": town,
            "Driving": time_data.get("Driving"),
            "Transit": time_data.get("Transit")
        })

pd.DataFrame(travel_cache_rows).to_csv("travel_mode_cache.csv", index=False)


# --------------------------------------------------

# REGION + COUNTY DROPDOWNS
region_list = townpop['Region'].dropna().unique()
county_list = townpop['County'].dropna().unique()

st.sidebar.header("Choose your Filters")
selected_regions = st.sidebar.multiselect("Select Region(s)", region_list)
selected_counties = st.sidebar.multiselect("Select County(ies)", county_list)
within_2hr_drive = st.sidebar.checkbox("Only show towns within 2 hours of Heathrow", value=False)
exclude_london = st.sidebar.checkbox("Exclude London")

# APPLY FILTERS
filtered_df = townpop.copy()
if selected_regions:
    filtered_df = filtered_df[filtered_df['Region'].isin(selected_regions)]
if selected_counties:
    filtered_df = filtered_df[filtered_df['County'].isin(selected_counties)]
if within_2hr_drive:
    filtered_df = filtered_df[filtered_df["Driving Time (mins)"] <= 120]
if exclude_london:
    filtered_df = filtered_df[filtered_df['Region'].str.upper() != "LONDON"]

# DISPLAY
st.dataframe(filtered_df)

# ---------------------------------------------------------------------------
# --- Make Plots ---
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📈 Summary",
    "🏙️ Population & Demand",
    "🕒 Travel Time Distribution",
    "📊 Demand by Region",
    "📋 High Demand Towns",
    "🌍 Heatmap",
    "🚉 Transit vs Car Gaps"
])

with tab1:
# SUMMARY STATS
    st.subheader("Total Population in Filtered Selection")
    st.metric("Population", f"{filtered_df['Mid-2023'].sum():,}")

with tab2:
    # Show Bar Chart of Population
    st.subheader("Population of Towns")
    fig = px.bar(
        filtered_df, 
        x = "Region", 
        y = "Mid-2023", 
        text = filtered_df["Mid-2023"].apply(lambda x: f"{x:,.0f}"), 
        template = "seaborn")
    st.plotly_chart(fig,use_container_width=True, height = 200)

    st.subheader("Total Annual Air Travel Demand in Filtered Selection")
    st.metric("Demand", f"{filtered_df['Annual Air Travel Demand'].sum():,}")

with tab3:
    # --- Show Bar Chart of Air Travel Demand ---
    # Create bar chart
    fig = px.bar(
        filtered_df,
        x="Region",
        y="Annual Air Travel Demand",
        text=filtered_df["Annual Air Travel Demand"].apply(lambda x: f"{x:,.0f}"),
        template="seaborn",
        title="Total Annual Air Travel Demand by Region"
    )
    # Show chart in Streamlit
    st.plotly_chart(fig, use_container_width=True)

# --- Top 10 Areas by Air Travel Demand ---

    st.subheader("✈️ Top 10 Areas by Annual Air Travel Demand")
    top10 = filtered_df.nlargest(10, 'Annual Air Travel Demand')

    fig = px.bar(
        top10,
        x='Name',
        y='Annual Air Travel Demand',
        text='Annual Air Travel Demand',
        title='Top 10 Areas by Annual Air Travel Demand',
        template='seaborn'
    )
    fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
    fig.update_layout(xaxis_tickangle=45)

    st.plotly_chart(fig, use_container_width=True)

# --- Travel Time Distribution to Heathrow ---

    st.subheader("⏱️ Distribution of Travel Times to Heathrow")

    # Drop rows with missing travel time
    valid_travel_df = filtered_df.dropna(subset=["Driving Time (mins)", "Transit Time (mins)"])

    # Create histogram
    fig = px.histogram(
        valid_travel_df,
        x="Driving Time (mins)",
        nbins=20,
        title="Distribution of Travel Times to Heathrow from Districts (Driving)",
        labels={"Driving Time (mins)": "Travel Time (minutes)"},
        template="seaborn"
    )
    # Show plot
    st.plotly_chart(fig, use_container_width=True)

# --- Show High Demand towns within 90mins of Heathrow
with tab4:
    st.subheader("📊 Share of Total Air Travel Demand by Region")

    pie_df = filtered_df.groupby("Region")["Annual Air Travel Demand"].sum().reset_index()
    fig = px.pie(
        pie_df,
        values="Annual Air Travel Demand",
        names="Region",
        title="Share of Total Air Travel Demand by Region"
    )
    st.plotly_chart(fig, use_container_width=True)

with tab5:
    st.subheader("📋 High Demand Towns Within 90 Minutes of Heathrow")
    high_demand_close = filtered_df[
        (filtered_df["Driving Time (mins)"] <= 120) &
        (filtered_df["Annual Air Travel Demand"] > filtered_df["Annual Air Travel Demand"].median())
    ][["Name", "Region", "Mid-2023", "Annual Air Travel Demand", "Driving Time (mins)"]]

    st.dataframe(high_demand_close.sort_values("Annual Air Travel Demand", ascending=False))


# Save coordinate cache back to CSV
coord_out_df = pd.DataFrame([
    {'Town': town, 'Latitude': lat, 'Longitude': lon}
    for town, (lat, lon) in coord_cache.items()
])
coord_out_df.to_csv(COORD_CACHE_PATH, index=False)

# Drop rows with missing data for map
townpop = townpop.dropna(subset=['Latitude', 'Longitude', 'Annual Air Travel Demand'])

# --- Plot bar chart showing top 10 areas with biggest difference between car and Public transport travel times ---
# Filter valid rows
mode_df = townpop.dropna(subset=["Driving Time (mins)", "Transit Time (mins)"]).copy()
mode_df["Time Gap (mins)"] = mode_df["Transit Time (mins)"] - mode_df["Driving Time (mins)"]

# Show top differences
mode_df["Time Gap (mins)"] = pd.to_numeric(mode_df["Time Gap (mins)"], errors="coerce")
top_gap = mode_df.nlargest(10, "Time Gap (mins)")

with tab7:
    st.subheader("🚉 Areas with the Biggest Public Transport vs Car Travel Time Gap")
    fig = px.bar(
        top_gap,
        x="Name",
        y="Time Gap (mins)",
        text="Time Gap (mins)",
        title="Top 10 Areas with Biggest Public Transport Delay vs Driving",
        template="seaborn"
    )
    fig.update_traces(textposition='outside')
    st.plotly_chart(fig, use_container_width=True)

# ----------------------------------
# Heatmap
# ----------------------------------
with tab6:
    st.subheader("🌍 Heatmap of Air Travel Demand")
    fig = px.density_mapbox(
        townpop,
        lat='Latitude',
        lon='Longitude',
        z='Annual Air Travel Demand',
        radius=20,
        center=dict(lat=52.5, lon=-1.5),
        zoom=5,
        mapbox_style="carto-positron",
        height = 1000
    )
    st.plotly_chart(fig, use_container_width=True)


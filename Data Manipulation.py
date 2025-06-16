import pandas as pd
import streamlit as st
import plotly.express as px
import warnings
import googlemaps
import datetime
import os
warnings.filterwarnings('ignore')

gmaps = googlemaps.Client(key='AIzaSyAY2UiYlMrmqUMarroMfogazA6Ls0t7rV0')


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

# --- Get Multiplier ---
region_trips = pd.DataFrame({
    "Region": [
        "LONDON","SOUTH EAST", "SOUTH WEST", "EAST", "WEST MIDLANDS", "EAST MIDLANDS",
        "YORKSHIRE AND THE HUMBER", "NORTH WEST", "NORTH EAST", "WALES"
    ],
    "Heathrow Trips": [
        29936000,12053000, 4095000, 4739000, 1809000, 1881000,
        859000, 614000, 155000, 1161000
    ]
})

# Calculate Regional Population
region_pop = townpop.groupby("Region")["Mid-2023"].sum().reset_index()
region_pop.columns = ["Region", "Region Population"]
# Merge pop with trips
region_data = pd.merge(region_trips, region_pop, on="Region")
region_data["Trip Rate"] = region_data["Heathrow Trips"] / region_data["Region Population"]
# Merge with main table
townpop = townpop.merge(region_data[["Region", "Trip Rate"]], on="Region", how="left")
townpop["Annual Air Travel Demand"] = townpop["Mid-2023"] * townpop["Trip Rate"]

# --- Cache Setup ---
# --- Travel Time Cache Setup ---
CACHE_PATH = "travel_time_cache.parquet"

# Load travel time cache if it exists and is not empty
travel_time_cache = {}
if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 0:
    try:
        cache_df = pd.read_parquet(CACHE_PATH)
        travel_time_cache = cache_df.set_index("Town")[["Driving", "Transit"]].to_dict(orient="index")
    except Exception as e:
        print(f"Warning: Could not load travel time cache: {e}")
        travel_time_cache = {}

# --- Coordinate Cache Setup ---
COORD_CACHE_PATH = "coordinates_cache.parquet"

coord_cache = {}
if os.path.exists(COORD_CACHE_PATH) and os.path.getsize(COORD_CACHE_PATH) > 0:
    try:
        coord_df = pd.read_parquet(COORD_CACHE_PATH)
        if {'Town', 'Latitude', 'Longitude'}.issubset(coord_df.columns):
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


# Save updated travel time cache to Parquet only if it has data
travel_cache_rows = [
    {
        "Town": town,
        "Driving": time_data.get("Driving"),
        "Transit": time_data.get("Transit")
    }
    for town, time_data in travel_time_cache.items()
    if isinstance(time_data, dict)
]

if travel_cache_rows:
    pd.DataFrame(travel_cache_rows).to_parquet(CACHE_PATH, index=False)


# --------------------------------------------------

# REGION + COUNTY DROPDOWNS
# --- Sidebar Filters ---
st.sidebar.header("Choose your Filters")

# Build initial lists
region_list = townpop['Region'].dropna().unique()
county_list = townpop['County'].dropna().unique()
district_list = townpop['Name'].sort_values().unique()

# Region selection
selected_regions = st.sidebar.multiselect("Select Region(s)", region_list, key="region_selector")
# Update counties list based on region selection
if selected_regions:
    county_list = townpop[townpop['Region'].isin(selected_regions)]['County'].dropna().unique()
selected_counties = st.sidebar.multiselect("Select County(ies)", county_list, key="county_selector")
# Update district list based on county selection
if selected_counties:
    district_list = townpop[townpop['County'].isin(selected_counties)]['Name'].sort_values().unique()
selected_districts = st.sidebar.multiselect("Select District(s)", district_list, key="district_selector")

# Other filters
within_2hr_drive = st.sidebar.checkbox("Only show towns within 2 hours of Heathrow", value=False)
exclude_london = st.sidebar.checkbox("Exclude London")

# --- Apply Filters to DataFrame ---
filtered_df = townpop.copy()

if selected_regions:
    filtered_df = filtered_df[filtered_df['Region'].isin(selected_regions)]
if selected_counties:
    filtered_df = filtered_df[filtered_df['County'].isin(selected_counties)]
if selected_districts:
    filtered_df = filtered_df[filtered_df['Name'].isin(selected_districts)]
if within_2hr_drive:
    filtered_df = filtered_df[filtered_df["Driving Time (mins)"] <= 120]
if exclude_london:
    filtered_df = filtered_df[filtered_df['Region'].fillna('').str.upper() != "LONDON"]

# --- Display Output ---
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

# Annual Air Travel Demand
    st.subheader("Total Annual Air Travel Demand in Filtered Selection")
    total_demand = filtered_df["Annual Air Travel Demand"].sum()
    st.metric("Demand", f"{total_demand:,.0f}")

with tab2:
    # Show Bar Chart of Population
    st.subheader("Population of Towns")
    fig = px.bar(
        filtered_df, 
        x = "Region", 
        y = "Mid-2023", 
        text = filtered_df["Mid-2023"], 
        template="plotly_white",
        height = 400)
    fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
    st.plotly_chart(fig,use_container_width=True, height = 200)
    

with tab3:
    # --- Show Bar Chart of Air Travel Demand ---
    # Create bar chart
    fig = px.bar(
        filtered_df,
        x="Region",
        y="Annual Air Travel Demand",
        text=filtered_df["Annual Air Travel Demand"],
        template="plotly_white",
        title="Total Annual Air Travel Demand by Region"
    )
    fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
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
        template="plotly_white"
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

    # Sort first
    sorted_close = high_demand_close.sort_values("Annual Air Travel Demand", ascending=False)

    # Then apply formatting
    st.dataframe(
        sorted_close.style.format({
            "Mid-2023": "{:,.0f}",
            "Annual Air Travel Demand": "{:,.0f}",
            "Driving Time (mins)": "{:,.0f}"
        })
    )


# Save coordinate cache back to Parquet only if it has data
if coord_cache:
    coord_out_df = pd.DataFrame([
        {'Town': town, 'Latitude': lat, 'Longitude': lon}
        for town, (lat, lon) in coord_cache.items()
    ])
    coord_out_df.to_parquet(COORD_CACHE_PATH, index=False)

# Drop rows with missing data for map
filtered_df1 = filtered_df.dropna(subset=['Latitude', 'Longitude', 'Annual Air Travel Demand'])

# --- Plot bar chart showing top 10 areas with biggest difference between car and Public transport travel times ---
# Filter valid rows
mode_df = filtered_df1.dropna(subset=["Driving Time (mins)", "Transit Time (mins)"]).copy()
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
        template="plotly_white"
    )
    fig.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
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
    


# ======================================================================
#  Update data (keep the same file names):
#   1. Illegal activities: run the patrol block join, save Illegal_Activities_with_PatrolBlock.gpkg
#   2. Tracks: run the export notebook, which makes track_reach.csv (never upload the big tracks file)
#   3. Replace the files in this folder (and on GitHub), then refresh the page
# ======================================================================
import os
import json
import pandas as pd
import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Patrol Block Dashboard", layout="wide")


# ######################################################################
# SECTION 1: SETTINGS  (the only part you normally need to edit)
# ######################################################################

# --- 1.1 Where the data files are -------------------------------------
# Default = the same folder as App.py. Or write a full path, for example:
# DATA_DIR = r"C:\Users\BunnarithHun\OneDrive - WWF\WWF\Python\Data Science"
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 1.2 Data file 1: patrol blocks (polygons) ------------------------
BLOCKS_FILE = "Patrol_Block.gpkg"
BLOCKS_LAYER = "patrol_block"
BLOCKS_NAME_COL = "Name"            # column with the block name
BLOCKS_PA_COL = "PA"                # column with the protected area (SWS / PPWS)

# --- 1.3 Data file 2: illegal activity points -------------------------
CASES_FILE = "Illegal_Activities_with_PatrolBlock.gpkg"
CASES_LAYER = "Illegal_Activities_with_PatrolBlock"
CASES_DATE_COL = "Date"
CASES_PA_COL = "PA"
CASES_BLOCK_COL = "Patrol_Block"    # block name already added to each point

# --- 1.4 Data file 3: patrol tracking lines ---------------------------
TRACKS_FILE = "track_reach.csv" 

# --- 1.5 Texts, colours and sizes -------------------------------------
APP_TITLE = "Illegal Activities and Patrol Tracking by Block"
COLOR_CASES = "#d7191c"             # bar colour, illegal activities
COLOR_TRACKS = "#2f7fb5"            # bar colour, patrol tracking
SCALE_CASES = "YlOrRd"              # map colours, illegal activities
SCALE_TRACKS = "YlGnBu"             # map colours, patrol tracking
CHART_HEIGHT = 650                  # height of charts and maps (pixels)
LAYOUT_RATIO = [1, 1.3]             # width of [bar chart, map] in each row
LABEL_SIZE = 11                     # size of the block names on the maps


# --- 1.6 Set Default PA -------------------------------------
DEFAULT_PA = "SWS"                  # PA selected when the page opens

# ######################################################################
# SECTION 2: LOAD THE DATA  (runs once, then it is remembered)
# ######################################################################
def file_path(name):
    return os.path.join(DATA_DIR, name)


def files_signature():
    """Last-modified time of the 3 files. When a file is replaced, this
    changes, so the app reloads the data by itself."""
    return tuple(os.path.getmtime(file_path(f)) for f in (BLOCKS_FILE, CASES_FILE, TRACKS_FILE))


@st.cache_data(show_spinner="Loading data (this can take a minute)...")
def load_data(signature):
    # Patrol blocks -> standard column names: Patrol_Block, PA
    blocks = gpd.read_file(file_path(BLOCKS_FILE), layer=BLOCKS_LAYER)
    blocks = blocks.rename(columns={BLOCKS_NAME_COL: "Patrol_Block", BLOCKS_PA_COL: "PA"})
    blocks = blocks[["Patrol_Block", "PA", "geometry"]]

    # Illegal activities -> standard column names: Date, PA, Patrol_Block
    cases = gpd.read_file(file_path(CASES_FILE), layer=CASES_LAYER)
    cases = pd.DataFrame(cases.drop(columns="geometry"))
    cases = cases.rename(columns={CASES_DATE_COL: "Date", CASES_PA_COL: "PA",
                                  CASES_BLOCK_COL: "Patrol_Block"})
    cases["Date"] = pd.to_datetime(cases["Date"])

    # Tracks -> which blocks does each track reach? -> standard names: ID, Start_Date
    reach = pd.read_csv(file_path(TRACKS_FILE), parse_dates=["Start_Date"])

    # Map shapes and label positions (one point inside each block)
    blocks_4326 = blocks.to_crs(4326)
    geo = json.loads(blocks_4326[["Patrol_Block", "geometry"]].to_json())
    centre = blocks_4326.geometry.representative_point()
    labels = pd.DataFrame({"Patrol_Block": blocks_4326["Patrol_Block"].values,
                           "lon": centre.x.values, "lat": centre.y.values})

    return pd.DataFrame(blocks.drop(columns="geometry")), geo, labels, cases, reach


blocks_df, geo, labels, cases, reach = load_data(files_signature())


# ######################################################################
# SECTION 3: SIDEBAR FILTERS
# ######################################################################
st.sidebar.header("Filters")

pa_list = sorted(blocks_df["PA"].unique())
pa = st.sidebar.selectbox("Protected area", pa_list,
                          index=pa_list.index(DEFAULT_PA) if DEFAULT_PA in pa_list else 0)

dmin = cases["Date"].min().date()
dmax = max(cases["Date"].max(), reach["Start_Date"].max()).date()
dates = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)

# Note: which dates each dataset covers (helps users choose a correct range)
st.sidebar.caption(f"Illegal activity data: {cases['Date'].min().date()} to {cases['Date'].max().date()}")
st.sidebar.caption(f"Patrol tracking data: {reach['Start_Date'].min().date()} to {reach['Start_Date'].max().date()}")

if not isinstance(dates, tuple) or len(dates) < 2:
    st.stop()                       # wait until both dates are chosen
d1, d2 = pd.Timestamp(dates[0]), pd.Timestamp(dates[1])


# ######################################################################
# SECTION 4: FILTER AND COUNT
# ######################################################################
names = blocks_df.loc[blocks_df["PA"] == pa, "Patrol_Block"].tolist()     # blocks of this PA

c = cases[(cases["PA"] == pa) & cases["Date"].between(d1, d2)]
r = reach[reach["Patrol_Block"].isin(names) & reach["Start_Date"].between(d1, d2)]

cases_by_block = c["Patrol_Block"].value_counts().reindex(names, fill_value=0)
tracks_by_block = r.groupby("Patrol_Block")["ID"].nunique().reindex(names, fill_value=0)


# ######################################################################
# SECTION 5: CHART FUNCTIONS
# ######################################################################
def bar_chart(series, color):
    """Horizontal bars, biggest on top."""
    s = series.sort_values()
    fig = px.bar(x=s.values, y=s.index, orientation="h", text=s.values,
                 color_discrete_sequence=[color])
    fig.update_layout(height=CHART_HEIGHT, margin=dict(l=0, r=0, t=40, b=0),
                      xaxis_title=None, yaxis_title=None,
                      title=dict(text="Ranking by block", x=0))
    return fig


def block_map(series, label, scale, title):
    """Blocks coloured by value, with the block name and number on each block."""
    df = pd.DataFrame({"Patrol_Block": series.index, label: series.values})
    fig = px.choropleth(df, geojson=geo, locations="Patrol_Block",
                        featureidkey="properties.Patrol_Block",
                        color=label, color_continuous_scale=scale)
    fig.update_geos(fitbounds="locations", visible=False)

    lab = labels[labels["Patrol_Block"].isin(series.index)].copy()
    lab["value"] = lab["Patrol_Block"].map(series)
    fig.add_trace(go.Scattergeo(
        lon=lab["lon"], lat=lab["lat"],
        text=lab["Patrol_Block"] + "<br>" + lab["value"].astype(str),
        mode="text", textfont=dict(size=LABEL_SIZE, color="black"),
        showlegend=False, hoverinfo="skip"))

    fig.update_layout(height=CHART_HEIGHT, margin=dict(l=0, r=0, t=40, b=0),
                      title=dict(text=title, x=0))
    return fig


# ######################################################################
# SECTION 6: THE PAGE
# ######################################################################
st.title(APP_TITLE)
st.caption(f"{pa} | {dates[0]} to {dates[1]}")

# ---------- Row 1: illegal activities ----------
st.subheader("1. Illegal activities")
st.metric("Total cases", f"{len(c):,}")
left, right = st.columns(LAYOUT_RATIO)
left.plotly_chart(bar_chart(cases_by_block, COLOR_CASES), use_container_width=True)
right.plotly_chart(block_map(cases_by_block, "cases", SCALE_CASES, "Illegal activities by block"),
                   use_container_width=True)

st.divider()

# ---------- Row 2: patrol tracking ----------
st.subheader("2. Patrol tracking achievement")
if r.empty:
    st.info("No tracking data for this PA and period. Blocks cannot be compared with patrol effort.")
else:
    st.metric("Tracks reaching the blocks", f"{r['ID'].nunique():,}")
    left, right = st.columns(LAYOUT_RATIO)
    left.plotly_chart(bar_chart(tracks_by_block, COLOR_TRACKS), use_container_width=True)
    right.plotly_chart(block_map(tracks_by_block, "tracks", SCALE_TRACKS, "Tracks reaching each block"),
                       use_container_width=True)

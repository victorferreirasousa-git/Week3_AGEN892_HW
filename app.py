import pandas as pd
import requests
import folium
import branca
import re
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="US State Income Map", layout="wide")
st.title("US State Income Map")

@st.cache_data(ttl=86400)
def load_data():
    # ---- 1) County income data ----
    income = pd.read_csv(
        "https://raw.githubusercontent.com/pri-data/50-states/master/data/income-counties-states-national.csv",
        dtype=str,
    )
    income.columns = [c.strip() for c in income.columns]

    # pick income-YYYY, income-YYYYa/b, etc.
    def pick_income_col(df, year: int):
        pat = re.compile(fr"(?i)^income[\s_-]?{year}[a-z]?$")
        cands = [c for c in df.columns if pat.match(c)]
        if not cands:
            return None
        return max(cands, key=lambda c: pd.to_numeric(df[c], errors="coerce").notna().sum())

    c2015 = pick_income_col(income, 2015)
    c1989 = pick_income_col(income, 1989)

    def first_match(df, options):
        low = {c.lower(): c for c in df.columns}
        for o in options:
            if o in low:
                return low[o]
        return None

    cstate  = first_match(income, ["state", "state_abbr", "stateabbr"])
    ccounty = first_match(income, ["county", "county_name"])

    missing = []
    if c2015 is None: missing.append("income-2015*")
    if c1989 is None: missing.append("income-1989* (may be income-1989a/b)")
    if cstate is None: missing.append("state")
    if ccounty is None: missing.append("county")
    if missing:
        st.error(f"Input CSV is missing expected columns: {missing}\nFound: {list(income.columns)}")
        st.stop()

    income = income.rename(columns={
        c2015: "income-2015",
        c1989: "income-1989",
        cstate: "state",
        ccounty: "county",
    })
    income["income-2015"] = pd.to_numeric(income["income-2015"], errors="coerce")
    income["income-1989"] = pd.to_numeric(income["income-1989"], errors="coerce")

    # ---- 2) State polygons ----
    states_geo = requests.get(
        "https://raw.githubusercontent.com/python-visualization/folium-example-data/main/us_states.json"
    ).json()

    # ---- 3) State name -> 2-letter abbreviation ----
    abbrs = pd.DataFrame(
        requests.get(
            "https://gist.githubusercontent.com/tvpmb/4734703/raw/b54d03154c339ed3047c66fefcece4727dfc931a/US%2520State%2520List"
        ).json()
    )
    def find_col(df, *aliases):
        canon = {c.lower().replace(" ", "").replace("_", "").replace("-", ""): c for c in df.columns}
        for a in aliases:
            k = a.lower().replace(" ", "").replace("_", "").replace("-", "")
            if k in canon:
                return canon[k]
        return None

    name_col = find_col(abbrs, "name", "state", "statename")
    a2_col   = find_col(abbrs, "abbreviation", "alpha-2", "alpha2", "abbr", "code")
    if name_col is None or a2_col is None:
        st.error(f"Unexpected schema for state list. Columns: {list(abbrs.columns)}")
        st.stop()
    abbrs = abbrs.rename(columns={name_col: "name", a2_col: "alpha2"})
    name_to_alpha2 = dict(zip(abbrs["name"], abbrs["alpha2"]))

    return income, states_geo, name_to_alpha2

income, states_geo, name_to_alpha2 = load_data()

# Per-state medians across counties
state_medians = income.groupby("state").agg(
    median_2015=("income-2015", "median"),
    median_1989=("income-1989", "median"),
    n_counties=("county", "count"),
).reset_index()

med_2015_by_alpha2 = state_medians.set_index("state")["median_2015"].to_dict()
med_1989_by_alpha2 = state_medians.set_index("state")["median_1989"].to_dict()

# ---- Layout columns defined BEFORE use ----
left, right = st.columns([2, 1], gap="large")

# ---- Map ----
vals = pd.Series(med_2015_by_alpha2)
vmin, vmax = float(vals.min()), float(vals.max())
colormap = branca.colormap.LinearColormap(
    colors=["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    vmin=vmin, vmax=vmax,
    caption="State median county household income (2015 USD)",
)

# Build the map with explicit tiles (more reliable on Streamlit Cloud)
m = folium.Map(location=[39.8283, -98.5795], zoom_start=4, tiles=None, control_scale=True)
folium.TileLayer('Stamen Terrain', control=False).add_to(m)

def style_function(feature):
    name = feature["properties"]["name"]
    a2 = name_to_alpha2.get(name)
    value = med_2015_by_alpha2.get(a2)
    if value is None:
        return {"fillOpacity": 0.2, "weight": 0.5, "color": "gray"}
    return {"fillColor": colormap(value), "fillOpacity": 0.8, "weight": 0.7, "color": "white"}

def on_each_feature(feature, layer):
    name = feature["properties"]["name"]
    a2 = name_to_alpha2.get(name)
    v2015 = med_2015_by_alpha2.get(a2, float("nan"))
    v1989 = med_1989_by_alpha2.get(a2, float("nan"))
    html = f"""
        <div style='font-size:13px'>
            <b>{name}</b><br>
            2015 median county income: ${v2015:,.0f}<br>
            1989 median county income: ${v1989:,.0f}
        </div>
    """
    folium.Tooltip(html, sticky=True).add_to(layer)

# Add states layer
folium.GeoJson(
    data=states_geo,
    name="US States",
    style_function=style_function,
    highlight_function=lambda _: {"weight": 2, "color": "black", "fillOpacity": 0.9},
    on_each_feature=on_each_feature,
).add_to(m)

# Add colorbar
colormap.add_to(m)

# Fit to US bounds (lower-left, upper-right)
m.fit_bounds([[24.396308, -124.848974], [49.384358, -66.885444]])

with left:
    st.subheader("Interactive Map")
    # 1) Try st_folium with explicit width
    try:
        st_folium(m, height=600, width=900, returned_objects=[], key="income_map")
    except Exception:
        # 2) Fallback: raw HTML (very robust)
        html = m.get_root().render()
        st.components.v1.html(html, height=620, scrolling=False)

# ---- Right panel: dropdown + county table ----
with right:
    st.subheader("State Statistics & County Table")
    state_options = sorted(state_medians["state"].tolist())
    default_index = state_options.index("NE") if "NE" in state_options else 0
    chosen_state = st.selectbox("Choose a state (by abbreviation)", state_options, index=default_index)

    df_state = (
        income[income["state"] == chosen_state][["county", "income-1989", "income-2015"]]
        .rename(columns={"county": "County", "income-1989": "Income 1989 (USD)", "income-2015": "Income 2015 (USD)"})
        .sort_values("County")
        .reset_index(drop=True)
    )

    med1989 = df_state["Income 1989 (USD)"].median()
    med2015 = df_state["Income 2015 (USD)"].median()
    median_row = pd.DataFrame(
        {"County": ["— State Median —"], "Income 1989 (USD)": [med1989], "Income 2015 (USD)": [med2015]}
    )
    df_show = pd.concat([df_state, median_row], ignore_index=True)
    st.dataframe(df_show, use_container_width=True)
    st.caption("The color bar reflects the median of county incomes per state.")

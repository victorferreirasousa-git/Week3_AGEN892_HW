import pandas as pd
import requests
import folium
import branca
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="US State Income Map", layout="wide")
st.title("US State Income Map")

@st.cache_data(ttl=86400)
def load_data():
    # County income data
    income = pd.read_csv(
        "https://raw.githubusercontent.com/pri-data/50-states/master/data/income-counties-states-national.csv",
        dtype={"fips": str},
    )
    for col in ["income-2015", "income-1989"]:
        income[col] = pd.to_numeric(income[col], errors="coerce")

    # State polygons (GeoJSON)
    states_geo = requests.get(
        "https://raw.githubusercontent.com/python-visualization/folium-example-data/main/us_states.json"
    ).json()

    # State name -> 2-letter abbreviation
    abbrs = pd.DataFrame(
        requests.get(
            "https://gist.githubusercontent.com/tvpmb/4734703/raw/b54d03154c339ed3047c66fefcece4727dfc931a/US%2520State%2520List"
        ).json()
    ).rename(columns={"abbreviation": "alpha2"})
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

# Color scale based on 2015 MEDIAN income
vals = pd.Series(med_2015_by_alpha2)
vmin, vmax = float(vals.min()), float(vals.max())
colormap = branca.colormap.LinearColormap(
    colors=["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    vmin=vmin,
    vmax=vmax,
    caption="State median county household income (2015 USD)",
)

# Folium map
m = folium.Map(location=[39.8283, -98.5795], zoom_start=4, tiles="cartodbpositron")

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

folium.GeoJson(
    data=states_geo,
    name="US States",
    style_function=style_function,
    highlight_function=lambda _: {"weight": 2, "color": "black", "fillOpacity": 0.9},
    on_each_feature=on_each_feature,
).add_to(m)

colormap.add_to(m)

# Layout: map (left) and stats/table (right)
left, right = st.columns([2, 1], gap="large")

with left:
    st.subheader("Interactive Map")
    st_folium(m, height=600, width=None)

# Right panel: dropdown + county table (2015 & 1989) with state medians
state_options = sorted(state_medians["state"].tolist())
default_index = state_options.index("NE") if "NE" in state_options else 0

with right:
    st.subheader("State Statistics & County Table")
    chosen_state = st.selectbox("Choose a state (by abbreviation)", state_options, index=default_index)

    df_state = (
        income[income["state"] == chosen_state][["county", "income-1989", "income-2015"]]
        .rename(
            columns={
                "county": "County",
                "income-1989": "Income 1989 (USD)",
                "income-2015": "Income 2015 (USD)",
            }
        )
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
    st.caption("The color bar reflects the 2015 median of county incomes per state.")

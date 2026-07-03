import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from garminconnect import Garmin


RUNNING_KEYS = {"running", "treadmill_running", "trail_running", "track_running", "ultra_running"}
# --- STREAMLIT CONFIG ---
st.set_page_config(page_title="Garmin Running Dashboard", layout="wide")
st.title("🏃‍♂️ Garmin Running Dashboard")

# --- SECURE CREDENTIALS INPUT ---
with st.sidebar:
    st.header("Garmin Authentication")
    email = st.text_input("Email", type="default")
    password = st.text_input("Password", type="password")
    history_n = st.number_input("History N",value=100,help="How many historical runs to load")
    fetch_btn = st.button("Fetch My Runs")


# --- DATA FETCHING & CACHING ---
@st.cache_resource(show_spinner="Connecting to Garmin...")
def get_garmin_client(email, password):
    client = Garmin(email, password)
    client.login()
    return client


@st.cache_data(show_spinner="Downloading running history...")
def fetch_running_data(email, password,history_n):
    client = get_garmin_client(email, password)

    # Pulling last 100 activities (adjust limit as needed)
    activities = client.get_activities(0, history_n)

    run_data = []
    for act in activities:
        # Filter purely for running activities
        
        if act["activityType"]["typeKey"] in RUNNING_KEYS:
            # Convert meters to km
            distance_km = round(act["distance"] / 1000, 2)
            duration_sec = act["duration"]

            # Calculate Pace (Min/Km)
            if distance_km > 0:
                total_minutes = duration_sec / 60
                pace_decimal = total_minutes / distance_km
                pace_mins = int(pace_decimal)
                pace_secs = int((pace_decimal - pace_mins) * 60)
                pace_str = f"{pace_mins}:{pace_secs:02d} /km"
            else:
                pace_str = "0:00 /km"

            # Format duration into HH:MM:SS
            time_str = str(datetime.timedelta(seconds=int(duration_sec)))

            # Parse date string
            date_str = act["startTimeLocal"].split(" ")[0]

            # Fetch the geocoded location string (defaults to 'Unknown Location' if blank)
            loc_name = act.get("locationName", "Unknown Location")

            run_data.append(
                {
                    "date": pd.to_datetime(date_str).date(),
                    "distance": distance_km,
                    "time": time_str,
                    "pace": pace_str,
                    "location": loc_name, # <-- ADD THIS LINE
                    "raw_duration": duration_sec,
                }
            )

    return pd.DataFrame(run_data)


# --- DASHBOARD LOGIC ---
if email and password and fetch_btn:
    try:
        df = fetch_running_data(email, password,history_n)

        if df.empty:
            st.warning("Connected! But no running activities were found.")
        else:
            # --- 1. DEDUPLICATE MULTIPLE DAILY RUNS ---
            df_daily = df.groupby("date").agg({
                "distance": "sum",
                "raw_duration": "sum",
                "location": lambda x: " / ".join(filter(None, set(x))) # Combines duplicates smoothly
            }).reset_index()

            def calculate_daily_pace(row):
                if row["distance"] > 0:
                    total_minutes = row["raw_duration"] / 60
                    pace_decimal = total_minutes / row["distance"]
                    return f"{int(pace_decimal)}:{int((pace_decimal - int(pace_decimal)) * 60):02d} /km"
                return "-"

            df_daily["pace"] = df_daily.apply(calculate_daily_pace, axis=1)
            df_daily["time"] = df_daily.apply(lambda r: str(datetime.timedelta(seconds=int(r["raw_duration"]))) if r["raw_duration"] > 0 else "No Run", axis=1)

            # --- 2. CALCULATE 3-YEAR CALENDAR RANGE ---
            current_date = datetime.date.today()
            start_date = datetime.date(current_date.year - 3, 1, 1) # Scales back 3 years cleanly
            end_date = datetime.date(current_date.year, 12, 31)
            date_range = pd.date_range(start_date, end_date)

            # --- 3. WEEKLY TOTALS OVERVIEW ---
            st.header("📅 Recent Weekly Mileage")
            df["week_start"] = pd.to_datetime(df["date"]) - pd.to_timedelta(pd.to_datetime(df["date"]).dt.weekday, unit="D")
            
            # Show the top 5 most recent weeks
            weekly_summary = df.groupby("week_start")["distance"].sum().reset_index()
            weekly_summary = weekly_summary.sort_values("week_start", ascending=False).head(5)

            cols = st.columns(len(weekly_summary))
            for idx, row in enumerate(weekly_summary.itertuples()):
                with cols[idx]:
                    st.metric(
                        label=f"Week of {row.week_start.strftime('%b %d, %Y')}",
                        value=f"{row.distance:.1f} km",
                    )

            # --- 4. 3-YEAR WEEKLY DISTANCE STACKED BAR CHART ---
            st.header("📊 3-Year Weekly Training Volume (Stacked by Run)")
            
            df["week_start"] = pd.to_datetime(df["date"]) - pd.to_timedelta(pd.to_datetime(df["date"]).dt.weekday, unit="D")
            df_stacked = df.sort_values("date").copy()
            df_stacked["run_label"] = pd.to_datetime(df_stacked["date"]).dt.strftime("%a, %b %d")

            import plotly.express as px
            
            # CUSTOM COLOR SCALE: Avoids white by starting at a clear mid-green 
            # and shifting to a deep forest green for long runs.
            vibrant_greens = [
                [0.0, "#a1dbb2"],   # Visible light mint-green for short runs/warmups
                [0.5, "#41ab5d"],   # Vibrant mid-green
                [1.0, "#00441b"]    # Deep, rich forest green for long runs
            ]
            
            fig_bar = px.bar(
                df_stacked,
                x="week_start",
                y="distance",
                color="distance", 
                color_continuous_scale=vibrant_greens,
                labels={"week_start": "Week Commencing", "distance": "Distance (km)"},
                hover_data={
                    "run_label": True,
                    "distance": ":.2f",
                    "time": True,
                    "pace": True,
                    "location": True, # <-- Include location in payload array
                    "week_start": False 
                }
            )
            


            
            fig_bar.update_layout(
                xaxis_title="Timeline",
                yaxis_title="Total Distance (km)",
                height=350,
                margin=dict(t=10, b=10, l=10, r=10),
                barmode="stack", 
                coloraxis_showscale=False, 
                bargap=0.1
            )

            fig_bar.update_traces(
                hovertemplate="<b>%{customdata[0]}</b><br>📍 %{customdata[3]}<br>Distance: %{y} km<br>Time: %{customdata[1]}<br>Pace: %{customdata[2]}<extra></extra>"
            )
            
            st.plotly_chart(fig_bar, width='stretch')
            
            # --- 5. MULTI-YEAR RECURRING HEATMAPS ---
            st.header("🔥 Multi-Year Consistency Grid")
            
            days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            
            for year in range(current_date.year, current_date.year - 4, -1):
                st.subheader(f"🗓️ {year}")
                
                # Build specific target calendar year grid map boundaries
                year_dates = pd.date_range(datetime.date(year, 1, 1), datetime.date(year, 12, 31))
                base_year = pd.DataFrame({"date": year_dates.date})
                
                base_year["weekday"] = pd.to_datetime(base_year["date"]).dt.strftime("%a")
                
                # FIX: Calculate an absolute column week position from day zero of the calendar grid
                # This ensures every single date in the 365-day layout gets a unique sequence integer (0 to 53)
                base_year["grid_week"] = base_year.apply(
                    lambda row: int((row["date"] - datetime.date(year, 1, 1)).days + datetime.date(year, 1, 1).weekday()) // 7, 
                    axis=1
                )

                df_year_grid = pd.merge(base_year, df_daily, on="date", how="left")
                df_year_grid["distance"] = df_year_grid["distance"].fillna(0)
                df_year_grid["time"] = df_year_grid["time"].fillna("No Run")
                df_year_grid["pace"] = df_year_grid["pace"].fillna("-")
                df_year_grid["location"] = df_year_grid["location"].fillna("") # <-- Set fallback empty spaces

                # Pivot cleanly over the guaranteed-unique grid_week coordinate columns
                p_dist = df_year_grid.pivot(index="weekday", columns="grid_week", values="distance").reindex(days_order).fillna(0)
                p_time = df_year_grid.pivot(index="weekday", columns="grid_week", values="time").reindex(days_order).fillna("No Run")
                p_pace = df_year_grid.pivot(index="weekday", columns="grid_week", values="pace").reindex(days_order).fillna("-")
                p_date = df_year_grid.pivot(index="weekday", columns="grid_week", values="date").reindex(days_order)

                # Generate tooltips
                hover_text = []
                for r in range(len(p_dist.index)):
                    row_text = []
                    for c in range(len(p_dist.columns)):
                        d_v = p_date.iloc[r, c]
                        if d_v is None or pd.isna(d_v):
                            row_text.append("")
                        else:
                            loc_v = df_year_grid[df_year_grid["date"] == d_v]["location"].values[0]
                            loc_str = f"<br>📍 {loc_v}" if loc_v else ""
                            
                            row_text.append(
                                f"Date: {d_v}{loc_str}<br>"
                                f"Distance: {p_dist.iloc[r,c]} km<br>"
                                f"Time: {p_time.iloc[r,c]}<br>"
                                f"Pace: {p_pace.iloc[r,c]}"
                            )
                    hover_text.append(row_text)

                # Build heatmap matrix visualization layout
                fig_heat = go.Figure(data=go.Heatmap(
                    z=p_dist.values, 
                    x=list(range(len(p_dist.columns))), # Continuous visual column steps
                    y=p_dist.index,
                    colorscale="Greens", xgap=2, ygap=2, showscale=False,
                    text=hover_text, hoverinfo="text"
                ))
                
                fig_heat.update_layout(
                    xaxis=dict(showticklabels=False), # Hide the raw tracking column coordinate numbers
                    yaxis_autorange="reversed", # Keeps Monday on top, Sunday on bottom
                    height=200, 
                    margin=dict(t=5, b=15, l=10, r=10)
                )
                st.plotly_chart(fig_heat, width='stretch')
                
            
    except Exception as e:
        st.error(f"Failed to load dashboard: {e}")
        st.info("Double check your Garmin credentials or clear security prompt checks.")
else:
    st.info("<- Enter your Garmin credentials on the sidebar to build your dashboard.")
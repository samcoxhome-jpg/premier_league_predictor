import streamlit as st

#Read in parts of my app that i need here
from src.predictor import preload_form_cache
from src.simulator import (
    build_league_state,
    get_team_best_position,
    get_team_worst_position,
    get_predicted_final_table,
    get_match_probabilities,
)
from src.data_loading import load_raw_league_data

#Helper function to decide which suffix to attach to a position, for example 11 goes to 11th
def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

#Sets the page title
st.set_page_config(page_title="Team Details")

#Hides Streamlit's automatic page-list sidebar as we only ever have 1 page in operation so looked redundant 
st.markdown("<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] { display: none; }</style>", unsafe_allow_html=True)

#Get selected team and league from the URL
team_name = st.query_params.get("name")
league_code = st.query_params.get("league")

#If no team is found throw an error
if not team_name or not league_code:
    st.warning("No team selected. Go back to the home page and click a team.")
    st.page_link("app.py", label="Back to title race")
    st.stop()


#Calling from the API each time i need standings is very slow, must make use of caching to remember the standings accross pages 
standings_data, scheduled_data, finished_data = load_raw_league_data(league_code)
current_stats, remaining_fixtures = build_league_state(standings_data, scheduled_data)

#Find the data for the selected team
table = standings_data["standings"][0]["table"]
team_row = next((row for row in table if row["team"]["name"] == team_name), None)

#Safe gaurd, if team has no data recorded then throw an error
if team_row is None:
    st.error(f"Couldn't find {team_name} in the current league.")
    st.page_link("app.py", label="<- Back to title race")
    st.stop()

#Load form data into the cache first so it doesnt get recalculated for every fixture
preload_form_cache(league_code, finished_matches=finished_data["matches"])


#--Header--#
crest_url = team_row["team"]["crest"]
col_badge, col_name = st.columns([1, 4], vertical_alignment="center")
with col_badge:
    st.image(crest_url, width=80)
with col_name:
    st.title(team_row["team"]["name"])


#--Final position posibility stats--#
best_pos = get_team_best_position(team_name, current_stats, remaining_fixtures)
worst_pos = get_team_worst_position(team_name, current_stats, remaining_fixtures)
predicted_table = get_predicted_final_table(current_stats, remaining_fixtures, league_code)
predicted_pos = predicted_table[team_name]

total_teams = len(current_stats)

#Display the 3 cols for the teams range of finishing positions
st.subheader("Final Position Range")
col_best, col_predicted, col_worst = st.columns(3)
col_best.metric("Best Possible", f"{ordinal(best_pos)} / {total_teams}")
col_predicted.metric("Predicted", f"{ordinal(predicted_pos)} / {total_teams}")
col_worst.metric("Worst Possible", f"{ordinal(worst_pos)} / {total_teams}")

#How many matches played out of how many total
played = team_row["playedGames"]

remaining = 0
for fixture in remaining_fixtures:
    if fixture["home"] == team_name or fixture["away"] == team_name:
        remaining += 1

total_num_matches = played + remaining

st.subheader("Season Progress")
st.write(f"Played {played} of {total_num_matches} matches")

#--Remaining fixtures with W/D/L probabilities--#
st.subheader("Remaining Fixtures")

team_fixtures = []
for m in scheduled_data["matches"]:
    if m["homeTeam"]["name"] == team_name or m["awayTeam"]["name"] == team_name:
        team_fixtures.append(m)

if not team_fixtures:
    st.write("No remaining fixtures.")
else:
    for fixture in team_fixtures:
        home = fixture["homeTeam"]["name"]
        away = fixture["awayTeam"]["name"]
        #Postponed games have no confirmed date yet
        date = fixture["utcDate"][:10] if fixture.get("dateConfirmed", True) else "Date TBC"

        is_home = (team_name == home)
        opponent = away if is_home else home
        venue = "(H)" if is_home else "(A)"

        probability_home, probability_draw, probability_away = get_match_probabilities(
            home, away, fixture["utcDate"], league_code
        )
        if is_home:
            probability_win, probability_loss = probability_home, probability_away
        else:
            probability_win, probability_loss = probability_away, probability_home

        st.markdown(f"{date} - vs {opponent} {venue}")
        #Show the 3 probabilties, chop off decimals, just looks nicer
        col_w, col_d, col_l = st.columns(3)
        col_w.metric("Win", f"{probability_win*100:.0f}%")
        col_d.metric("Draw", f"{probability_draw*100:.0f}%")
        col_l.metric("Loss", f"{probability_loss*100:.0f}%")


st.page_link("app.py", label="Back to title race")
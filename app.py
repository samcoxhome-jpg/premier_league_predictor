import streamlit as st
from urllib.parse import quote

from src.simulator import (
    build_league_state,
    has_won_league,
    is_relegated,
    get_locked_continental_tier,
)
from src.predictor import preload_form_cache
from src.data_loading import load_raw_league_data, load_probabilities

import base64
from pathlib import Path

def load_icon(filename):
    path = Path("assets") / filename
    with open(path, "rb") as f:
        data = f.read()
    encoded = base64.b64encode(data).decode("utf-8")
    extension = path.suffix[1:]
    return f"data:image/{extension};base64,{encoded}"


TROPHY = load_icon("trophy.png")
TICK_TIER_1 = load_icon("tick_tier_1.png")
TICK_TIER_2 = load_icon("tick_tier_2.png")
TICK_TIER_3 = load_icon("tick_tier_3.png")
DOWN_ARROW = load_icon("down_arrow.png")

LEAGUE_CODE = "PL"
LEAGUE_NAME = "Premier League"

st.set_page_config(page_title="Premier League Title Predictor")

#Hides Streamlit's automatic page list sidebar, the links still work
st.markdown("<style>[data-testid='stSidebarNav'] { display: none; }</style>", unsafe_allow_html=True)

st.title("Premier League Title Predictor")

if st.button("Update", help="Fetch the latest standings and recalculate odds now, instead of waiting for the daily refresh"):
    load_raw_league_data.clear()
    load_probabilities.clear()
    st.rerun()

#Description of the app here maybe!!!

with st.expander("What do the icons mean?"):
    key_html = f"""
    <table style="width: 100%; border-collapse: collapse;">
      <tr>
        <td style="padding: 6px; width: 40px;">
          <img src="{TROPHY}" style="height: 22px; vertical-align: middle;">
        </td>
        <td style="padding: 6px;">League winners - mathematically uncatchable</td>
      </tr>
      <tr>
        <td style="padding: 6px;">
          <img src="{TICK_TIER_1}" style="height: 22px; vertical-align: middle;">
        </td>
        <td style="padding: 6px;">Guaranteed top-tier continental qualification (Champions League)</td>
      </tr>
      <tr>
        <td style="padding: 6px;">
          <img src="{TICK_TIER_2}" style="height: 22px; vertical-align: middle;">
        </td>
        <td style="padding: 6px;">Guaranteed second-tier continental qualification (Europa League)</td>
      </tr>
      <tr>
        <td style="padding: 6px;">
          <img src="{TICK_TIER_3}" style="height: 22px; vertical-align: middle;">
        </td>
        <td style="padding: 6px;">Guaranteed third-tier continental qualification (Conference League)</td>
      </tr>
      <tr>
        <td style="padding: 6px;">
          <img src="{DOWN_ARROW}" style="height: 22px; vertical-align: middle;">
        </td>
        <td style="padding: 6px;">Relegated - mathematically can't escape the bottom 3</td>
      </tr>
    </table>
    """
    st.markdown(key_html, unsafe_allow_html=True)


#Helper function for common formatting
def format_probability(prob):
    if prob == 0:
        return "0%"
    #Anything under 0.05% would show as 0.0% which looks impossible, so show <0.1% instead
    if prob < 0.0005:
        return "<0.1%"
    return f"{prob * 100:.1f}%"


#Get the data (cached), form cache still needs loading every time
standings_data, scheduled_data, finished_data = load_raw_league_data(LEAGUE_CODE)
current_stats, remaining_fixtures = build_league_state(standings_data, scheduled_data)
preload_form_cache(LEAGUE_CODE, finished_matches=finished_data["matches"])

if not remaining_fixtures:
    st.info(
        "Fixtures for this season haven't been published yet. "
        "Check back once the schedule is announced."
    )
    st.stop()

#Results is a 1D sorted list of (team:title_prob) pairs
results = load_probabilities(current_stats, remaining_fixtures, LEAGUE_CODE)

rows_html = ""

#Take each pair
for team, prob in results:

    #Put the team name into the URL's format
    encoded_name = quote(team)

    #Turn the value into a more intuative format that we can display
    prob_display = format_probability(prob)

    #Decide which icon and background colour to apply (if any)
    icon_html = ""
    row_style = ""

    if has_won_league(team, current_stats, remaining_fixtures):
        icon_html = f'<img src="{TROPHY}" style="height: 18px; vertical-align: middle; margin-right: 6px;">'
        row_style = 'style="background-color: #8a6a00;"'
    elif is_relegated(team, LEAGUE_CODE, current_stats, remaining_fixtures):
        icon_html = f'<img src="{DOWN_ARROW}" style="height: 18px; vertical-align: middle; margin-right: 6px;">'
        row_style = 'style="background-color: #5a1a1a;"'
    else:
        tier = get_locked_continental_tier(team, LEAGUE_CODE, current_stats, remaining_fixtures)
        if tier == 1:
            icon_html = f'<img src="{TICK_TIER_1}" style="height: 18px; vertical-align: middle; margin-right: 6px;">'
            row_style = 'style="background-color: #422bd6;"'   # dark blue
        elif tier == 2:
            icon_html = f'<img src="{TICK_TIER_2}" style="height: 18px; vertical-align: middle; margin-right: 6px;">'
            row_style = 'style="background-color: #e0732b;"'   # orange
        elif tier == 3:
            icon_html = f'<img src="{TICK_TIER_3}" style="height: 18px; vertical-align: middle; margin-right: 6px;">'
            row_style = 'style="background-color: #64b360;"'   # green

    #Make the unique link for each team, including any status icon
    team_link = f'<a href="/team?name={encoded_name}&league={LEAGUE_CODE}" target="_self">{icon_html}{team}</a>'

    rows_html += f"<tr {row_style}><td>{team_link}</td><td>{prob_display}</td></tr>"

table_html = f"""
<table style="width: 100%; border-collapse: collapse;">
  <thead>
    <tr>
      <th style="text-align: left; padding: 8px;">Team</th>
      <th style="text-align: left; padding: 8px;">Win Probability</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
"""

st.subheader(LEAGUE_NAME)
st.markdown(table_html, unsafe_allow_html=True)
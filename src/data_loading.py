import streamlit as st

from src.simulator import fetch_raw_league_data, get_probabilities


#Cache the data for a day, the Update button clears it to get new results
CACHE_TTL_SECONDS = 60 * 60 * 24


@st.cache_data(ttl=CACHE_TTL_SECONDS, persist="disk")
def load_raw_league_data(league_code):
    return fetch_raw_league_data(league_code)


@st.cache_data(ttl=CACHE_TTL_SECONDS, persist="disk")
def load_probabilities(current_stats, remaining_fixtures, league_code):
    return get_probabilities(current_stats, remaining_fixtures, league_code)

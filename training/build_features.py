import pandas as pd
from pathlib import Path
import json

#Setup file paths
DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_FILE = DATA_DIR / "prem_historic_data.csv"
OUTPUT_FILE = DATA_DIR / "training_rows.csv"

SEASON_AVERAGES_FILE = DATA_DIR / "season_averages.json"
PROMOTED_TEAM_FALLBACK = 1.0

FORM_WINDOW = 5
MAX_FORM_AGE_DAYS = 60

#Load the raw match data
def load_raw_data():
    df = pd.read_csv(INPUT_FILE)
    df["MatchDate"] = pd.to_datetime(df["MatchDate"], format="mixed", dayfirst=True)
    df = df.sort_values("MatchDate").reset_index(drop=True)
    return df

#Get a team's previous matches before a given date
def get_previous_matches(team, before_date, df):
    is_team = (df["HomeTeam"] == team) | (df["AwayTeam"] == team)
    is_before = df["MatchDate"] < before_date
    return df[is_team & is_before].sort_values("MatchDate").tail(FORM_WINDOW)

#Calculate form stats for a team going into a match
def compute_team_form(team, before_date, current_season, df, season_averages):
    #Get the last 5 matches
    previous = get_previous_matches(team, before_date, df)

    #Need at least 5 matches
    if len(previous) < FORM_WINDOW:
        return None

    #Make sure form is recent enough
    days_since_last = (before_date - previous["MatchDate"].max()).days
    if days_since_last > MAX_FORM_AGE_DAYS:
        return None

    #Calculate rest days
    rest_days = (before_date - previous["MatchDate"].max()).days

    goals_for = 0
    goals_against = 0
    points = 0
    quality_points = 0.0

    #Go through each previous match
    for index, match in previous.iterrows():
        if match["HomeTeam"] == team:
            opponent = match["AwayTeam"]
            goals_for += match["FullTimeHomeGoals"]
            goals_against += match["FullTimeAwayGoals"]
            if match["FullTimeResult"] == "H":
                match_points = 3
            elif match["FullTimeResult"] == "D":
                match_points = 1
            else:
                match_points = 0
        else:
            opponent = match["HomeTeam"]
            goals_for += match["FullTimeAwayGoals"]
            goals_against += match["FullTimeHomeGoals"]
            if match["FullTimeResult"] == "A":
                match_points = 3
            elif match["FullTimeResult"] == "D":
                match_points = 1
            else:
                match_points = 0

        points += match_points
        #Weight points by opponent strength
        opponent_strength = get_last_season_ppg(opponent, current_season, season_averages)
        quality_points += match_points * opponent_strength

    #Return average stats
    return {
        "form_gf": goals_for / FORM_WINDOW,
        "form_ga": goals_against / FORM_WINDOW,
        "form_pts": points / FORM_WINDOW,
        "form_quality_pts": quality_points / FORM_WINDOW,
        "rest_days": rest_days,
    }

#How many seasons to blend and decay factor
N_BLEND_SEASONS = 3
DECAY = 0.7

#Get the previous season string
def get_previous_season(current_season):
    start_year = int(current_season[:4])
    previous_start = start_year - 1
    return f"{previous_start}/{str(previous_start + 1)[-2:]}"

#Get a team's PPG from past seasons (weighted blend)
def get_last_season_ppg(team, current_season, season_averages, n_seasons=N_BLEND_SEASONS, decay=DECAY):
    season = current_season
    weighted_sum = 0.0
    total_weight = 0.0

    #Look at multiple past seasons
    for k in range(n_seasons):
        season = get_previous_season(season)
        if season in season_averages and team in season_averages[season]:
            weight = decay ** k
            weighted_sum += weight * season_averages[season][team]
            total_weight += weight

    #If no data, use fallback
    if total_weight == 0:
        return PROMOTED_TEAM_FALLBACK

    return weighted_sum / total_weight

#Default PPG for teams with no current season games
DEFAULT_SEASON_PPG = 1.4

#Calculate PPG across all matches this season so far
def compute_season_ppg_so_far(team, before_date, current_season, df):
    #Find all matches this team has played this season before this date
    is_team = (df["HomeTeam"] == team) | (df["AwayTeam"] == team)
    is_this_season = df["Season"] == current_season
    is_before = df["MatchDate"] < before_date
    played = df[is_team & is_this_season & is_before]

    #If no games played yet, use default
    if len(played) == 0:
        return DEFAULT_SEASON_PPG

    #Calculate points
    points = 0
    for _, match in played.iterrows():
        if match["HomeTeam"] == team:
            if match["FullTimeResult"] == "H":
                points += 3
            elif match["FullTimeResult"] == "D":
                points += 1
        else:
            if match["FullTimeResult"] == "A":
                points += 3
            elif match["FullTimeResult"] == "D":
                points += 1

    return points / len(played)

#Build the training dataset
def build_training_rows(df, season_averages):
    rows = []

    #Go through each match in the raw data
    for index, match in df.iterrows():
        home_team = match["HomeTeam"]
        away_team = match["AwayTeam"]
        match_date = match["MatchDate"]
        season = match["Season"]

        #Get form for both teams
        home_form = compute_team_form(home_team, match_date, season, df, season_averages)
        away_form = compute_team_form(away_team, match_date, season, df, season_averages)

        #Skip if we don't have enough form data
        if home_form is None or away_form is None:
            continue

        #Get other features
        home_last_season_ppg = get_last_season_ppg(home_team, season, season_averages)
        away_last_season_ppg = get_last_season_ppg(away_team, season, season_averages)
        home_season_ppg_so_far = compute_season_ppg_so_far(home_team, match_date, season, df)
        away_season_ppg_so_far = compute_season_ppg_so_far(away_team, match_date, season, df)

        #Build the training row
        row = {
            "match_date": match_date,
            "home_team": home_team,
            "away_team": away_team,
            "home_form_gf": home_form["form_gf"],
            "home_form_ga": home_form["form_ga"],
            "home_form_pts": home_form["form_pts"],
            "home_form_quality_pts": home_form["form_quality_pts"],
            "home_rest_days": home_form["rest_days"],
            "home_season_ppg_so_far": home_season_ppg_so_far,
            "away_form_gf": away_form["form_gf"],
            "away_form_ga": away_form["form_ga"],
            "away_form_pts": away_form["form_pts"],
            "away_form_quality_pts": away_form["form_quality_pts"],
            "away_rest_days": away_form["rest_days"],
            "away_season_ppg_so_far": away_season_ppg_so_far,
            "home_last_season_ppg": home_last_season_ppg,
            "away_last_season_ppg": away_last_season_ppg,
            "home_goals": match["FullTimeHomeGoals"],
            "away_goals": match["FullTimeAwayGoals"],
        }

        rows.append(row)

        #Progress update
        if index % 200 == 0:
            print(f"  Processed {index} / {len(df)} matches...")

    return pd.DataFrame(rows)

#Main function
def main():
    print("Loading data...")
    df = load_raw_data()
    print(f"Loaded {len(df)} matches from {df['MatchDate'].min().date()} to {df['MatchDate'].max().date()}")

    #Load season averages
    with open(SEASON_AVERAGES_FILE, "r") as f:
        season_averages = json.load(f)

    print("\nBuilding training rows...")
    training_df = build_training_rows(df, season_averages)

    #Save the results
    training_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved {len(training_df)} training rows to {OUTPUT_FILE}")
    print(f"Dropped {len(df) - len(training_df)} matches due to insufficient form data")

    print("\nFirst few rows:")
    print(training_df.head())

    print("\nSummary stats:")
    print(training_df.describe())

if __name__ == "__main__":
    main()
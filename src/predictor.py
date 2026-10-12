import pickle
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

from src.api_client import get_matches


#Load paths and config
MODELS_DIR = Path(__file__).parent.parent / "models"
DATA_DIR = Path(__file__).parent.parent / "data"
BASELINES_FILE = DATA_DIR / "season_averages.json"

FORM_WINDOW = 5
PROMOTED_TEAM_FALLBACK = 1.0

#Load season averages data
with open(BASELINES_FILE, "r") as f:
    _season_averages = json.load(f)

#Get the most recent season from the data
LAST_COMPLETED_SEASON = max(_season_averages.keys())

#These are the columns our model expects
FEATURE_COLUMNS = [
    "home_form_gf",
    "home_form_ga",
    "home_form_pts",
    "home_form_quality_pts",
    "away_form_gf",
    "away_form_ga",
    "away_form_pts",
    "away_form_quality_pts",
    "home_last_season_ppg",
    "away_last_season_ppg",
    "home_rest_days",
    "away_rest_days",
    "home_season_ppg_so_far",
    "away_season_ppg_so_far",
]

#Load the trained models
with open(MODELS_DIR / "home_goals_model.pkl", "rb") as f:
    home_models = pickle.load(f)
    home_model = home_models[0]  #Main model is first

with open(MODELS_DIR / "away_goals_model.pkl", "rb") as f:
    away_models = pickle.load(f)
    away_model = away_models[0]  #Main model is first

#How many extra bootstrap models we have
N_BOOTSTRAP_MODELS = len(home_models) - 1

#Map API team names to our training names
#Only need the ones that are different, the rest already match
TEAM_NAME_MAP = {
    "Man Utd": "Man United",
    "Spurs": "Tottenham",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Leicester City": "Leicester",
    "Sheffield Utd": "Sheffield United",
    "Norwich City": "Norwich",
    "Stoke City": "Stoke",
    "Swansea City": "Swansea",
    "Cardiff City": "Cardiff",
    "Luton Town": "Luton",
    "Birmingham City": "Birmingham",
    "Huddersfield Town": "Huddersfield",
}

#Caches to avoid recalculating stuff
form_cache = {}
season_ppg_cache = {}
DEFAULT_SEASON_PPG = 1.4

#Calculate how many points per game a team has this season
def get_season_ppg(team_name, all_matches):
    points = 0
    games_played = 0
    
    #Look at every match
    for match in all_matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        
        #Skip if this team isn't playing
        if home_team != team_name and away_team != team_name:
            continue
            
        games_played = games_played + 1
        home_goals = match["score"]["fullTime"]["home"]
        away_goals = match["score"]["fullTime"]["away"]
        
        #Work out if team won, drew or lost
        if home_team == team_name:
            #Team is at home
            if home_goals > away_goals:
                points = points + 3
            elif home_goals == away_goals:
                points = points + 1
        else:
            #Team is away
            if away_goals > home_goals:
                points = points + 3
            elif away_goals == home_goals:
                points = points + 1
    
    #If no games played, use default
    if games_played == 0:
        return DEFAULT_SEASON_PPG
        
    return points / games_played

#Get a team's recent form from last 5 games
def get_recent_form(team_name, all_matches):
    #Find all matches this team played
    team_matches = []
    for match in all_matches:
        if match["homeTeam"]["name"] == team_name or match["awayTeam"]["name"] == team_name:
            team_matches.append(match)
    
    #Sort by date (oldest first)
    team_matches.sort(key=lambda m: m["utcDate"])
    
    #Get last 5 matches
    last_few_matches = team_matches[-FORM_WINDOW:]
    
    #Not enough matches yet
    if len(last_few_matches) < FORM_WINDOW:
        return None
    
    goals_scored = 0
    goals_conceded = 0
    total_points = 0
    quality_points = 0.0
    
    #Go through each recent match
    for match in last_few_matches:
        home_team = match["homeTeam"]["name"]
        away_team = match["awayTeam"]["name"]
        home_goals = match["score"]["fullTime"]["home"]
        away_goals = match["score"]["fullTime"]["away"]
        
        #Figure out if team won, drew or lost
        if home_team == team_name:
            #Team is at home
            opponent = away_team
            goals_scored = goals_scored + home_goals
            goals_conceded = goals_conceded + away_goals
            
            if home_goals > away_goals:
                match_points = 3
            elif home_goals == away_goals:
                match_points = 1
            else:
                match_points = 0
        else:
            #Team is away
            opponent = home_team
            goals_scored = goals_scored + away_goals
            goals_conceded = goals_conceded + home_goals
            
            if away_goals > home_goals:
                match_points = 3
            elif away_goals == home_goals:
                match_points = 1
            else:
                match_points = 0
        
        total_points = total_points + match_points
        
        #Weight points by opponent strength
        opponent_strength = get_prior_season_ppg(opponent)
        quality_points = quality_points + (match_points * opponent_strength)
    
    #Return average stats per game
    return {
        "form_gf": goals_scored / FORM_WINDOW,
        "form_ga": goals_conceded / FORM_WINDOW,
        "form_pts": total_points / FORM_WINDOW,
        "form_quality_pts": quality_points / FORM_WINDOW,
        "last_match_date": last_few_matches[-1]["utcDate"],
    }

#Load all team data into caches
def preload_form_cache(league_code="PL", finished_matches=None):
    #Get matches if not provided
    if finished_matches is None:
        finished_matches = get_matches(league_code, status="FINISHED")["matches"]
    
    #Find all unique teams
    teams = set()
    for match in finished_matches:
        teams.add(match["homeTeam"]["name"])
        teams.add(match["awayTeam"]["name"])
    
    #Clear old caches
    form_cache.clear()
    season_ppg_cache.clear()
    
    #Calculate stats for each team
    for team in teams:
        form_cache[team] = get_recent_form(team, finished_matches)
        season_ppg_cache[team] = get_season_ppg(team, finished_matches)

#Maximum rest days we allow
MAX_REST_DAYS = 60
DEFAULT_REST_DAYS = 7

#Convert date string to datetime object
def convert_to_datetime(date_string):
    return datetime.fromisoformat(date_string.replace("Z", "+00:00"))

#Calculate rest days for each fixture
def calculate_rest_days(fixtures):
    #Track when each team last played
    last_match_day = {}
    
    #Start with their last actual match
    for team, form in form_cache.items():
        if form is not None:
            last_match_day[team] = convert_to_datetime(form["last_match_date"])
    
    #Sort fixtures by date
    sorted_fixtures = sorted(fixtures, key=lambda f: f[2])
    
    #Store results
    rest_days_result = {}
    
    #Go through each fixture in order
    for home, away, date_str in sorted_fixtures:
        match_date = convert_to_datetime(date_str)
        
        #Calculate home rest days
        if home in last_match_day:
            days_since = (match_date - last_match_day[home]).days
            home_rest = min(days_since, MAX_REST_DAYS)
        else:
            home_rest = DEFAULT_REST_DAYS
        
        #Calculate away rest days
        if away in last_match_day:
            days_since = (match_date - last_match_day[away]).days
            away_rest = min(days_since, MAX_REST_DAYS)
        else:
            away_rest = DEFAULT_REST_DAYS
        
        #Store result
        rest_days_result[(home, away)] = (home_rest, away_rest)
        
        #Update last match day for these teams
        last_match_day[home] = match_date
        last_match_day[away] = match_date
    
    return rest_days_result

#How many past seasons to look at
BLEND_SEASONS = 3
BLEND_DECAY = 0.7

#Get a season string from N years ago
def get_older_season(current_season, years_ago):
    start_year = int(current_season[:4])
    new_start = start_year - years_ago
    return f"{new_start}/{str(new_start + 1)[-2:]}"

#Get a team's PPG from last season(s)
def get_prior_season_ppg(api_team_name):
    #Convert API name to training name
    if api_team_name in TEAM_NAME_MAP:
        training_name = TEAM_NAME_MAP[api_team_name]
    else:
        training_name = api_team_name
    
    weighted_sum = 0.0
    total_weight = 0.0
    
    #Look at multiple past seasons
    for i in range(BLEND_SEASONS):
        season = get_older_season(LAST_COMPLETED_SEASON, i)
        
        #Check if we have data for this team in this season
        if season in _season_averages:
            if training_name in _season_averages[season]:
                weight = BLEND_DECAY ** i
                weighted_sum = weighted_sum + (weight * _season_averages[season][training_name])
                total_weight = total_weight + weight
    
    #If no data found, use fallback
    if total_weight == 0:
        return PROMOTED_TEAM_FALLBACK
    
    return weighted_sum / total_weight

#Build feature array for a single match
def make_feature_row(home, away, home_rest, away_rest):
    #Get form data
    home_form = form_cache.get(home)
    away_form = form_cache.get(away)
    
    #Get prior season strength
    home_strength = get_prior_season_ppg(home)
    away_strength = get_prior_season_ppg(away)
    
    #If no form data, use defaults
    if home_form is None:
        home_form = {
            "form_gf": 1.4, 
            "form_ga": 1.4, 
            "form_pts": 1.4, 
            "form_quality_pts": 1.4
        }
    
    if away_form is None:
        away_form = {
            "form_gf": 1.4, 
            "form_ga": 1.4, 
            "form_pts": 1.4, 
            "form_quality_pts": 1.4
        }
    
    #Get season PPG so far
    home_season_ppg = season_ppg_cache.get(home, DEFAULT_SEASON_PPG)
    away_season_ppg = season_ppg_cache.get(away, DEFAULT_SEASON_PPG)
    
    #Build the feature array
    features = [
        home_form["form_gf"],
        home_form["form_ga"],
        home_form["form_pts"],
        home_form["form_quality_pts"],
        away_form["form_gf"],
        away_form["form_ga"],
        away_form["form_pts"],
        away_form["form_quality_pts"],
        home_strength,
        away_strength,
        home_rest,
        away_rest,
        home_season_ppg,
        away_season_ppg,
    ]
    
    return features

#Simulate a random score from expected goals
def sample_scoreline(home_expected, away_expected):
    home_goals = np.random.poisson(home_expected)
    away_goals = np.random.poisson(away_expected)
    return (home_goals, away_goals)

#Get expected goals for multiple fixtures
def compute_expected_goals(fixture_list):
    if not fixture_list:
        return {}
    
    #Get rest days for all fixtures
    rest_days = calculate_rest_days(fixture_list)
    
    #Build features for each fixture
    all_features = []
    for home, away, date in fixture_list:
        home_rest, away_rest = rest_days[(home, away)]
        row = make_feature_row(home, away, home_rest, away_rest)
        all_features.append(row)
    
    #Convert to DataFrame
    features_df = pd.DataFrame(all_features, columns=FEATURE_COLUMNS)
    
    #Get predictions from all models
    home_predictions = []
    for model in home_models:
        home_predictions.append(model.predict(features_df))
    
    away_predictions = []
    for model in away_models:
        away_predictions.append(model.predict(features_df))
    
    #Format results
    results = {}
    for i, (home, away, date) in enumerate(fixture_list):
        fixture_expected = []
        for m in range(len(home_models)):
            expected_home = float(home_predictions[m][i])
            expected_away = float(away_predictions[m][i])
            fixture_expected.append((expected_home, expected_away))
        results[(home, away)] = fixture_expected
    
    return results

#Predict a single match
def predict_match(home_team, away_team, match_date=None):
    #Get rest days
    if match_date is not None:
        rest_days = calculate_rest_days([(home_team, away_team, match_date)])
        home_rest, away_rest = rest_days[(home_team, away_team)]
    else:
        home_rest = DEFAULT_REST_DAYS
        away_rest = DEFAULT_REST_DAYS
    
    #Make feature row
    row = make_feature_row(home_team, away_team, home_rest, away_rest)
    features = pd.DataFrame([row], columns=FEATURE_COLUMNS)
    
    #Predict
    expected_home = home_model.predict(features)[0]
    expected_away = away_model.predict(features)[0]
    
    #Simulate score
    return sample_scoreline(expected_home, expected_away)
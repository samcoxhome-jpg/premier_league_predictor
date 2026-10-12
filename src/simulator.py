import random
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from src.api_client import get_standings, get_matches
from src.predictor import predict_match, preload_form_cache, compute_expected_goals, sample_scoreline


#How the continental competition slots are given based on league finish position
LEAGUE_CONTINENTAL_SLOTS = {
    "PL":  {"tier_1": 5, "tier_2": 2, "tier_3": 1},  # England
    #REDUNDANT AS ONLY DOING PREMIER LEAUGE NOW
    "PD":  {"tier_1": 5, "tier_2": 1, "tier_3": 1},  # Spain
    "SA":  {"tier_1": 4, "tier_2": 2, "tier_3": 1},  # Italy
    "BL1": {"tier_1": 4, "tier_2": 2, "tier_3": 1},  # Germany
    "FL1": {"tier_1": 3, "tier_2": 1, "tier_3": 1},  # France
    "DED": {"tier_1": 2, "tier_2": 1, "tier_3": 0},  # Netherlands
    "BSA": {"tier_1": 6, "tier_2": 6, "tier_3": 0},  # Brazil
    "PPL": {"tier_1": 2, "tier_2": 1, "tier_3": 1},  # Portugal
}

#How many of the bottom teams each leauge relegates 
LEAGUE_RELEGATION_COUNT = {
    "PL":  3,
    #REDUNDANT AS ONLY DOING PREMIER LEAUGE NOW
    "PD":  3,
    "SA":  3,
    "BL1": 3,
    "FL1": 3,
    "DED": 3,
    "PPL": 2,
    "BSA": 4,
}

def fetch_raw_league_data(league_code):
    with ThreadPoolExecutor(max_workers=3) as executor:
        standings_future = executor.submit(get_standings, league_code)
        scheduled_future = executor.submit(get_matches, league_code, "SCHEDULED")
        finished_future = executor.submit(get_matches, league_code, "FINISHED")

        standings_data = standings_future.result()
        scheduled_data = scheduled_future.result()
        finished_data = finished_future.result()

    return standings_data, scheduled_data, finished_data


def build_league_state(standings_data, scheduled_data):
    table = standings_data["standings"][0]["table"]
    current_stats = {
        row["team"]["name"]: {
            "points": row["points"],
            "gf": row["goalsFor"],
            "ga": row["goalsAgainst"],
        }
        for row in table
    }
    remaining_fixtures = [
        {"home": m["homeTeam"]["name"], "away": m["awayTeam"]["name"], "date": m["utcDate"]}
        for m in scheduled_data["matches"]
    ]
    return current_stats, remaining_fixtures


def get_league_state(league_code):
    standings_data, scheduled_data, finished_data = fetch_raw_league_data(league_code)
    current_stats, remaining_fixtures = build_league_state(standings_data, scheduled_data)
    preload_form_cache(league_code, finished_matches=finished_data["matches"])
    return current_stats, remaining_fixtures

def get_remaining_count(team, remaining_fixtures):
    count = 0
    for fixture in remaining_fixtures:
        if fixture["home"] == team or fixture["away"] == team:
            count += 1
    return count


def max_possible_points(team, current_stats, remaining_fixtures):
    current = current_stats[team]["points"]
    remaining = get_remaining_count(team, remaining_fixtures)
    return current + 3 * remaining


def min_possible_points(team, current_stats):
    return current_stats[team]["points"]

def get_locked_continental_tier(team, league_code, current_stats, remaining_fixtures):
    slots = LEAGUE_CONTINENTAL_SLOTS.get(league_code)
    if slots is None:
        return None

    our_worst_finish = min_possible_points(team, current_stats)

    teams_that_could_finish_above_us = 0
    for other_team in current_stats:
        if other_team == team:
            continue
        their_best_finish = max_possible_points(other_team, current_stats, remaining_fixtures)
        if their_best_finish > our_worst_finish:
            teams_that_could_finish_above_us += 1

    guaranteed_position = teams_that_could_finish_above_us + 1

    tier_1_cutoff = slots["tier_1"]
    tier_2_cutoff = tier_1_cutoff + slots["tier_2"]
    tier_3_cutoff = tier_2_cutoff + slots["tier_3"]

    if slots["tier_1"] > 0 and guaranteed_position <= tier_1_cutoff:
        return 1
    if slots["tier_2"] > 0 and guaranteed_position <= tier_2_cutoff:
        return 2
    if slots["tier_3"] > 0 and guaranteed_position <= tier_3_cutoff:
        return 3
    return None

def simulate_match(home, away, expected_goals_by_fixture, home_model_index, away_model_index):
    expected_home = expected_goals_by_fixture[(home, away)][home_model_index][0]
    expected_away = expected_goals_by_fixture[(home, away)][away_model_index][1]
    home_goals, away_goals = sample_scoreline(expected_home, expected_away)
    if home_goals > away_goals:
        return home_goals, away_goals, 3, 0   # home win
    if home_goals < away_goals:
        return home_goals, away_goals, 0, 3   # away win
    return home_goals, away_goals, 1, 1       # draw

def has_won_league(team, current_stats, remaining_fixtures):
    our_lowest_finish = min_possible_points(team, current_stats)

    for other_team in current_stats:
        if other_team == team:
            continue

        their_best_finish = max_possible_points(other_team, current_stats, remaining_fixtures)
        if their_best_finish >= our_lowest_finish:
            return False

    return True

def is_relegated(team, league_code, current_stats, remaining_fixtures):
    bottom_n = LEAGUE_RELEGATION_COUNT.get(league_code)
    if bottom_n is None:
        return False

    our_best_finish = max_possible_points(team, current_stats, remaining_fixtures)

    guaranteed_to_finish_above_us = 0
    for other_team in current_stats:
        if other_team == team:
            continue
        their_worst_finish = min_possible_points(other_team, current_stats)
        if their_worst_finish > our_best_finish:
            guaranteed_to_finish_above_us += 1

    total_teams = len(current_stats)
    safe_positions = total_teams - bottom_n

    return guaranteed_to_finish_above_us >= safe_positions

def has_qualified_for_continental(team, league_code, current_stats, remaining_fixtures):
    slots = LEAGUE_CONTINENTAL_SLOTS.get(league_code)
    if slots is None:
        return False  # league we don't have data for

    total_slots = slots["tier_1"] + slots["tier_2"] + slots["tier_3"]
    if total_slots == 0:
        return False

    our_worst_finish = min_possible_points(team, current_stats)

    teams_that_could_finish_above_us = 0
    for other_team in current_stats:
        if other_team == team:
            continue

        their_best_finish = max_possible_points(other_team, current_stats, remaining_fixtures)
        if their_best_finish > our_worst_finish:
            teams_that_could_finish_above_us += 1

    return teams_that_could_finish_above_us < total_slots

#How many games before a team gets switched to a different bootstrap model
#Means a teams strength can change during the season (injuries, form, new manager etc)
GAMES_PER_DRIFT = 8


def simulate_season(current_stats, remaining_fixtures, expected_goals_by_fixture):
    #Fixtures need to be in date order for the model switching to make sense
    stats = {team: dict(s) for team, s in current_stats.items()}

    any_fixture = next(iter(expected_goals_by_fixture.values()))
    n_models = len(any_fixture)

    #Each team gets its own model, injuries and form only affect one team not the whole league
    team_model_index = {}
    team_games_played = {}

    def get_team_model_index(team):
        if team not in team_model_index:
            team_model_index[team] = random.randrange(n_models)
            team_games_played[team] = 0
            return team_model_index[team]

        team_games_played[team] += 1
        if team_games_played[team] % GAMES_PER_DRIFT == 0:
            team_model_index[team] = random.randrange(n_models)
        return team_model_index[team]

    for fixture in remaining_fixtures:
        home, away = fixture["home"], fixture["away"]
        home_model_index = get_team_model_index(home)
        away_model_index = get_team_model_index(away)
        home_goals, away_goals, home_pts, away_pts = simulate_match(
            home, away, expected_goals_by_fixture, home_model_index, away_model_index
        )
        
        stats[home]["points"] += home_pts
        stats[home]["gf"] += home_goals
        stats[home]["ga"] += away_goals
        
        stats[away]["points"] += away_pts
        stats[away]["gf"] += away_goals
        stats[away]["ga"] += home_goals
    
    return sorted(
        stats.keys(),
        key=lambda t: (stats[t]["points"], stats[t]["gf"] - stats[t]["ga"], stats[t]["gf"]),
        reverse=True
    )


def run_simulations(current_points, remaining_fixtures, expected_goals_by_fixture, n=5000):
    champion_counts = Counter()

    for i in range(n):
        final_table = simulate_season(current_points, remaining_fixtures, expected_goals_by_fixture)
        champion = final_table[0]
        champion_counts[champion] += 1

    #Work out what fraction of the simulations each team won the league in
    probabilities = {}
    for team, count in champion_counts.items():
        probabilities[team] = count / n

    return probabilities


def get_probabilities(current_stats, remaining_fixtures, league_code, n=5000):
    #form_cache needs to be loaded before calling this

    #Work out expected goals once per fixture here so the model isnt rerun in every simulation
    fixture_pairs = [(f["home"], f["away"], f["date"]) for f in remaining_fixtures]
    expected_goals_by_fixture = compute_expected_goals(fixture_pairs)

    probabilities = run_simulations(current_stats, remaining_fixtures, expected_goals_by_fixture, n=n)

    leader_points = max(stats["points"] for stats in current_stats.values())

    BELOW_DETECTABLE = 0.00005
    for team, stats in current_stats.items():
        if probabilities.get(team, 0) > 0:
            continue

        remaining_matches = sum(
            1 for f in remaining_fixtures
            if f["home"] == team or f["away"] == team
        )
        max_possible_points = stats["points"] + 3 * remaining_matches

        if max_possible_points >= leader_points:
            probabilities[team] = BELOW_DETECTABLE
        else:
            probabilities[team] = 0.0

    probability_list = list(probabilities.items())
    sorted_list = sorted(probability_list, key=lambda x: x[1], reverse=True)
    return sorted_list

def get_team_best_position(team, current_stats, remaining_fixtures):
    final_points = {}
    for t, stats in current_stats.items():
        if t == team:
            remaining = sum(1 for f in remaining_fixtures if f["home"] == t or f["away"] == t)
            final_points[t] = stats["points"] + 3 * remaining
        else:
            final_points[t] = stats["points"]

    sorted_teams = sorted(final_points.items(), key=lambda x: x[1], reverse=True)
    for position, (t, _) in enumerate(sorted_teams, start=1):
        if t == team:
            return position


def get_team_worst_position(team, current_stats, remaining_fixtures):
    final_points = {}
    for t, stats in current_stats.items():
        if t == team:
            final_points[t] = stats["points"]
        else:
            remaining = sum(1 for f in remaining_fixtures if f["home"] == t or f["away"] == t)
            final_points[t] = stats["points"] + 3 * remaining

    sorted_teams = sorted(final_points.items(), key=lambda x: x[1], reverse=True)
    for position, (t, _) in enumerate(sorted_teams, start=1):
        if t == team:
            return position


def get_team_average_position(team, current_stats, remaining_fixtures, league_code, n=1000):
    #form_cache needs to be loaded before calling this
    fixture_pairs = [(f["home"], f["away"], f["date"]) for f in remaining_fixtures]
    expected_goals_by_fixture = compute_expected_goals(fixture_pairs)

    total = 0
    for i in range(n):
        final_table = simulate_season(current_stats, remaining_fixtures, expected_goals_by_fixture)
        total += final_table.index(team) + 1
    return total / n


def get_predicted_final_table(current_stats, remaining_fixtures, league_code, n=1000):
    #Gives each team a predicted position from 1 to 20
    #Ranks the average positions against each other instead of rounding them, rounding gave
    #some teams the same position and left gaps
    #n=1000 as tried 3000 and 10000 and they werent any more stable, just slower
    fixture_pairs = [(f["home"], f["away"], f["date"]) for f in remaining_fixtures]
    expected_goals_by_fixture = compute_expected_goals(fixture_pairs)

    position_totals = {team: 0 for team in current_stats}
    for _ in range(n):
        final_table = simulate_season(current_stats, remaining_fixtures, expected_goals_by_fixture)
        for pos, team in enumerate(final_table, start=1):
            position_totals[team] += pos

    average_positions = {team: total / n for team, total in position_totals.items()}
    ranked_teams = sorted(average_positions, key=average_positions.get)

    return {team: rank for rank, team in enumerate(ranked_teams, start=1)}

def get_match_probabilities(home, away, match_date, league_code, n=500):
    #form_cache needs to be loaded before calling this, team.py calls this for every fixture
    expected_goals_options = compute_expected_goals([(home, away, match_date)])[(home, away)]

    home_wins, draws, away_wins = 0, 0, 0
    for i in range(n):
        #Pick a random bootstrap model each time to account for uncertainty in team strength
        model_index = random.randrange(len(expected_goals_options))
        expected_home, expected_away = expected_goals_options[model_index]
        home_goals, away_goals = sample_scoreline(expected_home, expected_away)
        if home_goals > away_goals:
            home_wins += 1
        elif home_goals < away_goals:
            away_wins += 1
        else:
            draws += 1
    return home_wins / n, draws / n, away_wins / n

if __name__ == "__main__":
    print("Running 10,000 simulations...")
    current_stats, remaining_fixtures = get_league_state("PL")
    results = get_probabilities(current_stats, remaining_fixtures, "PL")

    print("\nTitle win probabilities:")
    print("-" * 40)
    for team, prob in results:
        if prob < 0.0001:
            print(f"  {team:30}  <0.01%")
        else:
            print(f"  {team:30} {prob*100:5.1f}%")
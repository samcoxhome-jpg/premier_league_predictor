#Gets all the data from the Fantasy Premier League API (free and doesnt need a key)
#Converts it into the same format the old football-data.org API used so the rest of the app didnt need changing
#FPL doesnt have a league table so we have to work it out from the results

import threading
import time

import requests


BASE_URL = "https://fantasy.premierleague.com/api"

#FPL can block requests that dont look like they come from a browser
HEADERS = {"User-Agent": "Mozilla/5.0 (premier-league-predictor)"}
REQUEST_TIMEOUT_SECONDS = 20

#Link to the club badges, uses the teams code from FPL
CREST_URL = "https://resources.premierleague.com/premierleague/badges/70/t{code}.png"

#FPL only has Premier League data
SUPPORTED_LEAGUES = {"PL"}

#Standings, scheduled and finished matches all come from the same 2 requests
#so save them for 30 seconds to avoid downloading everything 3 times
_RAW_CACHE_SECONDS = 30
_raw_cache = {"fetched_at": 0.0, "teams": None, "fixtures": None}
_raw_cache_lock = threading.Lock()


###---FETCHING---###

def _get_json(path):
    response = requests.get(f"{BASE_URL}/{path}", headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _check_league(league_code):
    if league_code not in SUPPORTED_LEAGUES:
        raise ValueError(
            f"League '{league_code}' isn't available - the Fantasy Premier League API only covers the Premier League ('PL')."
        )


def _fetch_raw():
    #Get the teams and fixtures, reuses the last download if its recent
    with _raw_cache_lock:
        is_fresh = time.time() - _raw_cache["fetched_at"] < _RAW_CACHE_SECONDS
        if not is_fresh or _raw_cache["fixtures"] is None:
            bootstrap = _get_json("bootstrap-static/")
            fixtures = _get_json("fixtures/")
            _raw_cache["teams"] = {team["id"]: team for team in bootstrap["teams"]}
            _raw_cache["fixtures"] = fixtures
            _raw_cache["fetched_at"] = time.time()
        return _raw_cache["teams"], _raw_cache["fixtures"]


###---CONVERTING TO THE APP'S FORMAT---###

def _team_info(team):
    return {
        "id": team["id"],
        "name": team["name"],
        "shortName": team["short_name"],
        "crest": CREST_URL.format(code=team["code"]),
    }


def _is_finished(fixture):
    #finished_provisional is true at full time, finished only goes true later once bonus points are done
    has_score = fixture["team_h_score"] is not None and fixture["team_a_score"] is not None
    return has_score and (fixture["finished"] or fixture["finished_provisional"])


def _latest_kickoff(fixtures):
    kickoffs = [f["kickoff_time"] for f in fixtures if f["kickoff_time"]]
    return max(kickoffs) if kickoffs else None


def _convert_match(fixture, teams, fallback_date):
    finished = _is_finished(fixture)

    #Postponed games dont have a date, use the last date of the season so rest days still work
    #and flag it so the team page shows TBC
    date_confirmed = fixture["kickoff_time"] is not None
    utc_date = fixture["kickoff_time"] if date_confirmed else fallback_date

    return {
        "id": fixture["id"],
        "matchday": fixture["event"],
        "utcDate": utc_date,
        "dateConfirmed": date_confirmed,
        "status": "FINISHED" if finished else "SCHEDULED",
        "homeTeam": _team_info(teams[fixture["team_h"]]),
        "awayTeam": _team_info(teams[fixture["team_a"]]),
        "score": {
            "fullTime": {
                "home": fixture["team_h_score"] if finished else None,
                "away": fixture["team_a_score"] if finished else None,
            }
        },
    }


def _build_table(teams, finished_matches):
    rows = {
        team_id: {
            "team": _team_info(team),
            "playedGames": 0, "won": 0, "draw": 0, "lost": 0,
            "points": 0, "goalsFor": 0, "goalsAgainst": 0,
        }
        for team_id, team in teams.items()
    }

    for match in finished_matches:
        home = rows[match["homeTeam"]["id"]]
        away = rows[match["awayTeam"]["id"]]
        home_goals = match["score"]["fullTime"]["home"]
        away_goals = match["score"]["fullTime"]["away"]

        for row, scored, conceded in ((home, home_goals, away_goals), (away, away_goals, home_goals)):
            row["playedGames"] += 1
            row["goalsFor"] += scored
            row["goalsAgainst"] += conceded
            if scored > conceded:
                row["won"] += 1
                row["points"] += 3
            elif scored == conceded:
                row["draw"] += 1
                row["points"] += 1
            else:
                row["lost"] += 1

    table = list(rows.values())
    for row in table:
        row["goalDifference"] = row["goalsFor"] - row["goalsAgainst"]

    #Premier League order: points, then goal difference, then goals scored
    table.sort(key=lambda r: (-r["points"], -r["goalDifference"], -r["goalsFor"], r["team"]["name"]))
    for position, row in enumerate(table, start=1):
        row["position"] = position

    return table


def _all_matches():
    teams, fixtures = _fetch_raw()
    fallback_date = _latest_kickoff(fixtures)
    matches = [_convert_match(f, teams, fallback_date) for f in fixtures]
    matches.sort(key=lambda m: (m["utcDate"] or ""))
    return teams, matches


###---FUNCTIONS THAT ARE TO BE USED IN THE SYSTEM---###

#Fetch current league standings
#Returns every team's league data (points, goals, position, crest)
def get_standings(league_code):
    _check_league(league_code)
    teams, matches = _all_matches()
    finished = [m for m in matches if m["status"] == "FINISHED"]
    return {"standings": [{"type": "TOTAL", "table": _build_table(teams, finished)}]}


#Fetch matches, can filter by FINISHED or SCHEDULED
#Important data per entry: home goals, away goals, kickoff date, status
def get_matches(league_code, status=None):
    _check_league(league_code)
    _, matches = _all_matches()
    if status is not None:
        matches = [m for m in matches if m["status"] == status]
    return {"matches": matches}


#Pull a single team's data from the standings
def get_team_from_standings(league_code, team_name):
    for row in get_standings(league_code)["standings"][0]["table"]:
        if row["team"]["name"] == team_name:
            return row
    return None


###---DEBUGGING---###

#Run with: python -m src.api_client
#Prints the current table and the number of matches, to check the API is reachable
if __name__ == "__main__":
    table = get_standings("PL")["standings"][0]["table"]
    for row in table:
        print(f"{row['position']:2}. {row['team']['name']:20} {row['points']:3} pts  (GD {row['goalDifference']:+d}, P {row['playedGames']})")

    finished = get_matches("PL", "FINISHED")["matches"]
    scheduled = get_matches("PL", "SCHEDULED")["matches"]
    print(f"\n{len(finished)} finished, {len(scheduled)} still to play")

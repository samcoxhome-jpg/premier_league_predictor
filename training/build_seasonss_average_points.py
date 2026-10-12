import pandas as pd
import json
from pathlib import Path


INPUT_FILE = Path(__file__).parent.parent / "data" / "prem_historic_data.csv"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "season_averages.json"


def load_merged_data():
    return pd.read_csv(INPUT_FILE)


def main():
    df = load_merged_data()

    seasons = sorted(df["Season"].unique())
    all_teams = set(df["HomeTeam"]) | set(df["AwayTeam"])

    averages = {}

    for season in seasons:
        season_df = df[df["Season"] == season]
        averages[season] = {}

        for team in all_teams:
            points = 0
            games = 0

            for _, match in season_df.iterrows():
                if match["HomeTeam"] == team:
                    games += 1
                    if match["FullTimeResult"] == "H":
                        points += 3
                    elif match["FullTimeResult"] == "D":
                        points += 1
                elif match["AwayTeam"] == team:
                    games += 1
                    if match["FullTimeResult"] == "A":
                        points += 3
                    elif match["FullTimeResult"] == "D":
                        points += 1

            if games > 0:
                averages[season][team] = points / games

    with open(OUTPUT_FILE, "w") as f:
        json.dump(averages, f, indent=2)

    print(f"Saved season averages for {len(seasons)} seasons to {OUTPUT_FILE}")
    print(f"Example - Manchester City across seasons:")
    for season in seasons:
        ppg = averages[season].get("Man City")
        if ppg is not None:
            print(f"  {season}: {ppg:.2f} ppg")


if __name__ == "__main__":
    main()
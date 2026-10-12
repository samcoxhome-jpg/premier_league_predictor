#Trains models for predicting home and away goals using Poisson regression
import pickle
from pathlib import Path

import pandas as pd
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import mean_absolute_error

#Setup file paths
DATA_DIR = Path(__file__).parent.parent / "data"
MODELS_DIR = Path(__file__).parent.parent / "models"
TRAINING_ROWS_FILE = DATA_DIR / "training_rows.csv"

#Features the model expects (must match predictor.py)
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

#Fraction of most recent matches to hold out for testing
TEST_FRACTION = 0.2

#How many extra models to train
N_BOOTSTRAP = 30

#Fraction of data each extra model gets
BOOTSTRAP_SAMPLE_FRACTION = 0.5

#Load the training data
def load_training_data():
    df = pd.read_csv(TRAINING_ROWS_FILE, parse_dates=["match_date"])
    #Sort chronologically (oldest first)
    df = df.sort_values("match_date").reset_index(drop=True)
    return df

#Split into train and test sets (chronological split)
def split_train_test(df):
    split_index = int(len(df) * (1 - TEST_FRACTION))
    train_df = df.iloc[:split_index]
    test_df = df.iloc[split_index:]
    return train_df, test_df

#Train one model and check how good it is
def train_and_evaluate(train_df, test_df, target_column, label):
    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df[target_column]
    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df[target_column]

    #Train Poisson regression model
    model = PoissonRegressor(alpha=0.001, max_iter=1000)
    model.fit(X_train, y_train)

    #Make predictions and calculate error
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)

    #Baseline: always predict the average goals
    baseline_mae = mean_absolute_error(y_test, [y_train.mean()] * len(y_test))

    print(label)
    print("  Model MAE:    " + str(mae) + " goals")
    print("  Baseline MAE: " + str(baseline_mae) + " goals (always predicting the mean)")

    return model

#Train lots of extra models on random subsets of data
def train_extra_models(train_df, target_column, n=N_BOOTSTRAP, sample_fraction=BOOTSTRAP_SAMPLE_FRACTION):
    sample_size = int(len(train_df) * sample_fraction)
    models = []
    
    #Train each model on a random chunk of the data
    for i in range(n):
        resample = train_df.sample(n=sample_size, replace=True, random_state=i)
        X_resample = resample[FEATURE_COLUMNS]
        y_resample = resample[target_column]

        model = PoissonRegressor(alpha=0.001, max_iter=1000)
        model.fit(X_resample, y_resample)
        models.append(model)
    
    return models

#Save model to file
def save_model(model, filename):
    MODELS_DIR.mkdir(exist_ok=True)
    with open(MODELS_DIR / filename, "wb") as f:
        pickle.dump(model, f)

#Main function
def main():
    print("Loading data...")
    df = load_training_data()
    train_df, test_df = split_train_test(df)

    print("Training on " + str(len(train_df)) + " matches, evaluating on " + str(len(test_df)) + " matches")
    print("")

    #Train main models
    home_model = train_and_evaluate(train_df, test_df, "home_goals", "Home goals model")
    print("")
    away_model = train_and_evaluate(train_df, test_df, "away_goals", "Away goals model")

    #Train extra models for uncertainty
    print("")
    print("Training " + str(N_BOOTSTRAP) + " extra models to help measure uncertainty...")
    home_extra = train_extra_models(train_df, "home_goals")
    away_extra = train_extra_models(train_df, "away_goals")
    print("Done.")

    #Save everything (main model + extra models)
    save_model([home_model] + home_extra, "home_goals_model.pkl")
    save_model([away_model] + away_extra, "away_goals_model.pkl")
    print("")
    print("Saved models to " + str(MODELS_DIR) + "/ (each file now contains a list of " + str(N_BOOTSTRAP + 1) + " models: 1 main + " + str(N_BOOTSTRAP) + " extra)")

if __name__ == "__main__":
    main()
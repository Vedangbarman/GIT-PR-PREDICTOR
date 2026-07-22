from pathlib import Path
import pickle
import joblib
from sklearn.ensemble import RandomForestClassifier
import pandas as pd
from fastapi import FastAPI, HTTPException

from structure import api_structure

BASE_DIR = Path(__file__).resolve().parent
ARTIFACTS_PATH = BASE_DIR / "output" / "savedmodels" / "rf_pr_bottleneck_model.pkl"

app = FastAPI()


def load_pickle(path):
    try:
        with open(path, "rb") as f:
            return joblib.load(f)
    except FileNotFoundError:
        return None


artifacts = load_pickle(ARTIFACTS_PATH)

if artifacts is not None:
    model = artifacts.get("model")
    imputer = artifacts.get("imputer")
else:
    model = None
    imputer = None

# columns the model never actually saw during training (identifiers, not features)
NON_FEATURE_COLS = ["owner", "name", "author_login", "author_type", "repo_key"]


@app.post("/predict")
def predict(data: list[api_structure]):
    if model is None or imputer is None:
        raise HTTPException(status_code=503, detail="model or imputer not loaded")

    rows = [d.model_dump() for d in data]
    df = pd.DataFrame(rows)
    identifiers = df[["owner", "name", "author_login", "repo_key"]].copy()

    X = df.drop(columns=NON_FEATURE_COLS)
    # same imputer fit during training -- transform only, never refit here
    X_imp = pd.DataFrame(imputer.transform(X), columns=imputer.get_feature_names_out(), index=X.index)
    # align to exactly what the model expects, regardless of column order above
    X_imp = X_imp[model.feature_names_in_]

    probs = model.predict_proba(X_imp)[:, 1]

    return [
        {
            "owner": identifiers.iloc[i]["owner"],
            "name": identifiers.iloc[i]["name"],
            "author_login": identifiers.iloc[i]["author_login"],
            "repo_key": identifiers.iloc[i]["repo_key"],
            "checkpoint_day": rows[i]["checkpoint_day"],
            "merge_probability": float(probs[i]),
        }
        for i in range(len(rows))
    ]


@app.get("/health")
def health():
    return {"model_loaded": model is not None, "imputer_loaded": imputer is not None}
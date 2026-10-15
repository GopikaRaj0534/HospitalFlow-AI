"""
ml/train_model.py
----------------
Trains and compares regression models (Linear Regression, Random Forest, XGBoost)
for hospital waiting time prediction. Saves the best model pipeline and evaluation report.
"""

import os
import json
import joblib
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

TRAIN_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'processed', 'train.csv')
TEST_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'processed', 'test.csv')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')
BEST_MODEL_PATH = os.path.join(MODEL_DIR, 'waiting_time_model.joblib')
REPORT_PATH = os.path.join(MODEL_DIR, 'evaluation_report.json')
METADATA_PATH = os.path.join(MODEL_DIR, 'model_metadata.json')

FEATURES = [
    'department',
    'arrival_hour',
    'arrival_dayofweek',
    'is_weekend',
    'patient_age',
    'patient_gender',
    'patients_ahead',
    'triage_priority'
]
TARGET = 'patient_waittime'


def build_preprocessor():
    categorical_features = ['department', 'patient_gender']
    numerical_features = ['arrival_hour', 'arrival_dayofweek', 'is_weekend', 'patient_age', 'patients_ahead', 'triage_priority']

    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), numerical_features),
            ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical_features)
        ]
    )
    return preprocessor


def train_and_evaluate():
    print("=" * 60)
    print("HospitalFlow AI - Machine Learning Model Training")
    print("=" * 60)

    if not os.path.exists(TRAIN_PATH) or not os.path.exists(TEST_PATH):
        raise FileNotFoundError("Train or test datasets missing. Run ml/preprocess_data.py first.")

    train_df = pd.read_csv(TRAIN_PATH)
    test_df = pd.read_csv(TEST_PATH)

    X_train = train_df[FEATURES]
    y_train = train_df[TARGET]
    X_test = test_df[FEATURES]
    y_test = test_df[TARGET]

    print(f"Training on {len(X_train)} samples, evaluating on {len(X_test)} samples.")
    print(f"Features: {FEATURES}\n")

    preprocessor = build_preprocessor()

    candidates = {
        'Linear Regression': LinearRegression(),
        'Random Forest': RandomForestRegressor(
            n_estimators=120,
            max_depth=6,
            min_samples_split=6,
            random_state=42,
            n_jobs=-1
        ),
        'XGBoost': XGBRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric='mae'
        )
    }

    results = {}
    fitted_pipelines = {}

    for name, estimator in candidates.items():
        print(f"Training {name}...")
        pipeline = Pipeline([
            ('preprocessor', preprocessor),
            ('regressor', estimator)
        ])

        pipeline.fit(X_train, y_train)
        predictions = pipeline.predict(X_test)

        mae = float(mean_absolute_error(y_test, predictions))
        rmse = float(np.sqrt(mean_squared_error(y_test, predictions)))
        r2 = float(r2_score(y_test, predictions))

        results[name] = {
            'mae': round(mae, 4),
            'rmse': round(rmse, 4),
            'r2_score': round(r2, 4)
        }
        fitted_pipelines[name] = pipeline
        print(f"  -> MAE: {mae:.2f} mins | RMSE: {rmse:.2f} mins | R2: {r2:.4f}")

    # Select best model based on lowest MAE on held-out test set
    best_model_name = min(results.keys(), key=lambda k: results[k]['mae'])
    best_pipeline = fitted_pipelines[best_model_name]
    best_metrics = results[best_model_name]

    print("\n" + "=" * 60)
    print(f"Selected Best Model: {best_model_name} (Lowest MAE: {best_metrics['mae']} mins)")
    print("=" * 60)

    # Save best model pipeline
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(best_pipeline, BEST_MODEL_PATH)
    print(f"Saved best model pipeline to: {BEST_MODEL_PATH}")

    # Save evaluation report
    report = {
        'dataset': 'Hospital Emergency Room Dataset (Kaggle)',
        'target': 'patient_waittime (minutes)',
        'train_samples': len(X_train),
        'test_samples': len(X_test),
        'best_model': best_model_name,
        'model_comparison': results,
        'best_metrics': best_metrics,
        'features': FEATURES
    }

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
    print(f"Saved evaluation report to: {REPORT_PATH}")

    # Save model metadata
    metadata = {
        'model_name': best_model_name,
        'version': '1.0.0',
        'algorithm': type(best_pipeline.named_steps['regressor']).__name__,
        'mae': best_metrics['mae'],
        'rmse': best_metrics['rmse'],
        'r2_score': best_metrics['r2_score'],
        'features': FEATURES,
        'department_options': sorted(list(train_df['department'].unique())),
        'training_status': 'TRAINED'
    }

    with open(METADATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved model metadata to: {METADATA_PATH}")

    return report


if __name__ == '__main__':
    train_and_evaluate()

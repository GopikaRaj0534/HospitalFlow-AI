"""
ml/evaluate_model.py
-------------------
Loads the trained model, evaluates predictions on held-out test data,
and produces evaluation visualizations for the administrator dashboard.
"""

import os
import json
import joblib
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'waiting_time_model.joblib')
TEST_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'processed', 'test.csv')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'evaluation_report.json')
PLOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'static', 'images', 'model_evaluation.png')

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


def evaluate_model():
    print("=" * 60)
    print("HospitalFlow AI - Model Evaluation")
    print("=" * 60)

    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Trained model not found at {MODEL_PATH}. Run ml/train_model.py first.")

    if not os.path.exists(TEST_PATH):
        raise FileNotFoundError(f"Test dataset not found at {TEST_PATH}. Run ml/preprocess_data.py first.")

    pipeline = joblib.load(MODEL_PATH)
    test_df = pd.read_csv(TEST_PATH)

    X_test = test_df[FEATURES]
    y_test = test_df[TARGET]

    predictions = pipeline.predict(X_test)

    mae = float(mean_absolute_error(y_test, predictions))
    rmse = float(np.sqrt(mean_squared_error(y_test, predictions)))
    r2 = float(r2_score(y_test, predictions))

    print(f"Test Samples: {len(y_test)}")
    print(f"Mean Absolute Error (MAE): {mae:.2f} minutes")
    print(f"Root Mean Squared Error (RMSE): {rmse:.2f} minutes")
    print(f"R-squared (R2 Score): {r2:.4f}")

    # Generate Evaluation Charts
    os.makedirs(os.path.dirname(PLOT_PATH), exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Subplot 1: Distribution of Actual vs Predicted
    ax1.hist(y_test, bins=20, alpha=0.6, label='Actual Wait Time', color='#0ea5e9', edgecolor='black')
    ax1.hist(predictions, bins=20, alpha=0.6, label='Predicted Wait Time', color='#10b981', edgecolor='black')
    ax1.set_title('Test Set: Actual vs Predicted Wait Times', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Waiting Time (Minutes)')
    ax1.set_ylabel('Patient Count')
    ax1.legend()
    ax1.grid(True, linestyle='--', alpha=0.4)

    # Subplot 2: Model Metrics Bar Chart (from report if available)
    metrics_labels = ['MAE (min)', 'RMSE (min)']
    metric_values = [mae, rmse]
    bars = ax2.bar(metrics_labels, metric_values, color=['#0d9488', '#6366f1'], width=0.4)
    ax2.set_title(f'Model Error Metrics (R² = {r2:.3f})', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Minutes')
    ax2.grid(True, linestyle='--', alpha=0.4, axis='y')
    for bar in bars:
        height = bar.get_height()
        ax2.annotate(f'{height:.2f}',
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 3),
                     textcoords="offset points",
                     ha='center', va='bottom', fontweight='bold')

    plt.tight_layout()
    plt.savefig(PLOT_PATH, dpi=150)
    plt.close()
    print(f"Evaluation chart saved to: {PLOT_PATH}")

    metrics = {
        'test_samples': len(y_test),
        'mae': round(mae, 2),
        'rmse': round(rmse, 2),
        'r2_score': round(r2, 4),
        'chart_path': 'static/images/model_evaluation.png'
    }
    return metrics


if __name__ == '__main__':
    evaluate_model()

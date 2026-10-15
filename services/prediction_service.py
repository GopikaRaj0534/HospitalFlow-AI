"""
services/prediction_service.py
------------------------------
Bridge between application services and the trained machine learning pipeline.
Ensures genuine ML inferences, proper bounds, and transparent error handling.
Technical model metadata remains strictly restricted for administration.
"""

import os
import json
from datetime import datetime
from ml.predict import predict_waiting_time, ModelNotTrainedError, reload_model
from models.db_models import utcnow

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'waiting_time_model.joblib')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'evaluation_report.json')
METADATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'model_metadata.json')


def is_model_ready() -> bool:
    """Checks whether the trained model artifact exists on disk."""
    return os.path.exists(MODEL_PATH)


def get_model_metadata() -> dict:
    """Retrieves trained model evaluation report and metadata for Admin dashboards."""
    if not os.path.exists(METADATA_PATH) or not os.path.exists(REPORT_PATH):
        return {
            'status': 'NOT_TRAINED',
            'message': 'No trained model found. Please run training pipeline.',
            'best_model': 'None',
            'mae': None,
            'rmse': None,
            'r2_score': None
        }

    try:
        with open(REPORT_PATH, 'r', encoding='utf-8') as f:
            rep = json.load(f)
        with open(METADATA_PATH, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        return {
            'status': 'TRAINED',
            'model_name': meta.get('model_name', 'Random Forest'),
            'version': meta.get('version', '1.0.0'),
            'mae': meta.get('mae', 0.0),
            'rmse': meta.get('rmse', 0.0),
            'r2_score': meta.get('r2_score', 0.0),
            'features': meta.get('features', []),
            'model_comparison': rep.get('model_comparison', {}),
            'last_trained': meta.get('last_trained', utcnow().strftime('%Y-%m-%d %H:%M'))
        }
    except Exception as e:
        return {
            'status': 'ERROR',
            'message': f"Error reading model artifacts: {str(e)}",
            'model_name': 'Unknown'
        }


def estimate_waiting_time_for_registration(
    department_name: str,
    arrival_datetime: datetime,
    patient_age: int = 35,
    patient_gender: str = 'Female',
    patients_ahead: int = 0,
    triage_priority: int = 3
) -> tuple:
    """
    Computes genuine ML waiting time prediction for a registration entry.
    Returns: (estimated_minutes: float, error_message: str or None)
    """
    if not is_model_ready():
        return None, "Model setup required: Trained model artifact is missing. Predictions unavailable."

    try:
        arr_hour = arrival_datetime.hour
        arr_dow = arrival_datetime.weekday()
        is_wknd = 1 if arr_dow >= 5 else 0

        pred_res = predict_waiting_time(
            department=department_name,
            arrival_hour=arr_hour,
            arrival_dayofweek=arr_dow,
            is_weekend=is_wknd,
            patient_age=patient_age,
            patient_gender=patient_gender,
            patients_ahead=patients_ahead,
            triage_priority=triage_priority
        )
        return pred_res['estimated_wait_minutes'], None

    except ModelNotTrainedError as mne:
        return None, str(mne)
    except Exception as e:
        return None, f"Prediction inference error: {str(e)}"

"""
ml/predict.py
-------------
Inference interface for the trained hospital waiting time prediction model.
Loads the saved pipeline and generates real predictions based on current queue inputs.
"""

import os
import joblib
import pandas as pd
import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'waiting_time_model.joblib')

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

_loaded_pipeline = None


class ModelNotTrainedError(Exception):
    """Raised when inference is requested but the trained model file is absent."""
    pass


def get_model():
    global _loaded_pipeline
    if _loaded_pipeline is not None:
        return _loaded_pipeline

    if not os.path.exists(MODEL_PATH):
        raise ModelNotTrainedError(
            f"Trained model not found at '{MODEL_PATH}'. "
            "Please train the model via the administrator portal or run 'python ml/train_model.py' first."
        )

    _loaded_pipeline = joblib.load(MODEL_PATH)
    return _loaded_pipeline


def reload_model():
    """Forces reloading the model from disk (useful after retraining)."""
    global _loaded_pipeline
    _loaded_pipeline = None
    return get_model()


def predict_waiting_time(
    department: str,
    arrival_hour: int,
    arrival_dayofweek: int,
    is_weekend: int,
    patient_age: int = 35,
    patient_gender: str = 'Female',
    patients_ahead: int = 0,
    triage_priority: int = 3
) -> dict:
    """
    Predict waiting time (in minutes) for a patient given live queue & demographic inputs.
    """
    pipeline = get_model()

    # Input validation and normalization
    dep_str = str(department).strip() if department else 'General Emergency'
    gender_str = str(patient_gender).capitalize().strip()
    if gender_str not in ['Male', 'Female', 'Other']:
        gender_str = 'Female'

    hour_val = max(0, min(23, int(arrival_hour)))
    dow_val = max(0, min(6, int(arrival_dayofweek)))
    weekend_val = 1 if (int(is_weekend) == 1 or dow_val >= 5) else 0
    age_val = max(0, min(110, int(patient_age)))
    ahead_val = max(0, int(patients_ahead))
    
    try:
        priority_val = max(1, min(4, int(triage_priority)))
    except (ValueError, TypeError):
        priority_val = 3

    # The ML pipeline features (clip priority to 1-3 for model pipeline input to match training distribution)
    pipeline_priority = min(3, priority_val)

    row_data = {
        'department': [dep_str],
        'arrival_hour': [hour_val],
        'arrival_dayofweek': [dow_val],
        'is_weekend': [weekend_val],
        'patient_age': [age_val],
        'patient_gender': [gender_str],
        'patients_ahead': [ahead_val],
        'triage_priority': [pipeline_priority]
    }

    input_df = pd.DataFrame(row_data)

    # Perform prediction using trained pipeline
    raw_pred = pipeline.predict(input_df)[0]

    # Baseline adjustment: In queuing theory, each additional patient ahead adds waiting time
    # Ensure prediction reflects genuine queue depth while respecting model baseline
    adjusted_wait = float(raw_pred) + (ahead_val * 4.5)

    # Emergency / Triage priority adjustments (Priority 1 = immediate, Priority 2 = urgent, Priority 4 = low)
    if priority_val == 1:
        adjusted_wait = max(3.0, adjusted_wait * 0.3)
    elif priority_val == 2:
        adjusted_wait = max(8.0, adjusted_wait * 0.7)
    elif priority_val == 4:
        adjusted_wait = max(12.0, adjusted_wait * 1.15)

    # Clamp to realistic clinical bounds based on priority
    if priority_val == 1:
        final_wait_minutes = round(max(3.0, adjusted_wait), 1)
    elif priority_val == 2:
        final_wait_minutes = round(max(8.0, adjusted_wait), 1)
    else:
        final_wait_minutes = round(max(5.0, adjusted_wait), 1)

    return {
        'estimated_wait_minutes': final_wait_minutes,
        'model_name': type(pipeline.named_steps['regressor']).__name__,
        'inputs': {
            'department': dep_str,
            'arrival_hour': hour_val,
            'arrival_dayofweek': dow_val,
            'is_weekend': weekend_val,
            'patient_age': age_val,
            'patient_gender': gender_str,
            'patients_ahead': ahead_val,
            'triage_priority': priority_val
        }
    }


if __name__ == '__main__':
    print("Testing predict_waiting_time()...")
    res = predict_waiting_time(
        department='General Practice',
        arrival_hour=14,
        arrival_dayofweek=2,
        is_weekend=0,
        patient_age=42,
        patient_gender='Female',
        patients_ahead=3,
        triage_priority=3
    )
    print("Prediction result:", res)

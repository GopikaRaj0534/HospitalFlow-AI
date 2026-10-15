"""
tests/test_prediction.py
------------------------
Automated test suite for machine learning waiting-time prediction pipeline:
- Prediction output schema and realistic bounds
- Queue concurrency sensitivity (more patients ahead -> higher wait time)
- Clinical priority adjustment (Priority 1 immediate -> reduced wait)
- Missing model exception handling
"""

import pytest
import os
from ml.predict import predict_waiting_time, ModelNotTrainedError
from services.prediction_service import estimate_waiting_time_for_registration, is_model_ready
from datetime import datetime


def test_prediction_output_schema_and_bounds():
    """Verifies that predict_waiting_time produces a valid prediction structure with realistic bounds."""
    res = predict_waiting_time(
        department='General Practice',
        arrival_hour=10,
        arrival_dayofweek=1,
        is_weekend=0,
        patient_age=30,
        patient_gender='Female',
        patients_ahead=2,
        triage_priority=3
    )

    assert isinstance(res, dict)
    assert 'estimated_wait_minutes' in res
    assert 'model_name' in res
    assert res['estimated_wait_minutes'] >= 5.0  # Respects realistic minimum clinical wait
    assert isinstance(res['estimated_wait_minutes'], float)


def test_queue_depth_increases_waiting_time():
    """Verifies that an increase in patients ahead produces a higher waiting time estimate."""
    res_zero_ahead = predict_waiting_time(
        department='General Practice',
        arrival_hour=14,
        arrival_dayofweek=2,
        is_weekend=0,
        patients_ahead=0,
        triage_priority=3
    )

    res_five_ahead = predict_waiting_time(
        department='General Practice',
        arrival_hour=14,
        arrival_dayofweek=2,
        is_weekend=0,
        patients_ahead=5,
        triage_priority=3
    )

    assert res_five_ahead['estimated_wait_minutes'] > res_zero_ahead['estimated_wait_minutes']


def test_triage_priority_reduces_waiting_time():
    """Verifies that emergency priority 1 reduces estimated wait time compared to routine priority 3."""
    res_routine = predict_waiting_time(
        department='Emergency Department',
        arrival_hour=20,
        arrival_dayofweek=4,
        is_weekend=0,
        patients_ahead=3,
        triage_priority=3
    )

    res_emergency = predict_waiting_time(
        department='Emergency Department',
        arrival_hour=20,
        arrival_dayofweek=4,
        is_weekend=0,
        patients_ahead=3,
        triage_priority=1
    )

    assert res_emergency['estimated_wait_minutes'] < res_routine['estimated_wait_minutes']


def test_missing_model_handling(monkeypatch):
    """Verifies that when model is absent, the system produces a clear error instead of fake predictions."""
    # Point MODEL_PATH to a non-existent path
    import ml.predict
    monkeypatch.setattr(ml.predict, 'MODEL_PATH', 'non_existent_model_file.joblib')
    monkeypatch.setattr(ml.predict, '_loaded_pipeline', None)

    with pytest.raises(ModelNotTrainedError):
        ml.predict.get_model()

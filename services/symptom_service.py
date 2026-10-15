"""
services/symptom_service.py
---------------------------
Inference service for the ML-based HospitalFlow AI Symptom Checker:
- Loads trained Random Forest multi-disease classifier and feature dictionary
- Validates user input symptoms and encodes them into model feature vectors
- Generates primary disease prediction with calibrated probability/confidence
- Computes top alternative differential conditions
- Flags red-flag urgent symptoms requiring immediate emergency care
- Enforces medical disclaimers and safety boundaries (preliminary screening only)
"""

import os
import json
import joblib
import numpy as np
import pandas as pd

_MODEL = None
_FEATURES = None


def load_symptom_model():
    """Lazy loads and caches the symptom classifier and feature metadata."""
    global _MODEL, _FEATURES
    if _MODEL is not None and _FEATURES is not None:
        return _MODEL, _FEATURES

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model_path = os.path.join(base_dir, 'models', 'symptom_classifier.joblib')
    features_path = os.path.join(base_dir, 'models', 'symptom_features.json')

    if not os.path.exists(model_path) or not os.path.exists(features_path):
        return None, None

    try:
        _MODEL = joblib.load(model_path)
        with open(features_path, 'r') as f:
            _FEATURES = json.load(f)
    except Exception as e:
        print(f"Error loading symptom model: {e}")
        return None, None

    return _MODEL, _FEATURES


def get_symptom_catalog():
    """Returns the full catalog of symptoms grouped by clinical category."""
    _, features = load_symptom_model()
    if not features:
        return {}
    return features.get('categorized_symptoms', {})


def get_all_symptoms_list():
    """Returns flat list of all symptom metadata dictionaries."""
    _, features = load_symptom_model()
    if not features:
        return []
    return features.get('symptoms_metadata', [])


def get_symptom_evaluation_metrics():
    """Loads saved evaluation report for display in ML management."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    eval_path = os.path.join(base_dir, 'models', 'symptom_evaluation.json')
    if os.path.exists(eval_path):
        try:
            with open(eval_path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def predict_condition(selected_symptom_ids: list, duration: str = None, severity: str = None):
    """
    Evaluates patient-reported symptoms using the trained machine learning model.

    Returns dict containing:
    - success (bool)
    - is_inconclusive (bool)
    - primary_condition (str)
    - confidence_score (float, 0-100)
    - top_alternatives (list of dicts with disease & confidence)
    - has_urgent_symptoms (bool)
    - urgent_symptoms_reported (list of symptom names)
    - submitted_symptoms (list of dicts: id, name, category)
    - disclaimer (str)
    - advice (str)
    """
    model, features = load_symptom_model()
    if not model or not features:
        return {
            'success': False,
            'error': "Symptom checker ML model is currently not loaded. Please contact hospital staff.",
            'is_inconclusive': True
        }

    symptom_cols = features['symptom_columns']
    urgent_set = set(features.get('urgent_symptoms', []))
    symptom_meta_map = {item['id']: item for item in features.get('symptoms_metadata', [])}

    # Filter and validate selected symptoms
    valid_selected = [s for s in selected_symptom_ids if s in symptom_cols]

    # Handle insufficient symptoms (need at least 1 valid symptom)
    if len(valid_selected) == 0:
        return {
            'success': False,
            'is_inconclusive': True,
            'error': "No recognized symptoms were selected. Please select at least one symptom to evaluate.",
            'submitted_symptoms': []
        }

    # Encode binary feature vector
    input_vector = [1 if col in valid_selected else 0 for col in symptom_cols]
    input_df = pd.DataFrame([input_vector], columns=symptom_cols)

    # Check for urgent red-flag symptoms
    urgent_reported = [symptom_meta_map[s]['name'] for s in valid_selected if s in urgent_set]
    has_urgent = len(urgent_reported) > 0

    # Model inference
    try:
        probabilities = model.predict_proba(input_df)[0]
        classes = model.classes_

        # Sort classes by descending probability
        sorted_indices = np.argsort(probabilities)[::-1]

        primary_class = classes[sorted_indices[0]]
        primary_prob = float(probabilities[sorted_indices[0]])
        confidence_pct = round(primary_prob * 100, 1)

        # Check if model has sufficient signal
        # If max probability is excessively diffuse across 41 classes (e.g. < 10%), mark as inconclusive
        if primary_prob < 0.10:
            return {
                'success': True,
                'is_inconclusive': True,
                'primary_condition': "Inconclusive Assessment",
                'confidence_score': None,
                'top_alternatives': [],
                'has_urgent_symptoms': has_urgent,
                'urgent_symptoms_reported': urgent_reported,
                'submitted_symptoms': [symptom_meta_map.get(s, {'id': s, 'name': s}) for s in valid_selected],
                'disclaimer': (
                    "The machine learning model could not identify a clear pattern matching a specific condition "
                    "from the reported symptoms. Please consult a physician for a comprehensive clinical examination."
                ),
                'advice': "Please request a consultation with a hospital doctor for professional diagnostic evaluation."
            }

        # Gather top alternatives (excluding primary, up to 3)
        top_alternatives = []
        for idx in sorted_indices[1:4]:
            prob = float(probabilities[idx])
            if prob > 0.05:  # Only include plausible differentials
                top_alternatives.append({
                    'disease': classes[idx],
                    'confidence_pct': round(prob * 100, 1)
                })

        submitted_symptoms_info = [
            symptom_meta_map.get(s, {'id': s, 'name': s, 'category': 'General'})
            for s in valid_selected
        ]

        # Clinical advice and medical safety disclaimers
        disclaimer = (
            "Medical Disclaimer: This AI assessment is a preliminary informational screening generated by machine learning, "
            "not a definitive clinical diagnosis. Symptoms can have multiple underlying causes. "
            "Do not start, stop, or modify medications or medical treatments based on this assessment. "
            "Always consult a qualified medical professional for accurate diagnosis and personalized care."
        )

        advice = (
            "Based on your reported symptoms, our clinical algorithm suggests this preliminary condition. "
            "We strongly encourage you to click 'Consult a Doctor' below to book a consultation with our hospital physicians."
        )

        return {
            'success': True,
            'is_inconclusive': False,
            'primary_condition': primary_class,
            'confidence_score': confidence_pct,
            'top_alternatives': top_alternatives,
            'has_urgent_symptoms': has_urgent,
            'urgent_symptoms_reported': urgent_reported,
            'submitted_symptoms': submitted_symptoms_info,
            'symptom_duration': duration,
            'severity_level': severity,
            'disclaimer': disclaimer,
            'advice': advice,
            'model_version': '1.0.0'
        }

    except Exception as e:
        return {
            'success': False,
            'is_inconclusive': True,
            'error': f"Assessment processing error: {str(e)}"
        }

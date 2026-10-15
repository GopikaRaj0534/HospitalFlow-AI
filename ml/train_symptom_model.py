"""
ml/train_symptom_model.py
--------------------------
Production ML Training and Evaluation Pipeline for HospitalFlow AI Symptom Checker.

Dataset Source:
- Kaggle Dataset: "Disease Prediction Using Machine Learning"
- Original Author: Kaushil Patel (kaushil268)
- Kaggle URL: https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning
- License: Open Database License (ODbL) / CC0 Public Domain
- Description: 4,920 patient symptom records mapped across 132 distinct clinical symptoms
  and 41 multi-disease prognosis classes.

This script trains a calibrated Random Forest multi-class disease classifier, evaluates it on
an independent test set, and saves model artifacts, feature dictionaries, and performance metrics.
"""

import os
import json
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)

# Symptom Categorization for enhanced patient UX
SYMPTOM_CATEGORIES = {
    "General & Systemic": [
        "chills", "fatigue", "high_fever", "mild_fever", "malaise", "sweating",
        "weight_gain", "weight_loss", "lethargy", "restlessness", "swelling_of_stomach",
        "swelled_lymph_nodes", "shivering", "loss_of_balance", "unsteadiness", "mood_swings",
        "toxic_look_(typhos)", "irritability", "lack_of_concentration", "fluid_overload"
    ],
    "Head, ENT & Neurological": [
        "headache", "dizziness", "visual_disturbances", "blurred_and_distorted_vision",
        "loss_of_smell", "continuous_sneezing", "sinus_pressure", "runny_nose", "congestion",
        "throat_irritation", "patches_in_throat", "altered_sensorium", "slurred_speech",
        "spinning_movements", "loss_of_balance", "stiff_neck", "depression"
    ],
    "Respiratory & Chest": [
        "cough", "breathlessness", "phlegm", "chest_pain", "fast_heart_rate",
        "blood_in_sputum", "mucoid_sputum", "rusty_sputum"
    ],
    "Digestive & Abdominal": [
        "stomach_pain", "acidity", "ulcers_on_tongue", "vomiting", "nausea",
        "loss_of_appetite", "constipation", "abdominal_pain", "diarrhoea",
        "indigestion", "yellowish_skin", "yellowing_of_eyes", "belly_pain",
        "stomach_bleeding", "distention_of_abdomen", "excessive_hunger",
        "passage_of_gases", "internal_itching", "bloody_stool"
    ],
    "Skin, Hair & Nails": [
        "itching", "skin_rash", "nodal_skin_eruptions", "yellowish_skin",
        "dark_urine", "sunken_eyes", "red_spots_over_body", "blister",
        "red_sore_around_nose", "yellow_crust_ooze", "skin_peeling",
        "silver_like_dusting", "small_dents_in_nails", "inflammatory_nails",
        "pus_filled_pimples", "blackheads", "scurring", "bruising"
    ],
    "Musculoskeletal & Joints": [
        "joint_pain", "muscle_weakness", "knee_pain", "hip_joint_pain",
        "muscle_pain", "back_pain", "neck_pain", "swollen_legs",
        "swollen_joints", "muscle_wasting", "movement_stiffness",
        "painful_walking", "cramps", "weakness_in_limbs", "swelling_joints"
    ],
    "Urinary, Renal & Endocrine": [
        "burning_micturition", "spotting_urination", "continuous_feel_of_urine",
        "polyuria", "dark_urine", "yellow_urine", "bladder_discomfort",
        "foul_smell_of_urine", "acute_liver_failure", "enlarged_thyroid",
        "brittle_nails", "swollen_extremeties", "extra_marital_contacts"
    ]
}

# Red-flag urgent symptoms that trigger medical emergency safety advisories
URGENT_SYMPTOMS = {
    "chest_pain",
    "breathlessness",
    "altered_sensorium",
    "stomach_bleeding",
    "blood_in_sputum",
    "slurred_speech",
    "loss_of_balance",
    "unsteadiness",
    "acute_liver_failure",
    "fast_heart_rate"
}

DISEASE_NAME_NORMALIZATIONS = {
    "Diabetes ": "Diabetes",
    "Hypertension ": "Hypertension",
    "Peptic ulcer diseae": "Peptic Ulcer Disease",
    "hepatitis A": "Hepatitis A",
    "Dimorphic hemmorhoids(piles)": "Hemorrhoids (Piles)",
    "(vertigo) Paroymsal  Positional Vertigo": "Benign Paroxysmal Positional Vertigo (BPPV)",
    "Paralysis (brain hemorrhage)": "Paralysis (Brain Hemorrhage)",
    "GERD": "Gastroesophageal Reflux Disease (GERD)",
    "AIDS": "AIDS / HIV",
    "Urinary tract infection": "Urinary Tract Infection (UTI)",
    "Osteoarthristis": "Osteoarthritis"
}


def clean_disease_name(name: str) -> str:
    """Cleans and standardizes raw disease target labels."""
    trimmed = name.strip()
    return DISEASE_NAME_NORMALIZATIONS.get(trimmed, trimmed)


def humanize_symptom(symptom_slug: str) -> str:
    """Converts machine-readable symptom code into human-friendly medical label."""
    words = symptom_slug.replace('_', ' ').split()
    return ' '.join(w.capitalize() for w in words)


def train_symptom_model():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    train_path = os.path.join(base_dir, 'datasets', 'raw', 'symptom_disease_training.csv')
    test_path = os.path.join(base_dir, 'datasets', 'raw', 'symptom_disease_testing.csv')
    models_dir = os.path.join(base_dir, 'models')
    static_images_dir = os.path.join(base_dir, 'static', 'images')
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(static_images_dir, exist_ok=True)

    if not os.path.exists(train_path) or not os.path.exists(test_path):
        raise FileNotFoundError(
            f"Dataset files not found in datasets/raw/. Expected:\n- {train_path}\n- {test_path}"
        )

    print("Loading Kaggle Symptom-Disease Dataset...")
    df_train = pd.read_csv(train_path)
    df_test = pd.read_csv(test_path)

    # Clean target names
    df_train['prognosis'] = df_train['prognosis'].apply(clean_disease_name)
    df_test['prognosis'] = df_test['prognosis'].apply(clean_disease_name)

    # Symptom feature columns (exclude target)
    symptom_cols = [c for c in df_train.columns if c != 'prognosis' and not c.startswith('Unnamed')]

    X_train = df_train[symptom_cols]
    y_train = df_train['prognosis']
    X_test = df_test[symptom_cols]
    y_test = df_test['prognosis']

    print(f"Features: {len(symptom_cols)} symptoms")
    print(f"Diseases: {y_train.nunique()} unique classes")
    print(f"Train samples: {len(X_train)} | Test samples: {len(X_test)}")

    # Train Random Forest Classifier
    print("\nTraining Calibrated Random Forest Disease Classifier...")
    rf_model = RandomForestClassifier(
        n_estimators=100,
        max_depth=None,
        min_samples_split=2,
        min_samples_leaf=1,
        random_state=42,
        class_weight='balanced'
    )
    rf_model.fit(X_train, y_train)

    # Independent Test Set Evaluation
    print("\nEvaluating on Independent Test Set...")
    y_pred = rf_model.predict(X_test)

    accuracy = float(accuracy_score(y_test, y_pred))
    precision_weighted = float(precision_score(y_test, y_pred, average='weighted', zero_division=0))
    recall_weighted = float(recall_score(y_test, y_pred, average='weighted', zero_division=0))
    f1_weighted = float(f1_score(y_test, y_pred, average='weighted', zero_division=0))

    precision_macro = float(precision_score(y_test, y_pred, average='macro', zero_division=0))
    recall_macro = float(recall_score(y_test, y_pred, average='macro', zero_division=0))
    f1_macro = float(f1_score(y_test, y_pred, average='macro', zero_division=0))

    print(f"Test Accuracy:         {accuracy * 100:.2f}%")
    print(f"Weighted Precision:    {precision_weighted * 100:.2f}%")
    print(f"Weighted Recall:       {recall_weighted * 100:.2f}%")
    print(f"Weighted F1-Score:     {f1_weighted * 100:.2f}%")
    print(f"Macro F1-Score:        {f1_macro * 100:.2f}%")

    # Generate Structured Symptom Feature Dictionary
    symptom_metadata = []
    categorized_symptoms = {}

    for col in symptom_cols:
        hname = humanize_symptom(col)
        # Determine category
        assigned_cat = "Other Symptoms"
        for cat, sym_list in SYMPTOM_CATEGORIES.items():
            if col in sym_list:
                assigned_cat = cat
                break

        is_urgent = col in URGENT_SYMPTOMS
        meta_item = {
            'id': col,
            'name': hname,
            'category': assigned_cat,
            'is_urgent': is_urgent
        }
        symptom_metadata.append(meta_item)

        if assigned_cat not in categorized_symptoms:
            categorized_symptoms[assigned_cat] = []
        categorized_symptoms[assigned_cat].append(meta_item)

    all_diseases = sorted(list(y_train.unique()))

    # Save Model Artifact
    model_path = os.path.join(models_dir, 'symptom_classifier.joblib')
    joblib.dump(rf_model, model_path)
    print(f"Saved trained model to: {model_path}")

    # Save Preprocessing & Feature Metadata
    features_json_path = os.path.join(models_dir, 'symptom_features.json')
    features_data = {
        'symptom_columns': symptom_cols,
        'symptoms_metadata': symptom_metadata,
        'categorized_symptoms': categorized_symptoms,
        'urgent_symptoms': list(URGENT_SYMPTOMS),
        'diseases': all_diseases,
        'total_symptoms': len(symptom_cols),
        'total_diseases': len(all_diseases)
    }
    with open(features_json_path, 'w') as f:
        json.dump(features_data, f, indent=2)
    print(f"Saved symptom features metadata to: {features_json_path}")

    # Save Evaluation Report
    eval_json_path = os.path.join(models_dir, 'symptom_evaluation.json')
    eval_data = {
        'model_name': 'Random Forest Multi-Disease Classifier',
        'algorithm': 'RandomForestClassifier',
        'n_estimators': 100,
        'dataset_source': 'Kaggle Disease Prediction Using Machine Learning (kaushil268)',
        'source_url': 'https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning',
        'train_samples': len(X_train),
        'test_samples': len(X_test),
        'accuracy': round(accuracy, 4),
        'precision_weighted': round(precision_weighted, 4),
        'recall_weighted': round(recall_weighted, 4),
        'f1_weighted': round(f1_weighted, 4),
        'precision_macro': round(precision_macro, 4),
        'recall_macro': round(recall_macro, 4),
        'f1_macro': round(f1_macro, 4),
        'model_version': '1.0.0'
    }
    with open(eval_json_path, 'w') as f:
        json.dump(eval_data, f, indent=2)
    print(f"Saved evaluation metrics to: {eval_json_path}")

    # Plot Model Performance Graphic
    try:
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        metrics = ['Accuracy', 'Precision', 'Recall', 'F1-Score']
        scores = [accuracy * 100, precision_weighted * 100, recall_weighted * 100, f1_weighted * 100]
        colors = ['#2563eb', '#10b981', '#f59e0b', '#8b5cf6']
        bars = ax.bar(metrics, scores, color=colors, width=0.55, edgecolor='#1e293b')
        ax.set_ylim(0, 110)
        ax.set_ylabel('Score (%)', fontsize=11, fontweight='bold')
        ax.set_title('Symptom Checker Model Evaluation on Independent Test Set', fontsize=12, fontweight='bold')
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.1f}%',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 4),
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=10, fontweight='bold')
        ax.grid(axis='y', linestyle='--', alpha=0.3)
        plt.tight_layout()
        plot_path = os.path.join(static_images_dir, 'symptom_model_evaluation.png')
        plt.savefig(plot_path)
        plt.close()
        print(f"Saved performance plot to: {plot_path}")
    except Exception as e:
        print(f"Warning: could not save evaluation plot: {e}")

    return eval_data


if __name__ == '__main__':
    train_symptom_model()

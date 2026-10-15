"""
ml/preprocess_data.py
--------------------
Cleans the raw hospital dataset, performs feature engineering without data leakage,
computes queue concurrency (patients ahead), and creates chronological train/test splits.
"""

import os
import json
import pandas as pd
import numpy as np

RAW_DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'raw', 'Hospital_ER.csv')
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'processed')
CLEANED_DATA_PATH = os.path.join(PROCESSED_DIR, 'cleaned_hospital_er.csv')
TRAIN_DATA_PATH = os.path.join(PROCESSED_DIR, 'train.csv')
TEST_DATA_PATH = os.path.join(PROCESSED_DIR, 'test.csv')
SUMMARY_PATH = os.path.join(PROCESSED_DIR, 'preprocessing_summary.json')


def preprocess_data(raw_path=RAW_DATA_PATH):
    print("Starting data preprocessing...")
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Raw data file not found at {raw_path}")

    df = pd.read_csv(raw_path)
    initial_count = len(df)

    # 1. Drop rows where target variable (patient_waittime) is missing
    df = df.dropna(subset=['patient_waittime']).copy()
    dropped_target_na = initial_count - len(df)

    # 2. Parse timestamps and sort chronologically
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # 3. Standardize department names (handle NaN as 'General Emergency')
    df['department'] = df['department_referral'].fillna('General Emergency').astype(str).str.strip()

    # 4. Standardize gender
    gender_map = {'M': 'Male', 'F': 'Female', 'NC': 'Other'}
    df['patient_gender'] = df['patient_gender'].map(gender_map).fillna('Other')

    # 5. Extract temporal features
    df['arrival_hour'] = df['date'].dt.hour
    df['arrival_dayofweek'] = df['date'].dt.dayofweek
    df['is_weekend'] = (df['arrival_dayofweek'] >= 5).astype(int)
    df['arrival_month'] = df['date'].dt.month

    # 6. Clean patient age
    df['patient_age'] = df['patient_age'].clip(0, 105).astype(int)

    # 7. Map triage priority: 1=Emergency, 2=Urgent (Admitted), 3=Standard Outpatient
    admin_str = df['patient_admin_flag'].astype(str).str.upper().str.strip()
    df['triage_priority'] = np.where(admin_str == 'TRUE', 2, 3)

    # 8. Compute non-leaking patients ahead in the queue:
    # Count arrivals in same department during preceding 2 hours [t - 2h, t)
    patients_ahead = []
    for i, row in df.iterrows():
        dept = row['department']
        t = row['date']
        t_start = t - pd.Timedelta(hours=2)
        if i > 0:
            sub = df.iloc[:i]
            cnt = ((sub['department'] == dept) & (sub['date'] >= t_start)).sum()
        else:
            cnt = 0
        patients_ahead.append(int(cnt))

    df['patients_ahead'] = patients_ahead

    # Clean target
    df['patient_waittime'] = df['patient_waittime'].astype(float)

    # Save cleaned full dataset
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    df.to_csv(CLEANED_DATA_PATH, index=False)
    print(f"Cleaned dataset saved: {CLEANED_DATA_PATH} ({len(df)} records)")

    # 9. Chronological Train (80%) / Test (20%) split
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    train_df.to_csv(TRAIN_DATA_PATH, index=False)
    test_df.to_csv(TEST_DATA_PATH, index=False)

    summary = {
        "raw_record_count": initial_count,
        "dropped_missing_target": dropped_target_na,
        "clean_record_count": len(df),
        "train_record_count": len(train_df),
        "test_record_count": len(test_df),
        "train_date_range": [str(train_df['date'].min()), str(train_df['date'].max())],
        "test_date_range": [str(test_df['date'].min()), str(test_df['date'].max())],
        "features": [
            "department",
            "arrival_hour",
            "arrival_dayofweek",
            "is_weekend",
            "patient_age",
            "patient_gender",
            "patients_ahead",
            "triage_priority"
        ],
        "target": "patient_waittime"
    }

    with open(SUMMARY_PATH, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    print(f"Train split saved: {TRAIN_DATA_PATH} ({len(train_df)} rows)")
    print(f"Test split saved: {TEST_DATA_PATH} ({len(test_df)} rows)")
    print(f"Preprocessing summary saved: {SUMMARY_PATH}")

    return train_df, test_df, summary


if __name__ == '__main__':
    preprocess_data()

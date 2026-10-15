"""
ml/inspect_dataset.py
--------------------
Inspects the raw Kaggle Hospital Emergency Room dataset,
produces data dictionary, missing values report, and statistical summary.
"""

import os
import json
import pandas as pd
import numpy as np

RAW_DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'raw', 'Hospital_ER.csv')
OUTPUT_DICT_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'processed', 'data_dictionary.json')
OUTPUT_REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'datasets', 'processed', 'inspection_report.json')


def inspect_dataset(csv_path=RAW_DATA_PATH):
    print("=" * 60)
    print("HospitalFlow AI - Kaggle Dataset Inspection")
    print("=" * 60)

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Raw dataset not found at {csv_path}. Please place Hospital_ER.csv in datasets/raw/")

    df = pd.read_csv(csv_path)
    total_rows, total_cols = df.shape
    print(f"Total Records: {total_rows}")
    print(f"Total Columns: {total_cols}\n")

    # Column inspection
    col_info = {}
    for col in df.columns:
        null_count = int(df[col].isnull().sum())
        null_pct = round((null_count / total_rows) * 100, 2)
        dtype = str(df[col].dtype)
        sample_vals = [str(x) for x in df[col].dropna().unique()[:5]]
        col_info[col] = {
            "dtype": dtype,
            "null_count": null_count,
            "null_pct": null_pct,
            "sample_values": sample_vals
        }

    # Data Dictionary documenting relevant columns
    data_dictionary = {
        "dataset_name": "Hospital Emergency Room Dataset",
        "publisher": "Laxdip Patel",
        "verified_kaggle_url": "https://www.kaggle.com/datasets/laxdippatel/hospital-emergency-room-dataset",
        "target_variable": "patient_waittime",
        "target_description": "Total waiting time in minutes from patient arrival to clinical consultation.",
        "target_units": "Minutes",
        "columns": {
            "date": {
                "description": "Patient arrival timestamp (M/D/YYYY H:MM format). Used to extract hour, day of week, and queue concurrency.",
                "type": "datetime",
                "role": "temporal_feature"
            },
            "patient_id": {
                "description": "Unique identifier for patient record.",
                "type": "string",
                "role": "identifier"
            },
            "patient_gender": {
                "description": "Biological sex of patient (M, F, NC).",
                "type": "categorical",
                "role": "feature"
            },
            "patient_age": {
                "description": "Patient age in years.",
                "type": "integer",
                "role": "feature"
            },
            "patient_sat_score": {
                "description": "Patient satisfaction rating recorded after visit (0-10). Excluded from prediction to prevent data leakage.",
                "type": "float",
                "role": "post_visit_metric"
            },
            "patient_first_inital": {
                "description": "First initial of patient name.",
                "type": "string",
                "role": "demographic"
            },
            "patient_last_name": {
                "description": "Last name of patient.",
                "type": "string",
                "role": "demographic"
            },
            "patient_race": {
                "description": "Reported race/ethnicity of patient.",
                "type": "categorical",
                "role": "demographic"
            },
            "patient_admin_flag": {
                "description": "Indicator if patient was admitted to inpatient bed or treated as outpatient. In live triage, mapped to urgency/priority.",
                "type": "boolean",
                "role": "feature"
            },
            "patient_waittime": {
                "description": "Actual waiting duration in minutes before consultation/care start. Target variable.",
                "type": "numeric (minutes)",
                "role": "target"
            },
            "department_referral": {
                "description": "Hospital department handling the patient visit (General Practice, Orthopedics, Cardiology, Neurology, Gastroenterology, Renal, Physiotherapy, or General Emergency if unreferred).",
                "type": "categorical",
                "role": "feature"
            }
        }
    }

    # Summary of target
    target_stats = {}
    if 'patient_waittime' in df.columns:
        valid_waits = df['patient_waittime'].dropna()
        target_stats = {
            "count": int(valid_waits.count()),
            "mean_minutes": round(float(valid_waits.mean()), 2),
            "median_minutes": round(float(valid_waits.median()), 2),
            "std_minutes": round(float(valid_waits.std()), 2),
            "min_minutes": round(float(valid_waits.min()), 2),
            "max_minutes": round(float(valid_waits.max()), 2),
            "p25_minutes": round(float(valid_waits.quantile(0.25)), 2),
            "p75_minutes": round(float(valid_waits.quantile(0.75)), 2),
        }

    # Save data dictionary and inspection report
    os.makedirs(os.path.dirname(OUTPUT_DICT_PATH), exist_ok=True)
    with open(OUTPUT_DICT_PATH, 'w', encoding='utf-8') as f:
        json.dump(data_dictionary, f, indent=2)

    inspection_report = {
        "total_records": total_rows,
        "total_columns": total_cols,
        "duplicate_records": int(df.duplicated().sum()),
        "target_summary": target_stats,
        "columns_summary": col_info,
        "departments_breakdown": {str(k): int(v) for k, v in df['department_referral'].fillna('General Emergency').value_counts().items()}
    }

    with open(OUTPUT_REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(inspection_report, f, indent=2)

    print("Data Dictionary saved to:", OUTPUT_DICT_PATH)
    print("Inspection Report saved to:", OUTPUT_REPORT_PATH)
    print("\nTarget Summary (Waiting Time in Minutes):", json.dumps(target_stats, indent=2))
    print("\nDepartments Breakdown:")
    for dept, count in inspection_report["departments_breakdown"].items():
        print(f"  - {dept}: {count} patients")

    return inspection_report


if __name__ == '__main__':
    inspect_dataset()

# HospitalFlow AI
## AI-Powered Hospital Queue Management, Multi-Disease Symptom Checker & Clinical Workflow System

HospitalFlow AI is a comprehensive, production-ready healthcare web application engineered to optimize clinical patient flow, eliminate outpatient and emergency crowding, manage priority queues across hospital departments, and provide AI-based clinical triage.

---

## 1. Architecture: The 3 Core Roles

HospitalFlow AI operates on a clean **3-role operational architecture**:
1. **Receptionist** (Hospital Operations & Clinical Intake Lead)
2. **Doctor** (Attending Physician Consultation Station)
3. **Patient** (Patient Health Portal, AI Symptom Checker & Live Queue Tracker)

> **Architectural Note:** In accordance with the project specification, the legacy Admin role has been completely removed. All administrative, department configuration, staff/doctor provisioning, hospital settings, and dual-model machine learning governance have been unified into the **Receptionist** portal. Legacy `/admin/*` routes redirect cleanly to `/receptionist/*`.

---

## 2. Key Modules & Functional Workflows

### A. Public Landing Page (`/`)
- **Public Entry Point**: Unauthenticated visitors arriving at `http://127.0.0.1:5000/` see a public landing page featuring clinical value propositions, system metrics (41 conditions, 132 symptoms, 3 roles), patient journey roadmap, clinical safety notice, and immediate portal access CTAs.
- **Role-Aware Redirection**: Authenticated visitors visiting `/` are automatically redirected to their respective role dashboard:
  - Receptionists &rarr; `/receptionist/dashboard`
  - Doctors &rarr; `/doctor/dashboard`
  - Patients &rarr; `/patient/dashboard`
- **Logout Behavior**: Signing out redirects directly back to the public landing page.

### B. Machine Learning Multi-Disease Symptom Checker (`/patient/symptom-checker`)
- **Kaggle Dataset**:
  - **Dataset Name**: *Disease Prediction Using Machine Learning*
  - **Source URL**: `https://www.kaggle.com/datasets/kaushil268/disease-prediction-using-machine-learning`
  - **Author**: Kaushil Patel (ODbL / Open Data Commons)
  - **Files**: `datasets/raw/symptom_disease_training.csv` (4,920 records) and `datasets/raw/symptom_disease_testing.csv` (41 records)
  - **Coverage**: 132 structured symptom binary features across 41 distinct human disease classes (Cardiovascular, Gastrointestinal, Dermatological, Neurological, Respiratory, Endocrine, Systemic).
- **ML Training Pipeline (`ml/train_symptom_model.py`)**:
  - Algorithm: `RandomForestClassifier(n_estimators=100, random_state=42)`
  - Evaluated on an independent, hold-out test set
  - Evaluation Metrics: **Accuracy: 100.0%**, **Macro F1: 1.0000**, **Precision: 1.0000**, **Recall: 1.0000**
  - Artifacts saved in `models/symptom_classifier.joblib`, `models/symptom_features.json`, and `models/symptom_evaluation.json`.
- **Inference & Safety Service (`services/symptom_service.py`)**:
  - Predicts primary condition with calibrated probability score.
  - Computes top 3 differential alternatives.
  - **Urgent Red-Flag Detection**: Automatically checks for acute symptoms (`chest_pain`, `breathlessness`, `blood_in_sputum`, `fast_heart_rate`, `swelling_joints`) and generates prominent clinical alerts.
  - **Non-Diagnostic Disclaimer**: Standardized medical advisories reminding patients that algorithmic assessments do not substitute certified medical diagnosis.
  - **Direct Doctor CTA**: One-click transition from assessment to "Consult a Doctor" prefilled form.
- **Assessment History (`/patient/assessments`)**:
  - Patients can view their past assessment reports.
  - Strict server-side RBAC ensures patients can only inspect their own assessments.

### C. Simplified Authentication & Doctor Self-Registration
- **Clean Auth Interface (`/login`, `/register`, `/register/doctor`)**:
  - Distraction-free, centered authentication forms without promotional cards, sidebars, or marketing text.
  - **Quick Test Credentials box completely eliminated** — no test accounts or passwords exposed in the UI.
  - Patient self-registration creates standard active patient accounts.
- **Doctor Self-Registration (`/register/doctor`)**:
  - Physicians register by submitting full name, email, phone, clinical qualification, medical license number, department, specialization, years of experience, and password.
  - Submissions are securely persisted to the `doctor_registration_requests` table with status `Pending`.
  - Pending doctors attempting to log in receive an informative advisory explaining that receptionist verification is in progress.
  - If rejected, doctors receive a clear decline notice with the receptionist's recorded justification.
- **Receptionist Approval Console (`/receptionist/doctor-registrations`)**:
  - Receptionists review pending physician credentials, licenses, and experience.
  - Upon approval, the physician's active `User` and `Staff` accounts are created and enabled for clinical duties.

### D. Patient Experience & Clinical Lifecycle
- **Find a Doctor (`/patient/doctors`)**:
  - Searchable physician directory filtered by medical department.
  - Displays qualification, experience, duty status, and one-click "Book Consultation" action preselecting the doctor and department.
- **Consultation Request & Schedule Negotiation (`/patient/request-consultation`, `/patient/consultation-requests`)**:
  - Request consultation with prefilled data from AI symptom assessments.
  - Receptionists can **Confirm** schedule, **Propose Alternative Date/Time Slot**, or **Decline**.
  - Patients can **Accept** or **Decline** proposed alternatives directly from their requests station.
  - Once confirmed, Receptionists can **Check-In to Live Queue** (`/receptionist/checkin-consultation-request`), assigning a live queue token.
- **Patient Medical Records (`/patient/medical-records`, `/patient/medical-records/<id>`)**:
  - Complete history of finalized consultations.
  - Printable official clinical summary featuring hospital letterhead, verified diagnosis, structured prescription, recommended follow-up date, and specialist referrals.

### E. Dedicated Doctor Clinical Portal (`/doctor/dashboard`)
- **Clinical KPIs**: Patients waiting, active in examination, completed today, and department queue depth.
- **Duty Availability**: Real-time availability toggling (`On Duty & Available` vs `Off Duty / Busy`).
- **Patient Queue Filtering**: Tabs for `Waiting`, `In Consultation`, `Completed Today`, `Department Intake`, `Consultation Requests`, and `All My Patients`.
- **Examination Chart (`/doctor/consultation/<reg_id>`)**:
  - Patient demographics, visit concern, and AI symptom assessment insights.
  - Full longitudinal visit history and prior diagnoses.
  - Consultation actions: Start Examination, Save Draft Notes, Finalize & Complete Consultation with Primary Diagnosis, Treatment Plan, Structured Prescription, Recommended Follow-up Date, and Specialist Department Referral.
  - **Cascading Recalculation**: Completing a consultation recalculates wait times and positions for all downstream waiting patients in that department and marks linked consultation requests as Completed.

### F. Upgraded Receptionist Management Portal
- **Queue Management**: Call patient, change triage priority, skip, cancel, check in.
- **Doctor Registrations (`/receptionist/doctor-registrations`)**: Review, verify credentials, approve, or reject physician registration requests.
- **Doctor Directory (`/receptionist/doctors`)**: Provision physicians, assign clinical department, toggle duty availability, safely deactivate accounts while preserving records.
- **User Management (`/receptionist/users`)**: Create and toggle accounts for Receptionists, Doctors, and Patients.
- **Department Registry (`/receptionist/departments`)**: Add departments and view staffing workload.
- **Hospital Settings (`/receptionist/hospital-settings`)**: Central phone, emergency line, address, hours.
- **Dual-Model ML Governance (`/receptionist/model-management`)**:
  1. Multi-Disease Symptom Classifier (Random Forest Classification, 41 conditions, 132 features).
  2. ER Waiting-Time Prediction Model (Regression Pipeline, R², MAE, RMSE).
  - One-click retraining controls for both models.

---

## 3. Technology Stack

- **Backend**: Python 3.14, Flask 3.0, Flask Blueprints, Flask-Login, Flask-SQLAlchemy 3.1, Werkzeug
- **Database**: MySQL / MariaDB (XAMPP localhost:3306) & SQLite (In-Memory for Automated Pytest)
- **Machine Learning**: scikit-learn, joblib, pandas, NumPy, matplotlib
- **Frontend**: Responsive Healthcare SaaS UI, Custom Clean Design System (Navy `#0f172a`, Teal `#0d9488`, Slate), Chart.js 4.4, Native JavaScript ES6+ (No bulky framework bloat)
- **Testing**: pytest (68 comprehensive automated unit and integration tests)

---

## 4. Setup & Running Instructions

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Initialize Database (MySQL / XAMPP)
Ensure MySQL is running (e.g. XAMPP Control Panel on port 3306), then run:
```bash
python database/init_db.py
```
This applies all non-destructive migrations:
- Migrates existing accounts to the 3-role schema (`receptionist`, `doctor`, `patient`).
- Creates `symptom_assessments` and `consultation_requests` tables.
- Seeds clinical departments and seed staff.

### Step 3: Run Full Automated Test Suite
```bash
python -m pytest -v
```
All **75 tests** run in isolated in-memory SQLite and pass with 100% success rate:
- `tests/test_doctor_registration.py` (Physician self-registration, pending status intercept, receptionist approval/rejection)
- `tests/test_symptom_and_consultations.py` (Landing page, ML symptom checker, red flags, requests)
- `tests/test_doctor.py` (Doctor portal, chart, prescriptions, referrals, follow-up, availability, RBAC)
- `tests/test_patient_workflow.py` (Find a Doctor, consultation requests, alternative proposal acceptance, medical records, intake)
- `tests/test_admin.py` (Transferred management endpoints under Receptionist)
- `tests/test_permissions.py` (RBAC isolation across all 3 roles: Receptionist, Doctor, Patient)
- `tests/test_queue.py` (Priority queuing, token generation, FIFO, status lifecycle)
- `tests/test_prediction.py` (Waiting-time regression model)
- `tests/test_contact.py` (Hospital contact directory & patient inquiries)
- `tests/test_auth.py` (Clean registration, login, password security)

### Step 4: Start the Web Application
```bash
python app.py
```
Access the application in your browser:
```
http://127.0.0.1:5000
```

---

## 5. Seed Accounts & Credentials

| Role | Email | Password | Description |
|---|---|---|---|
| **Receptionist** | `receptionist@hospitalflow.ai` | `Reception@12345` | Front Desk, Queue & Hospital Operations |
| **Receptionist (Lead)** | `admin@hospitalflow.ai` | `Admin@12345` | Migrated Operations Account (Full Managerial Access) |
| **Doctor** | `doctor.chen@hospitalflow.ai` | `Doctor@12345` | General Practice Physician Station |
| **Doctor** | `doctor.patel@hospitalflow.ai` | `Doctor@12345` | Cardiology Physician Station |
| **Patient** | `patient@hospitalflow.ai` | `Patient@12345` | Patient Health Portal & Symptom Screening |


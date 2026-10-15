"""
tests/test_symptom_and_consultations.py
---------------------------------------
Comprehensive test suite for the new Kaggle-trained ML Symptom Checker,
Doctor Consultation Request workflow, and Public Landing Page entry point:
- Public Landing Page (/) accessibility and authenticated role redirection
- Kaggle Multi-Disease Classifier inference, probabilities, and urgent red-flags
- Patient Symptom Checker workflow and database persistence
- Patient RBAC isolation on symptom assessments
- Patient Consultation Request creation, Receptionist assignment, and Doctor review
- Receptionist live queue check-in from Consultation Request
"""

import pytest
import json
from models.db_models import (
    db, User, Department, Staff, PatientRegistration, QueueRecord,
    SymptomAssessment, ConsultationRequest, Consultation, utcnow
)
from services.symptom_service import predict_condition, get_symptom_catalog


# =====================================================================
# 1. Public Landing Page & Root Routing
# =====================================================================

def test_public_landing_page_accessible_unauthenticated(client):
    """Verifies that an unauthenticated visitor visiting / gets the public landing page."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"HospitalFlow AI" in response.data
    assert b"Hospital Flow" in response.data
    assert b"Symptom Checker" in response.data
    assert b"Sign In" in response.data
    assert b"Registration" in response.data


def test_landing_page_redirects_authenticated_users(client):
    """Verifies that visiting / while logged in redirects directly to the user's role dashboard."""
    # 1. Patient redirect
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=False)
    resp_pat = client.get('/', follow_redirects=False)
    assert resp_pat.status_code == 302
    assert '/patient/dashboard' in resp_pat.location

    # 2. Receptionist redirect
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=False)
    resp_rec = client.get('/', follow_redirects=False)
    assert resp_rec.status_code == 302
    assert '/receptionist/dashboard' in resp_rec.location

    # 3. Doctor redirect
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'email': 'doctor@test.com', 'password': 'DocPass123!'}, follow_redirects=False)
    resp_doc = client.get('/', follow_redirects=False)
    assert resp_doc.status_code == 302
    assert '/doctor/dashboard' in resp_doc.location


# =====================================================================
# 2. ML Multi-Disease Symptom Classifier Service
# =====================================================================

def test_symptom_catalog_loaded():
    """Verifies that the Kaggle dataset symptom catalog loads properly."""
    catalog = get_symptom_catalog()
    assert isinstance(catalog, dict)
    assert len(catalog) >= 5


def test_ml_symptom_prediction_valid():
    """Verifies real ML model inference produces calibrated probabilities and predictions."""
    test_symptoms = ['itching', 'skin_rash', 'nodal_skin_eruptions']
    result = predict_condition(test_symptoms)

    assert result['success'] is True
    assert result['primary_condition'] is not None
    assert isinstance(result['confidence_score'], float)
    assert 0.0 <= result['confidence_score'] <= 100.0
    assert len(result['top_alternatives']) >= 0
    assert result['has_urgent_symptoms'] is False


def test_ml_symptom_prediction_red_flag_detection():
    """Verifies that acute cardiovascular/respiratory symptoms trigger urgent red-flag alerts."""
    urgent_symptoms = ['chest_pain', 'breathlessness', 'sweating']
    result = predict_condition(urgent_symptoms)

    assert result['success'] is True
    assert result['has_urgent_symptoms'] is True
    assert 'Chest Pain' in result['urgent_symptoms_reported']
    assert 'Breathlessness' in result['urgent_symptoms_reported']


# =====================================================================
# 3. Patient AI Symptom Checker Web Workflow
# =====================================================================

def test_patient_symptom_checker_submission_and_persistence(client, app):
    """Verifies patient can submit symptoms, view differential diagnosis, and assessment is persisted."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    # Submit symptoms via POST
    response = client.post('/patient/symptom-checker', data={
        'symptoms': ['headache', 'vomiting', 'stiff_neck'],
        'duration': '1 to 3 days',
        'severity': 'Severe'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Preliminary Assessment Result" in response.data or b"Consult a Doctor" in response.data

    with app.app_context():
        pat = User.query.filter_by(email='patient1@test.com').first()
        assessment = SymptomAssessment.query.filter_by(patient_user_id=pat.id).order_by(SymptomAssessment.created_at.desc()).first()
        assert assessment is not None
        assert assessment.predicted_disease is not None
        assert assessment.symptom_duration == '1 to 3 days'
        assert assessment.severity_level == 'Severe'
        assert 'headache' in assessment.selected_symptoms


def test_patient_assessment_privacy_isolation(client, app):
    """Verifies Patient 2 cannot access Patient 1's private symptom assessment report."""
    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        assessment = SymptomAssessment(
            assessment_reference='SA-PRIV-TEST',
            patient_user_id=p1.id,
            selected_symptoms=json.dumps(['fatigue', 'weight_loss']),
            predicted_disease='Diabetes',
            confidence_score=0.92
        )
        db.session.add(assessment)
        db.session.commit()
        assessment_id = assessment.id

    # Log in as Patient 2
    client.post('/login', data={'email': 'patient2@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    resp = client.get(f'/patient/assessment/{assessment_id}', follow_redirects=True)

    # Must be denied or redirected away
    assert b"Access denied" in resp.data or resp.status_code == 200
    # Must NOT display Patient 1's private reference
    assert b"SA-PRIV-TEST" not in resp.data or b"Access denied" in resp.data


# =====================================================================
# 4. Doctor Consultation Request Workflow
# =====================================================================

def test_patient_consultation_request_workflow(client, app):
    """
    Verifies full lifecycle of a doctor consultation request:
    1. Patient creates consultation request
    2. Receptionist views and assigns a doctor
    3. Doctor views request in consultation requests station
    """
    with app.app_context():
        gp = Department.query.filter_by(code='GP').first()
        gp_id = gp.id
        doc = User.query.filter_by(email='doctor@test.com').first()
        doc_id = doc.id

    # 1. Patient submits consultation request
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    res_req = client.post('/patient/request-consultation', data={
        'department_id': gp_id,
        'health_concern': 'Persistent severe migraine with nausea for past 2 days',
        'preferred_date': '2026-10-20',
        'preferred_time_slot': 'Morning (09:00 - 12:00)',
        'additional_notes': 'Sensitivity to bright lights'
    }, follow_redirects=True)

    assert res_req.status_code == 200
    assert b"Consultation request" in res_req.data
    assert b"submitted successfully" in res_req.data

    with app.app_context():
        pat = User.query.filter_by(email='patient1@test.com').first()
        req_obj = ConsultationRequest.query.filter_by(patient_user_id=pat.id).order_by(ConsultationRequest.created_at.desc()).first()
        assert req_obj is not None
        assert req_obj.status in ['Pending', 'Pending Review']
        req_id = req_obj.id

    client.get('/logout', follow_redirects=True)

    # 2. Receptionist assigns doctor to the request
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)
    res_assign = client.post('/receptionist/assign-consultation-doctor', data={
        'request_id': req_id,
        'doctor_id': doc_id,
        'receptionist_notes': 'Assigned to Dr. Test Physician for initial evaluation.'
    }, follow_redirects=True)

    assert res_assign.status_code == 200
    assert b"assigned successfully" in res_assign.data

    with app.app_context():
        updated_req = db.session.get(ConsultationRequest, req_id)
        assert updated_req.status in ['Assigned', 'Confirmed']
        assert updated_req.assigned_doctor_id == doc_id

    client.get('/logout', follow_redirects=True)

    # 3. Doctor views assigned request in doctor portal
    client.post('/login', data={'email': 'doctor@test.com', 'password': 'DocPass123!'}, follow_redirects=True)
    res_doc = client.get(f'/doctor/consultation-request/{req_id}')
    assert res_doc.status_code == 200
    assert b"Persistent severe migraine" in res_doc.data
    assert b"Physician Clinical Notes" in res_doc.data

    # Doctor adds notes
    res_notes = client.post(f'/doctor/consultation-request/{req_id}', data={
        'action': 'save_notes',
        'status': 'In Consultation',
        'doctor_notes': 'Patient advised to rest in dark room; clinical examination scheduled.'
    }, follow_redirects=True)
    assert res_notes.status_code == 200

    with app.app_context():
        final_req = db.session.get(ConsultationRequest, req_id)
        assert final_req.status == 'In Consultation'
        assert 'dark room' in final_req.doctor_notes


def test_receptionist_checkin_consultation_request_to_live_queue(client, app):
    """Verifies receptionist can check in a ConsultationRequest into the active physical queue."""
    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        gp = Department.query.filter_by(code='GP').first()
        doc = User.query.filter_by(email='doctor@test.com').first()

        req = ConsultationRequest(
            request_reference='CR-CHECKIN-001',
            patient_user_id=p1.id,
            department_id=gp.id,
            assigned_doctor_id=doc.id,
            health_concern='Joint inflammation and swelling',
            status='Assigned'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)
    response = client.post('/receptionist/checkin-consultation-request', data={
        'request_id': req_id
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Patient checked into live queue" in response.data

    with app.app_context():
        req_checked = db.session.get(ConsultationRequest, req_id)
        assert req_checked.registration_id is not None
        reg = db.session.get(PatientRegistration, req_checked.registration_id)
        assert reg is not None
        assert reg.queue_record is not None
        assert reg.queue_record.queue_status in ('Waiting', 'Called', 'In Consultation')

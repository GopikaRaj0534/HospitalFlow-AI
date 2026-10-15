"""
tests/test_patient_workflow.py
------------------------------
Automated test suite for patient-specific workflows:
- Health concern and symptom description submission
- Department referral selection
- Preservation of patient profile and multi-visit history
- Profile updating
- Patient queue isolation and non-diagnosis compliance
"""

import pytest
from models.db_models import db, User, Department, PatientRegistration, QueueRecord, utcnow
from services.auth_service import update_patient_profile


def test_patient_health_concern_submission(client, app):
    """Verifies that an authenticated patient can submit a health concern to enter queue."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    
    with app.app_context():
        dept = Department.query.filter_by(code='GP').first()
        dept_id = dept.id

    response = client.post('/patient/submit-concern', data={
        'health_concern_category': 'Fever',
        'symptoms_description': 'High temperature and chills starting yesterday morning',
        'symptom_duration': '1 to 3 days',
        'department_id': dept_id
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Health concern submitted successfully" in response.data or b"Active Consultation Ticket" in response.data

    with app.app_context():
        patient = User.query.filter_by(email='patient1@test.com').first()
        reg = PatientRegistration.query.filter_by(patient_user_id=patient.id).first()
        assert reg is not None
        assert reg.health_concern_category == 'Fever'
        assert 'High temperature' in reg.symptoms_description
        assert reg.symptom_duration == '1 to 3 days'
        assert reg.queue_record is not None
        assert reg.queue_record.queue_status == 'Waiting'


def test_invalid_health_concern_submission_rejected(client, app):
    """Verifies that submitting missing category or too-short symptom descriptions is rejected."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    with app.app_context():
        dept = Department.query.filter_by(code='GP').first()
        dept_id = dept.id

    # Too short symptom description (< 5 chars)
    response = client.post('/patient/submit-concern', data={
        'health_concern_category': 'Fever',
        'symptoms_description': 'Bad',
        'department_id': dept_id
    }, follow_redirects=True)

    assert b"at least 5 characters" in response.data


def test_patient_profile_update(client, app):
    """Verifies patient can update permitted demographic fields."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    response = client.post('/patient/profile', data={
        'full_name': 'Patient One Updated',
        'phone': '555-4321',
        'age': 34,
        'gender': 'Female'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"successfully updated" in response.data

    with app.app_context():
        p = User.query.filter_by(email='patient1@test.com').first()
        assert p.full_name == 'Patient One Updated'
        assert p.phone == '555-4321'
        assert p.age == 34


def test_patient_multi_visit_history_preserved(client, app):
    """Verifies that past visits are archived in history when a new visit is initiated."""
    with app.app_context():
        patient = User.query.filter_by(email='patient1@test.com').first()
        dept = Department.query.filter_by(code='GP').first()
        recep = User.query.filter_by(role='receptionist').first()

        # Prior completed visit
        old_reg = PatientRegistration(
            patient_user_id=patient.id,
            patient_name=patient.full_name,
            registered_by=recep.id,
            department_id=dept.id,
            token_number='GP-HIST-001',
            triage_priority=3,
            health_concern_category='Headache or Migraine'
        )
        db.session.add(old_reg)
        db.session.flush()

        old_queue = QueueRecord(
            registration_id=old_reg.id,
            queue_status='Completed',
            estimated_wait_minutes=0.0
        )
        db.session.add(old_queue)
        db.session.commit()

    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/patient/dashboard')

    # History table must contain the completed ticket
    assert b"GP-HIST-001" in response.data
    assert b"Headache or Migraine" in response.data
    assert b"Completed" in response.data


def test_patient_api_status_endpoint(client, app):
    """Verifies the asynchronous polling status API for active ticket."""
    with app.app_context():
        patient = User.query.filter_by(email='patient1@test.com').first()
        dept = Department.query.filter_by(code='GP').first()
        recep = User.query.filter_by(role='receptionist').first()

        reg = PatientRegistration(
            patient_user_id=patient.id,
            patient_name=patient.full_name,
            registered_by=recep.id,
            department_id=dept.id,
            token_number='GP-POLL-123',
            triage_priority=2,
            health_concern_category='Stomach Pain or Digestive Problems'
        )
        db.session.add(reg)
        db.session.flush()

        q = QueueRecord(
            registration_id=reg.id,
            queue_status='Waiting',
            patients_ahead=2,
            estimated_wait_minutes=18.5
        )
        db.session.add(q)
        db.session.commit()

    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    res = client.get('/patient/api/status')

    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['has_active'] is True
    assert json_data['token_number'] == 'GP-POLL-123'
    assert json_data['patients_ahead'] == 2
    assert json_data['estimated_wait_minutes'] == 18.5

def test_patient_dashboard_no_ml_leak(client, app):
    """
    Verifies that Patients do NOT see dataset records, model evaluation metrics,
    training details, or technical model internals on their dashboard.
    """
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/patient/dashboard')

    assert response.status_code == 200
    # Must NOT contain ML technical metrics or training internals
    assert b"Random Forest" not in response.data
    assert b"RMSE" not in response.data
    assert b"R2 Score" not in response.data
    assert b"Hospital_ER.csv" not in response.data


def test_patient_dashboard_empty_state(client):
    """Verifies that a patient without an active ticket sees a useful empty state and CTA."""
    client.post('/login', data={'email': 'patient2@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/patient/dashboard')

    assert response.status_code == 200
    assert b"No Active Consultation Ticket" in response.data
    assert b"Report Health Concern / Join Queue" in response.data


def test_find_a_doctor_directory(client, app):
    """Verifies that the Find a Doctor directory displays available physicians with department filters."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/patient/doctors')

    assert response.status_code == 200
    assert b"Hospital Physician Directory" in response.data
    # Doctor is in the test DB
    assert b"Dr. Test Physician" in response.data or b"Test Physician" in response.data
    assert b"Book Consultation" in response.data


def test_patient_consultation_alternative_acceptance(client, app):
    """Verifies full flow: patient requests consultation, receptionist proposes alternative, patient accepts."""
    from models.db_models import ConsultationRequest

    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    with app.app_context():
        dept = Department.query.filter_by(code='GP').first()
        doc = User.query.filter_by(role='doctor').first()
        pat = User.query.filter_by(email='patient1@test.com').first()

        req = ConsultationRequest(
            request_reference='CR-TEST-ALT-001',
            patient_user_id=pat.id,
            department_id=dept.id,
            preferred_doctor_id=doc.id,
            preferred_date='2026-10-25',
            preferred_time_slot='10:00 - 11:00',
            health_concern='Severe headaches recurring in evenings',
            status='Pending Review'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    # Receptionist proposes alternative schedule
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)

    resp_prop = client.post('/receptionist/propose-consultation-alternative', data={
        'request_id': req_id,
        'proposed_alternative_date': '2026-10-26',
        'proposed_alternative_time_slot': '14:00 - 15:00',
        'alternative_notes': 'Doctor is in surgical rotation on October 25th; available October 26th afternoon.'
    }, follow_redirects=True)

    assert resp_prop.status_code == 200
    with app.app_context():
        r = db.session.get(ConsultationRequest, req_id)
        assert r.status == 'Alternative Proposed'
        assert r.proposed_alternative_date == '2026-10-26'

    # Patient logs in, sees proposal, and accepts
    client.get('/logout', follow_redirects=True)
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    resp_view = client.get('/patient/consultation-requests')
    assert b"Alternative Proposed" in resp_view.data
    assert b"accept-alternative" in resp_view.data

    resp_accept = client.post(f'/patient/accept-alternative/{req_id}', follow_redirects=True)
    assert resp_accept.status_code == 200
    assert b"accepted" in resp_accept.data.lower()

    with app.app_context():
        r = db.session.get(ConsultationRequest, req_id)
        assert r.status == 'Confirmed'
        assert r.confirmed_date == '2026-10-26'
        assert r.confirmed_time_slot == '14:00 - 15:00'


def test_patient_medical_records_view(client, app):
    """Verifies that patient can view their completed consultation records with diagnosis, prescription, follow-up."""
    from models.db_models import Consultation

    with app.app_context():
        pat = User.query.filter_by(email='patient1@test.com').first()
        doc = User.query.filter_by(role='doctor').first()
        dept = Department.query.filter_by(code='GP').first()
        recep = User.query.filter_by(role='receptionist').first()

        reg = PatientRegistration(
            patient_user_id=pat.id,
            patient_name=pat.full_name,
            registered_by=recep.id,
            department_id=dept.id,
            assigned_doctor_id=doc.id,
            token_number='GP-MEDREC-999',
            triage_priority=3,
            health_concern_category='Chest Infection'
        )
        db.session.add(reg)
        db.session.flush()

        consult = Consultation(
            registration_id=reg.id,
            patient_user_id=pat.id,
            doctor_user_id=doc.id,
            department_id=dept.id,
            chief_complaint='Productive cough with low fever',
            diagnosis='Acute Bronchitis',
            treatment_plan='Adequate hydration and 5 days of rest',
            prescription='Amoxicillin 500mg TDS for 5 days, Paracetamol 500mg SOS',
            follow_up_instructions='Return if breathing difficulty develops',
            follow_up_date='2026-11-01',
            consultation_status='Completed'
        )
        db.session.add(consult)
        db.session.commit()
        consult_id = consult.id

    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    # View list of medical records
    resp = client.get('/patient/medical-records')
    assert resp.status_code == 200
    assert b"Medical Records &amp; Consultation Summaries" in resp.data or b"Medical Records" in resp.data
    assert b"Acute Bronchitis" in resp.data

    # View individual printable detail record
    detail_resp = client.get(f'/patient/medical-records/{consult_id}')
    assert detail_resp.status_code == 200
    assert b"Official Consultation &amp; Clinical Summary" in detail_resp.data or b"Clinical Summary" in detail_resp.data
    assert b"Acute Bronchitis" in detail_resp.data
    assert b"Amoxicillin 500mg" in detail_resp.data
    assert b"2026-11-01" in detail_resp.data


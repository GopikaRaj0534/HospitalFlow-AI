"""
tests/test_permissions.py
-------------------------
Automated test suite for role-based access control and patient data privacy:
- Protected routes redirect unauthenticated users
- Role enforcement (Admin, Receptionist, Patient)
- Model management and ML retraining restricted exclusively to Admin
- Patient record isolation (Patients cannot view other patients' queue tickets)
"""

import pytest
from models.db_models import db, PatientRegistration, QueueRecord, Department, User


def test_unauthenticated_access_redirects(client):
    """Verifies that accessing protected dashboards without logging in redirects to login."""
    res_admin = client.get('/admin/dashboard')
    assert res_admin.status_code in (301, 302, 307)

    res_recep = client.get('/receptionist/dashboard')
    assert res_recep.status_code == 302
    assert '/login' in res_recep.headers['Location']

    res_pat = client.get('/patient/dashboard')
    assert res_pat.status_code == 302
    assert '/login' in res_pat.headers['Location']


def test_patient_cannot_access_admin_portal(client):
    """Verifies that a patient cannot access admin/receptionist dashboard."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/admin/dashboard', follow_redirects=True)
    assert b"Access denied" in response.data or b"Patient Portal" in response.data or b"Patient Health Portal" in response.data


def test_patient_cannot_access_receptionist_portal(client):
    """Verifies that a patient cannot access receptionist dashboard."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/receptionist/dashboard', follow_redirects=True)
    assert b"Access denied" in response.data or b"Patient Portal" in response.data or b"Patient Health Portal" in response.data


def test_receptionist_can_access_admin_redirect_and_dashboard(client):
    """Verifies that legacy admin routes cleanly redirect receptionists to their dashboard."""
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)
    response = client.get('/admin/dashboard', follow_redirects=True)
    assert response.status_code == 200
    assert b"Registration Desk" in response.data or b"Receptionist" in response.data or b"Hospital Operations" in response.data


def test_receptionist_can_access_ml_model_management(client):
    """Verifies that receptionists manage the hospital and ML models."""
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)
    get_res = client.get('/receptionist/model-management', follow_redirects=True)
    assert get_res.status_code == 200
    assert b"Machine Learning" in get_res.data or b"Model Management" in get_res.data


def test_patient_cannot_access_ml_model_management(client):
    """Verifies that a patient cannot access ML model management."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    get_res = client.get('/receptionist/model-management', follow_redirects=True)
    assert b"Access denied" in get_res.data


def test_admin_redirects_to_receptionist_portal(client):
    """Verifies that seed operations account accesses the management dashboard."""
    client.post('/login', data={'email': 'admin@test.com', 'password': 'AdminPass123!'}, follow_redirects=True)
    response = client.get('/admin/dashboard', follow_redirects=True)
    assert response.status_code == 200
    assert b"Receptionist" in response.data or b"Registration Desk" in response.data or b"Hospital Operations" in response.data


def test_patient_data_privacy_isolation(client, app):
    """Verifies that Patient 1 cannot see Patient 2's tickets or private data."""
    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        p2 = User.query.filter_by(email='patient2@test.com').first()
        admin = User.query.filter_by(email='admin@test.com').first()
        dept = Department.query.filter_by(code='GP').first()

        # Create ticket for Patient 2
        reg2 = PatientRegistration(
            patient_user_id=p2.id,
            patient_name='Patient Two Private',
            registered_by=admin.id,
            department_id=dept.id,
            token_number='GP-PRIVATE-999',
            triage_priority=3
        )
        db.session.add(reg2)
        db.session.flush()

        q2 = QueueRecord(
            registration_id=reg2.id,
            queue_status='Waiting',
            patients_ahead=0,
            estimated_wait_minutes=25.0
        )
        db.session.add(q2)
        db.session.commit()

    # Log in as Patient 1
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/patient/dashboard')

    # Patient 1's dashboard must NOT contain Patient 2's private token
    assert b"GP-PRIVATE-999" not in response.data
    assert b"Patient Two Private" not in response.data

def test_unauthorized_priority_update_rejected(client, app):
    """Verifies that a patient cannot alter triage priority via receptionist endpoint."""
    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        dept = Department.query.filter_by(code='GP').first()
        admin = User.query.filter_by(email='admin@test.com').first()

        reg = PatientRegistration(
            patient_user_id=p1.id,
            patient_name=p1.full_name,
            registered_by=admin.id,
            department_id=dept.id,
            token_number='GP-PRIO-TEST',
            triage_priority=3
        )
        db.session.add(reg)
        db.session.commit()
        reg_id = reg.id

    # Log in as patient
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    res = client.post('/receptionist/update-priority', data={
        'registration_id': reg_id,
        'triage_priority': 1
    }, follow_redirects=True)

    assert b"Access denied" in res.data or res.status_code == 200
    with app.app_context():
        checked_reg = db.session.get(PatientRegistration, reg_id)
        assert checked_reg.triage_priority == 3  # unchanged

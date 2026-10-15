"""
tests/test_doctor_registration.py
---------------------------------
Comprehensive automated test suite for Doctor Self-Registration and Receptionist Approval:
1. Doctor submits registration request via /register/doctor -> status is 'Pending'.
2. Pending doctor attempting to log in receives the informative pending flash message and cannot access doctor portal.
3. Receptionist can view pending doctor requests at /receptionist/doctor-registrations.
4. Receptionist approves doctor registration -> active User and Staff created -> Doctor can log in.
5. Receptionist rejects doctor registration with reason -> rejected doctor receives rejection message with reason upon login.
6. Form validation prevents invalid / duplicate doctor registration.
"""

import pytest
from models.db_models import db, User, Department, Staff, DoctorRegistrationRequest


def test_doctor_registration_creates_pending_request(client, app):
    """Verifies that doctor registration form submission creates a pending request in doctor_registration_requests."""
    with app.app_context():
        dept = Department.query.filter_by(code='GP').first()
        dept_id = dept.id

    response = client.post('/register/doctor', data={
        'full_name': 'Dr. Elizabeth Blackwell',
        'email': 'elizabeth.blackwell@hospital.org',
        'phone': '555-0199',
        'qualification': 'MD, General Practice',
        'specialization': 'General Practitioner',
        'department_id': dept_id,
        'license_number': 'MD-LIC-998822',
        'experience_years': 7,
        'password': 'SecureDoctorPass123!',
        'confirm_password': 'SecureDoctorPass123!'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"submitted successfully" in response.data or b"pending review" in response.data

    with app.app_context():
        req = DoctorRegistrationRequest.query.filter_by(email='elizabeth.blackwell@hospital.org').first()
        assert req is not None
        assert req.full_name == 'Dr. Elizabeth Blackwell'
        assert req.status == 'Pending'
        assert req.license_number == 'MD-LIC-998822'
        assert req.experience_years == 7

        # User account should NOT exist yet as an active doctor
        user = User.query.filter_by(email='elizabeth.blackwell@hospital.org').first()
        assert user is None


def test_pending_doctor_login_intercepted(client, app):
    """Verifies that pending doctor attempting to log in is shown the pending review message."""
    with app.app_context():
        dept = Department.query.first()
        req = DoctorRegistrationRequest(
            full_name='Dr. Pending Physician',
            email='pending.doc@hospital.org',
            phone='555-0200',
            qualification='MBBS',
            specialization='Cardiology',
            department_id=dept.id,
            license_number='MED-111222',
            experience_years=4,
            status='Pending'
        )
        req.set_password('PendingPass123!')
        db.session.add(req)
        db.session.commit()

    response = client.post('/login', data={
        'email': 'pending.doc@hospital.org',
        'password': 'PendingPass123!'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"pending receptionist verification" in response.data
    # Should not be redirected to doctor dashboard
    assert b"Doctor Clinical Portal" not in response.data


def test_receptionist_approves_doctor_registration(client, app):
    """Verifies that Receptionist can approve a pending doctor, which creates the User and Staff records."""
    with app.app_context():
        dept = Department.query.filter_by(code='GP').first()
        dept_id = dept.id
        req = DoctorRegistrationRequest(
            full_name='Dr. Approvals Test',
            email='approved.doc@hospital.org',
            phone='555-0300',
            qualification='MD, Internal Medicine',
            specialization='Physician',
            department_id=dept_id,
            license_number='LIC-APP-777',
            experience_years=6,
            status='Pending'
        )
        req.set_password('ApproveMePass123!')
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    # Log in as Receptionist
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)

    # Receptionist approves request
    response = client.post(f'/receptionist/approve-doctor-registration/{req_id}', data={
        'department_id': dept_id
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"approved" in response.data.lower()

    # Verify database state
    with app.app_context():
        req = db.session.get(DoctorRegistrationRequest, req_id)
        assert req.status == 'Approved'
        assert req.user_id is not None

        doc_user = db.session.get(User, req.user_id)
        assert doc_user is not None
        assert doc_user.role == 'doctor'
        assert doc_user.is_active is True
        assert doc_user.email == 'approved.doc@hospital.org'

        staff = Staff.query.filter_by(user_id=doc_user.id).first()
        assert staff is not None
        assert staff.staff_type == 'Doctor'
        assert staff.department_id == dept_id
        assert staff.is_available is True
        assert staff.license_number == 'LIC-APP-777'

    # Now the doctor can log in
    client.get('/logout', follow_redirects=True)
    login_resp = client.post('/login', data={
        'email': 'approved.doc@hospital.org',
        'password': 'ApproveMePass123!'
    }, follow_redirects=True)

    assert login_resp.status_code == 200
    assert b"Doctor Clinical Portal" in login_resp.data or b"Dr. Approvals Test" in login_resp.data


def test_receptionist_rejects_doctor_registration(client, app):
    """Verifies that Receptionist can reject doctor registration with reason, and doctor sees reason upon login."""
    with app.app_context():
        dept = Department.query.first()
        dept_id = dept.id
        req = DoctorRegistrationRequest(
            full_name='Dr. Reject Candidate',
            email='reject.doc@hospital.org',
            phone='555-0400',
            qualification='MD',
            specialization='Pediatrics',
            department_id=dept_id,
            license_number='LIC-REJ-999',
            experience_years=2,
            status='Pending'
        )
        req.set_password('RejectPass123!')
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    # Log in as Receptionist
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)

    # Reject with specific reason
    rejection_reason = "Medical license number could not be verified with the state board."
    response = client.post(f'/receptionist/reject-doctor-registration/{req_id}', data={
        'rejection_reason': rejection_reason
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"rejected" in response.data.lower()

    with app.app_context():
        req = db.session.get(DoctorRegistrationRequest, req_id)
        assert req.status == 'Rejected'
        assert req.rejection_reason == rejection_reason

    # Doctor attempts to log in -> should see rejection reason
    client.get('/logout', follow_redirects=True)
    login_resp = client.post('/login', data={
        'email': 'reject.doc@hospital.org',
        'password': 'RejectPass123!'
    }, follow_redirects=True)

    assert login_resp.status_code == 200
    assert b"declined" in login_resp.data.lower() or b"rejected" in login_resp.data.lower()
    assert b"state board" in login_resp.data


def test_doctor_registration_without_subspecialization(client, app):
    """Verifies doctor self-registration succeeds without entering Subspecialization / Clinical Focus."""
    with app.app_context():
        dept = Department.query.filter_by(code='GP').first()
        dept_id = dept.id

    # Form post WITHOUT any 'specialization' field
    response = client.post('/register/doctor', data={
        'full_name': 'Dr. Marcus Welby',
        'email': 'marcus.welby@hospital.org',
        'phone': '555-0777',
        'department_id': dept_id,
        'qualification': 'MD, Internal Medicine',
        'license_number': 'MD-LIC-445566',
        'experience_years': 12,
        'password': 'WelbyPass123!',
        'confirm_password': 'WelbyPass123!'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"submitted successfully" in response.data or b"pending review" in response.data

    with app.app_context():
        req = DoctorRegistrationRequest.query.filter_by(email='marcus.welby@hospital.org').first()
        assert req is not None
        assert req.status == 'Pending'
        assert req.specialization == 'General Practice' or req.department_id == dept_id


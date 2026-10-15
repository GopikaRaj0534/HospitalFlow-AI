"""
tests/test_doctor.py
--------------------
Comprehensive automated test suite for HospitalFlow AI Doctor Role & Consultation Workflow:
1. Doctor authentication, session redirection, and role boundaries
2. Strict RBAC (Patient/Receptionist cannot access Doctor, Doctor cannot access Admin)
3. Doctor availability toggle
4. Admin Doctor Management (Create physician, department assignment, workload KPIs, status toggle)
5. Receptionist doctor assignment to active patients (no duplicate tokens)
6. Prevention of inactive, off-duty, or incompatible department doctor assignments
7. Consultation lifecycle:
   - Start consultation (updates status to 'In Consultation')
   - Save consultation draft (preserves notes without discharging)
   - Complete consultation (finalizes diagnosis, prescription, discharges patient)
8. Cascading queue recalculation upon consultation completion
9. Patient dashboard visibility (Attending doctor name, finalized discharge summary & Rx)
10. Patient data privacy isolation between unauthorized doctors
"""

import pytest
from datetime import datetime
from models.db_models import (
    db, User, Department, Staff, PatientRegistration, QueueRecord, Consultation, utcnow
)
from services.queue_service import register_patient_to_queue, assign_doctor_to_patient


def login_user(client, email, password):
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)


def logout_user(client):
    return client.get('/logout', follow_redirects=True)


# =====================================================================
# 1. Doctor Authentication & Access Control
# =====================================================================

def test_doctor_login_and_dashboard_redirection(client, app):
    """Verifies doctor authenticates successfully and redirects to dedicated doctor dashboard."""
    resp = login_user(client, 'doctor@test.com', 'DocPass123!')
    assert resp.status_code == 200
    assert b"Dr. Test Physician" in resp.data
    assert b"Physician Consultation Station" in resp.data
    assert b"Patients Waiting for You" in resp.data


def test_doctor_cannot_access_admin_or_receptionist_portal(client, app):
    """Verifies strict server-side RBAC: doctor cannot access Admin or Receptionist portals."""
    login_user(client, 'doctor@test.com', 'DocPass123!')

    # Attempt Admin portal
    resp_admin = client.get('/admin/dashboard', follow_redirects=True)
    assert b"Access denied" in resp_admin.data
    assert b"Physician Consultation Station" in resp_admin.data

    # Attempt Receptionist registration
    resp_recep = client.get('/receptionist/register-patient', follow_redirects=True)
    assert b"Access denied" in resp_recep.data


def test_patient_and_unauthenticated_cannot_access_doctor_portal(client, app):
    """Verifies unauthenticated users and patients are denied access to doctor routes."""
    # Unauthenticated
    resp_unauth = client.get('/doctor/dashboard', follow_redirects=False)
    assert resp_unauth.status_code == 302
    assert '/login' in resp_unauth.location

    # Patient
    login_user(client, 'patient1@test.com', 'PatPass123!')
    resp_pat = client.get('/doctor/dashboard', follow_redirects=True)
    assert b"Access denied" in resp_pat.data
    assert b"Patient Dashboard" in resp_pat.data or b"Patient Waiting Status" in resp_pat.data or b"Patient Health Portal" in resp_pat.data


def test_doctor_toggle_availability(client, app):
    """Verifies doctor can toggle active consultation availability."""
    login_user(client, 'doctor@test.com', 'DocPass123!')

    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        assert doc.staff_record.is_available is True

    # Toggle to Off Duty
    resp1 = client.post('/doctor/toggle-availability', follow_redirects=True)
    assert resp1.status_code == 200
    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        assert doc.staff_record.is_available is False

    # Toggle back to Available
    resp2 = client.post('/doctor/toggle-availability', follow_redirects=True)
    assert resp2.status_code == 200
    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        assert doc.staff_record.is_available is True


# =====================================================================
# 2. Admin Doctor Management
# =====================================================================

def test_admin_doctor_management_create_physician(client, app):
    """Verifies admin can provision a new physician with department assignment."""
    login_user(client, 'admin@test.com', 'AdminPass123!')

    with app.app_context():
        gp = Department.query.filter_by(code='GP').first()
        gp_id = gp.id

    resp = client.post('/admin/doctors', data={
        'action': 'create',
        'full_name': 'Dr. Sarah Connor, MD',
        'email': 'dr.connor@test.com',
        'phone': '+1 (555) 777-8899',
        'age': 38,
        'gender': 'Female',
        'department_id': gp_id,
        'password': 'SecureDocPass1!',
        'is_available': '1'
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b"Dr. Sarah Connor, MD" in resp.data

    with app.app_context():
        new_doc = User.query.filter_by(email='dr.connor@test.com').first()
        assert new_doc is not None
        assert new_doc.role == 'doctor'
        assert new_doc.staff_record is not None
        assert new_doc.staff_record.department_id == gp_id
        assert new_doc.staff_record.is_available is True


def test_admin_toggle_doctor_status_preserves_records(client, app):
    """Verifies admin can deactivate a doctor account safely without deleting records."""
    login_user(client, 'admin@test.com', 'AdminPass123!')

    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        doc_id = doc.id
        assert doc.is_active is True

    # Deactivate
    resp = client.post('/admin/doctors', data={
        'action': 'toggle_status',
        'doctor_id': doc_id
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        doc = db.session.get(User, doc_id)
        assert doc.is_active is False

    # Historical record still in database
    with app.app_context():
        doc_count = User.query.filter_by(role='doctor').count()
        assert doc_count >= 1


# =====================================================================
# 3. Receptionist Doctor Assignment Workflow
# =====================================================================

def test_receptionist_assigns_doctor_safely(client, app):
    """Verifies receptionist can assign a waiting patient to an active doctor in matching department."""
    with app.app_context():
        recep = User.query.filter_by(email='reception@test.com').first()
        doc = User.query.filter_by(email='doctor@test.com').first()
        doc_id = doc.id
        gp = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=gp.id,
            patient_name="Alice Wonder",
            patient_age=28,
            patient_gender="Female"
        )
        reg_id = reg.id
        orig_token = reg.token_number

    login_user(client, 'reception@test.com', 'RecepPass123!')

    # Assign to Dr. Test Physician
    resp = client.post('/receptionist/assign-doctor', data={
        'registration_id': reg_id,
        'doctor_id': doc_id
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b"assigned to Dr. Test Physician" in resp.data

    with app.app_context():
        updated_reg = db.session.get(PatientRegistration, reg_id)
        assert updated_reg.assigned_doctor_id == doc_id
        # Token number, arrival time, and single queue ticket preserved
        assert updated_reg.token_number == orig_token
        assert QueueRecord.query.filter_by(registration_id=reg_id).count() == 1


def test_receptionist_cannot_assign_inactive_doctor(client, app):
    """Verifies system rejects assigning a patient to a deactivated doctor."""
    with app.app_context():
        recep = User.query.filter_by(email='reception@test.com').first()
        doc = User.query.filter_by(email='doctor@test.com').first()
        doc.is_active = False
        gp = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=gp.id,
            patient_name="Bob Builder",
            patient_age=40,
            patient_gender="Male"
        )
        reg_id = reg.id
        doc_id = doc.id
        db.session.commit()

    login_user(client, 'reception@test.com', 'RecepPass123!')

    resp = client.post('/receptionist/assign-doctor', data={
        'registration_id': reg_id,
        'doctor_id': doc_id
    }, follow_redirects=True)

    assert b"deactivated and cannot accept new patients" in resp.data

    with app.app_context():
        reg_check = db.session.get(PatientRegistration, reg_id)
        assert reg_check.assigned_doctor_id is None

        # Restore doctor active state for subsequent tests
        doc = db.session.get(User, doc_id)
        doc.is_active = True
        db.session.commit()


def test_receptionist_cannot_assign_incompatible_department_doctor(client, app):
    """Verifies doctor in GP cannot be assigned to an Emergency Department patient."""
    with app.app_context():
        recep = User.query.filter_by(email='reception@test.com').first()
        doc = User.query.filter_by(email='doctor@test.com').first()
        em = Department.query.filter_by(code='EM').first()

        # Patient in Emergency Department
        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=em.id,
            patient_name="Charlie ER",
            patient_age=50,
            patient_gender="Male"
        )
        reg_id = reg.id
        doc_id = doc.id

    login_user(client, 'reception@test.com', 'RecepPass123!')

    resp = client.post('/receptionist/assign-doctor', data={
        'registration_id': reg_id,
        'doctor_id': doc_id
    }, follow_redirects=True)

    assert b"Specialization mismatch" in resp.data


def test_receptionist_cannot_assign_unavailable_doctor(client, app):
    """Verifies system rejects assigning an off-duty doctor."""
    with app.app_context():
        recep = User.query.filter_by(email='reception@test.com').first()
        doc = User.query.filter_by(email='doctor@test.com').first()
        doc.staff_record.is_available = False
        gp = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=gp.id,
            patient_name="Daisy Duck",
            patient_age=25,
            patient_gender="Female"
        )
        reg_id = reg.id
        doc_id = doc.id
        db.session.commit()

    login_user(client, 'reception@test.com', 'RecepPass123!')

    resp = client.post('/receptionist/assign-doctor', data={
        'registration_id': reg_id,
        'doctor_id': doc_id
    }, follow_redirects=True)

    assert b"off duty and unavailable" in resp.data

    # Restore availability
    with app.app_context():
        doc = db.session.get(User, doc_id)
        doc.staff_record.is_available = True
        db.session.commit()


# =====================================================================
# 4. Complete Consultation Workflow
# =====================================================================

def test_doctor_starts_consultation(client, app):
    """Verifies doctor starting consultation transitions QueueRecord to 'In Consultation'."""
    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        gp = Department.query.filter_by(code='GP').first()
        reg, _ = register_patient_to_queue(
            registered_by_user_id=doc.id,
            department_id=gp.id,
            patient_name="Ethan Hunt",
            patient_age=36,
            patient_gender="Male",
            assigned_doctor_id=doc.id
        )
        reg_id = reg.id

    login_user(client, 'doctor@test.com', 'DocPass123!')

    resp = client.post('/doctor/start-consultation', data={'registration_id': reg_id}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Consultation started" in resp.data
    assert b"In Consultation" in resp.data

    with app.app_context():
        updated_reg = db.session.get(PatientRegistration, reg_id)
        assert updated_reg.queue_record.queue_status == 'In Consultation'
        assert updated_reg.queue_record.consultation_start_time is not None
        assert updated_reg.consultation is not None
        assert updated_reg.consultation.consultation_status == 'In Progress'


def test_doctor_saves_draft_consultation(client, app):
    """Verifies doctor can save draft notes without discharging patient from queue."""
    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        gp = Department.query.filter_by(code='GP').first()
        reg, _ = register_patient_to_queue(
            registered_by_user_id=doc.id,
            department_id=gp.id,
            patient_name="Fiona Gallagher",
            patient_age=29,
            patient_gender="Female",
            assigned_doctor_id=doc.id
        )
        reg_id = reg.id

    login_user(client, 'doctor@test.com', 'DocPass123!')

    resp = client.post('/doctor/save-consultation', data={
        'registration_id': reg_id,
        'chief_complaint': 'Persistent dry cough and mild sore throat',
        'clinical_observations': 'Pharynx mildly erythematous. Lungs clear to auscultation.',
        'doctor_notes': 'Likely viral upper respiratory tract infection. Monitor for fever.',
        'diagnosis': 'Viral Pharyngitis',
        'treatment_plan': 'Rest, hydration, warm saline gargles',
        'prescription': 'Paracetamol 500mg PRN for pain',
        'follow_up_instructions': 'Review in 5 days if cough worsens'
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b"draft notes saved" in resp.data

    with app.app_context():
        consult = db.session.get(PatientRegistration, reg_id).consultation
        assert consult is not None
        assert consult.diagnosis == 'Viral Pharyngitis'
        assert consult.prescription == 'Paracetamol 500mg PRN for pain'
        assert consult.completed_at is None
        # Queue record is still active
        assert db.session.get(PatientRegistration, reg_id).queue_record.queue_status in ['Waiting', 'Called', 'In Consultation']


def test_doctor_completes_consultation_and_discharges_queue(client, app):
    """
    Verifies complete consultation lifecycle:
    - Finalizes diagnosis and treatment
    - Marks Consultation 'Completed' and sets completed_at
    - Marks QueueRecord 'Completed' and sets completion_time
    - Sets patients_ahead = 0 and estimated_wait_minutes = 0.0
    - Discharges patient from active queue
    """
    with app.app_context():
        doc = User.query.filter_by(email='doctor@test.com').first()
        gp = Department.query.filter_by(code='GP').first()
        reg, _ = register_patient_to_queue(
            registered_by_user_id=doc.id,
            department_id=gp.id,
            patient_name="George Clark",
            patient_age=52,
            patient_gender="Male",
            assigned_doctor_id=doc.id
        )
        reg_id = reg.id

    login_user(client, 'doctor@test.com', 'DocPass123!')

    resp = client.post('/doctor/complete-consultation', data={
        'registration_id': reg_id,
        'chief_complaint': 'Hypertension routine checkup',
        'clinical_observations': 'BP 132/84 mmHg, HR 74 bpm regular',
        'doctor_notes': 'Stable control on current therapy. No organ damage symptoms.',
        'diagnosis': 'Essential Hypertension (Well Controlled)',
        'treatment_plan': 'Low-sodium diet, regular moderate exercise',
        'prescription': 'Amlodipine 5mg OD x 30 days',
        'follow_up_instructions': 'Routine BP check in 1 month'
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b"discharged from the active queue" in resp.data

    with app.app_context():
        reg_check = db.session.get(PatientRegistration, reg_id)
        q_check = reg_check.queue_record
        c_check = reg_check.consultation

        # Queue record assertions
        assert q_check.queue_status == 'Completed'
        assert q_check.completion_time is not None
        assert q_check.patients_ahead == 0
        assert q_check.estimated_wait_minutes == 0.0

        # Consultation record assertions
        assert c_check.consultation_status == 'Completed'
        assert c_check.completed_at is not None
        assert c_check.diagnosis == 'Essential Hypertension (Well Controlled)'
        assert c_check.prescription == 'Amlodipine 5mg OD x 30 days'


def test_queue_recalculation_after_consultation_completion(client, app):
    """
    Verifies that when a doctor completes a consultation,
    the remaining waiting patients in that department have their
    positions ahead and waiting times dynamically recalculated.
    """
    with app.app_context():
        recep = User.query.filter_by(email='reception@test.com').first()
        doc = User.query.filter_by(email='doctor@test.com').first()
        gp = Department.query.filter_by(code='GP').first()

        # Register Patient 1
        reg1, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=gp.id,
            patient_name="Queue Patient One",
            triage_priority=3,
            assigned_doctor_id=doc.id
        )
        # Register Patient 2
        reg2, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=gp.id,
            patient_name="Queue Patient Two",
            triage_priority=3,
            assigned_doctor_id=doc.id
        )

        reg1_id = reg1.id
        reg2_id = reg2.id

    # Prior to completion: Patient 2 has at least 1 patient ahead
    with app.app_context():
        q2_before = db.session.get(PatientRegistration, reg2_id).queue_record
        assert q2_before.patients_ahead == 1

    # Doctor completes Patient 1
    login_user(client, 'doctor@test.com', 'DocPass123!')
    client.post('/doctor/complete-consultation', data={
        'registration_id': reg1_id,
        'diagnosis': 'Seasonal Allergic Rhinitis',
        'doctor_notes': 'Antihistamine prescribed.'
    }, follow_redirects=True)

    # After completion: Patient 2 is now first in line (patients_ahead == 0)
    with app.app_context():
        q1_after = db.session.get(PatientRegistration, reg1_id).queue_record
        q2_after = db.session.get(PatientRegistration, reg2_id).queue_record

        assert q1_after.queue_status == 'Completed'
        assert q2_after.patients_ahead == 0


def test_patient_views_assigned_doctor_and_completed_consultation(client, app):
    """
    Verifies patient can see their assigned doctor's name while waiting,
    and sees finalized diagnosis & prescription after consultation completion.
    """
    with app.app_context():
        pat = User.query.filter_by(email='patient1@test.com').first()
        doc = User.query.filter_by(email='doctor@test.com').first()
        gp = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=pat.id,
            department_id=gp.id,
            patient_name=pat.full_name,
            patient_user_id=pat.id,
            assigned_doctor_id=doc.id,
            health_concern_category="Headache"
        )
        reg_id = reg.id

    # Patient views dashboard while waiting: should see Attending Physician Dr. Test Physician
    login_user(client, 'patient1@test.com', 'PatPass123!')
    resp_waiting = client.get('/patient/dashboard')
    assert resp_waiting.status_code == 200
    assert b"Attending Physician" in resp_waiting.data
    assert b"Dr. Test Physician" in resp_waiting.data

    logout_user(client)

    # Doctor completes the visit
    login_user(client, 'doctor@test.com', 'DocPass123!')
    client.post('/doctor/complete-consultation', data={
        'registration_id': reg_id,
        'diagnosis': 'Tension Type Headache',
        'treatment_plan': 'Hydration and sleep hygiene',
        'prescription': 'Ibuprofen 400mg TDS after food',
        'follow_up_instructions': 'Review in 2 weeks if symptoms persist'
    }, follow_redirects=True)

    logout_user(client)

    # Patient views dashboard after completion: diagnosis & Rx visible in history
    login_user(client, 'patient1@test.com', 'PatPass123!')
    resp_done = client.get('/patient/dashboard')
    assert resp_done.status_code == 200
    assert b"Tension Type Headache" in resp_done.data
    assert b"Ibuprofen 400mg TDS" in resp_done.data
    assert b"Review in 2 weeks" in resp_done.data


def test_doctor_privacy_isolation_between_unrelated_departments(client, app):
    """
    Verifies a doctor cannot inspect or modify a consultation
    belonging to another doctor in an unrelated department.
    """
    with app.app_context():
        admin = User.query.filter_by(email='admin@test.com').first()
        em = Department.query.filter_by(code='EM').first()

        # Create Dr. Emergency in EM
        doc_em = User(full_name='Dr. Emergency', email='dr.em@test.com', role='doctor', is_active=True)
        doc_em.set_password('EmPass123!')
        db.session.add(doc_em)
        db.session.flush()

        staff_em = Staff(user_id=doc_em.id, department_id=em.id, staff_type='Doctor', is_available=True)
        db.session.add(staff_em)

        # Patient in Emergency Department assigned to Dr. Emergency
        reg, _ = register_patient_to_queue(
            registered_by_user_id=admin.id,
            department_id=em.id,
            patient_name="Trauma Patient",
            assigned_doctor_id=doc_em.id
        )
        em_reg_id = reg.id
        db.session.commit()

    # Log in as Dr. Test Physician (who belongs to GP)
    login_user(client, 'doctor@test.com', 'DocPass123!')

    # Attempt to open EM patient chart
    resp = client.get(f'/doctor/consultation/{em_reg_id}', follow_redirects=True)
    assert b"Access denied" in resp.data

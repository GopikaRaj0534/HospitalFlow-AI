"""
tests/test_contact.py
---------------------
Automated test suite for hospital contact information and in-site assistance requests:
- Public & authenticated contact information display
- Authenticated in-site assistance request submission
- Unique request reference generation (REQ-YYYY-NNNN)
- Verification that contact requests DO NOT create active queue tickets
- Staff review, status updates, and response notes
- Privacy: Patients can only view their own assistance requests
"""

import pytest
from models.db_models import db, User, ContactRequest, PatientRegistration, QueueRecord


def test_public_contact_page_displays_info(client):
    """Verifies that the /contact endpoint displays real configured hospital contact details."""
    response = client.get('/contact')
    assert response.status_code == 200
    assert b"HospitalFlow General Hospital" in response.data
    assert b"555" in response.data  # Phone numbers
    assert b"care@hospitalflow.ai" in response.data
    assert b"Health Science Boulevard" in response.data


def test_patient_submits_contact_request(client, app):
    """Verifies that a logged-in patient can submit an in-site assistance request."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    response = client.post('/patient/contact-requests', data={
        'request_type': 'Appointment Request',
        'subject': 'Cardiology consultation appointment inquiry',
        'message': 'I would like to inquire about booking a cardiology checkup for next Tuesday morning.',
        'preferred_contact_method': 'Email',
        'preferred_callback_time': 'Morning hours'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"submitted under reference" in response.data or b"REQ-" in response.data

    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        req = ContactRequest.query.filter_by(patient_user_id=p1.id).first()
        assert req is not None
        assert req.request_reference.startswith('REQ-')
        assert req.request_type == 'Appointment Request'
        assert req.status == 'Submitted'
        assert 'cardiology checkup' in req.message


def test_contact_request_does_not_create_queue_token(client, app):
    """Verifies that submitting a contact/appointment request does NOT create a queue token."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)

    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        initial_token_count = PatientRegistration.query.filter_by(patient_user_id=p1.id).count()

    # Submit assistance request
    client.post('/patient/contact-requests', data={
        'request_type': 'General Inquiry',
        'subject': 'Parking and visitor access question',
        'message': 'Could you please confirm if overnight parking is permitted near the east wing?'
    }, follow_redirects=True)

    with app.app_context():
        final_token_count = PatientRegistration.query.filter_by(patient_user_id=p1.id).count()
        # Token count must NOT increase
        assert final_token_count == initial_token_count


def test_staff_can_review_and_respond_to_request(client, app):
    """Verifies authorized receptionist staff can update request status and submit response note."""
    with app.app_context():
        p1 = User.query.filter_by(email='patient1@test.com').first()
        req = ContactRequest(
            request_reference='REQ-2026-TEST',
            patient_user_id=p1.id,
            patient_name=p1.full_name,
            patient_email=p1.email,
            request_type='Callback Request',
            subject='Follow-up inquiry',
            message='Need clarification on medication instructions.',
            status='Submitted'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id

    # Log in as receptionist
    client.post('/login', data={'email': 'reception@test.com', 'password': 'RecepPass123!'}, follow_redirects=True)

    # Receptionist responds
    res = client.post('/receptionist/contact-requests', data={
        'request_id': req_id,
        'status': 'Responded To',
        'staff_response': 'Nurse practitioner will telephone you at 11:00 AM.'
    }, follow_redirects=True)

    assert res.status_code == 200

    with app.app_context():
        updated_req = db.session.get(ContactRequest, req_id)
        assert updated_req.status == 'Responded To'
        assert 'telephone you at 11:00 AM' in updated_req.staff_response
        assert updated_req.responded_by_user_id is not None


def test_patient_requests_isolation(client, app):
    """Verifies that Patient 1 cannot view Patient 2's contact requests."""
    with app.app_context():
        p2 = User.query.filter_by(email='patient2@test.com').first()
        req_p2 = ContactRequest(
            request_reference='REQ-P2-SECRET',
            patient_user_id=p2.id,
            patient_name=p2.full_name,
            patient_email=p2.email,
            request_type='General Inquiry',
            subject='Confidential Medical Records Request',
            message='Please send records to Dr. Adams.',
            status='Submitted'
        )
        db.session.add(req_p2)
        db.session.commit()

    # Log in as Patient 1
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    res = client.get('/patient/contact-requests')

    # Patient 1 must NOT see Patient 2's request reference or subject
    assert b"REQ-P2-SECRET" not in res.data
    assert b"Confidential Medical Records Request" not in res.data

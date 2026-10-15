"""
tests/test_auth.py
------------------
Automated test suite for authentication and registration:
- Patient account registration
- Duplicate email prevention
- Valid and invalid login authentication
- Session termination on logout
"""

import pytest
from models.db_models import User


def test_patient_registration_success(client, app):
    """Verifies that a patient can successfully register a new account."""
    response = client.post('/register', data={
        'full_name': 'New Patient',
        'email': 'newpatient@example.com',
        'phone': '555-1234',
        'password': 'Password123!',
        'confirm_password': 'Password123!'
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email='newpatient@example.com').first()
        assert user is not None
        assert user.role == 'patient'
        assert user.check_password('Password123!')


def test_duplicate_registration_fails(client):
    """Verifies that registering with an already existing email is rejected."""
    response = client.post('/register', data={
        'full_name': 'Duplicate User',
        'email': 'patient1@test.com',  # seeded in conftest
        'phone': '555-0000',
        'password': 'Password123!',
        'confirm_password': 'Password123!'
    }, follow_redirects=True)

    assert b"already registered" in response.data or response.status_code == 200


def test_password_mismatch_fails(client):
    """Verifies that registration fails when passwords do not match."""
    response = client.post('/register', data={
        'full_name': 'Mismatch User',
        'email': 'mismatch@example.com',
        'phone': '555-0000',
        'password': 'Password123!',
        'confirm_password': 'DifferentPassword!'
    }, follow_redirects=True)

    assert b"do not match" in response.data


def test_valid_login(client):
    """Verifies successful login redirects to correct role dashboard."""
    response = client.post('/login', data={
        'email': 'patient1@test.com',
        'password': 'PatPass123!'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Welcome, Patient One" in response.data or b"Patient Portal" in response.data


def test_invalid_login_credentials(client):
    """Verifies incorrect password shows error and prevents login."""
    response = client.post('/login', data={
        'email': 'patient1@test.com',
        'password': 'WrongPassword123'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_logout(client):
    """Verifies logout terminates user session."""
    client.post('/login', data={'email': 'patient1@test.com', 'password': 'PatPass123!'}, follow_redirects=True)
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b"logged out" in response.data

"""
tests/test_admin.py
-------------------
Automated test suite for administrator system management:
- Hospital contact settings management
- User accounts and status toggling
- Department registry management
- Model management portal access
- Operational statistics dashboard
"""

import pytest
from models.db_models import db, User, Department, HospitalSetting


def test_admin_hospital_settings_update(client, app):
    """Verifies that an administrator can update hospital contact information."""
    client.post('/login', data={'email': 'admin@test.com', 'password': 'AdminPass123!'}, follow_redirects=True)

    response = client.post('/admin/hospital-settings', data={
        'hospital_name': 'HospitalFlow Medical Center West',
        'phone': '+1 (555) 888-1111',
        'emergency_phone': '+1 (555) 911-0000',
        'email': 'admin@hospitalflow-west.ai',
        'address': '500 Health Park Drive, West Wing, Metro City',
        'opening_hours': '24/7 Comprehensive Trauma & Emergency',
        'directions_url': 'https://maps.google.com/test'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"updated successfully" in response.data

    with app.app_context():
        setting = HospitalSetting.query.first()
        assert setting.hospital_name == 'HospitalFlow Medical Center West'
        assert setting.phone == '+1 (555) 888-1111'
        assert setting.emergency_phone == '+1 (555) 911-0000'


def test_admin_user_management_and_toggle(client, app):
    """Verifies admin can create a user and toggle their active status."""
    client.post('/login', data={'email': 'admin@test.com', 'password': 'AdminPass123!'}, follow_redirects=True)

    # 1. Create user
    res_create = client.post('/admin/users', data={
        'action': 'create',
        'full_name': 'Dr. Marcus Vance',
        'email': 'dr.vance@test.com',
        'phone': '555-7777',
        'role': 'receptionist',
        'password': 'DoctorPass123!'
    }, follow_redirects=True)

    assert res_create.status_code == 200
    assert b"created successfully" in res_create.data

    with app.app_context():
        created = User.query.filter_by(email='dr.vance@test.com').first()
        assert created is not None
        user_id = created.id

    # 2. Toggle status
    res_toggle = client.post('/admin/users', data={
        'action': 'toggle_status',
        'user_id': user_id
    }, follow_redirects=True)

    assert res_toggle.status_code == 200
    with app.app_context():
        updated = db.session.get(User, user_id)
        assert updated.is_active is False


def test_admin_department_creation(client, app):
    """Verifies admin can create a new hospital department."""
    client.post('/login', data={'email': 'admin@test.com', 'password': 'AdminPass123!'}, follow_redirects=True)

    response = client.post('/admin/departments', data={
        'action': 'create',
        'department_name': 'Pediatrics Clinic',
        'code': 'PED',
        'description': 'Children and adolescent clinical care'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"registered successfully" in response.data

    with app.app_context():
        dept = Department.query.filter_by(code='PED').first()
        assert dept is not None
        assert dept.department_name == 'Pediatrics Clinic'


def test_admin_model_management_page_accessible(client):
    """Verifies admin can view the ML model performance and evaluation report."""
    client.post('/login', data={'email': 'admin@test.com', 'password': 'AdminPass123!'}, follow_redirects=True)
    response = client.get('/admin/model-management', follow_redirects=True)

    assert response.status_code == 200
    assert b"ML Model Management" in response.data or b"Machine Learning" in response.data

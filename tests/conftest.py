"""
tests/conftest.py
-----------------
Pytest configuration and fixtures.
Uses an in-memory SQLite database to ensure tests NEVER delete or modify real XAMPP data.
"""

import pytest
import os
from app import create_app
from models.db_models import (
    db, User, Department, Staff, PatientRegistration, QueueRecord,
    Consultation, ContactRequest, HospitalSetting,
    SymptomAssessment, ConsultationRequest, DoctorRegistrationRequest
)


@pytest.fixture
def app():
    os.environ['FLASK_ENV'] = 'testing'
    app = create_app('testing')
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test_secret_key'
    })

    with app.app_context():
        db.create_all()

        # Seed test departments
        dept_gp = Department(department_name='General Practice', code='GP', description='General', is_active=True)
        dept_em = Department(department_name='Emergency Department', code='EM', description='ER', is_active=True)
        db.session.add_all([dept_gp, dept_em])
        db.session.flush()

        # Seed test users (Admin role transferred to Receptionist lead)
        admin = User(full_name='Test Admin', email='admin@test.com', role='receptionist', is_active=True)
        admin.set_password('AdminPass123!')

        receptionist = User(full_name='Test Receptionist', email='reception@test.com', role='receptionist', is_active=True)
        receptionist.set_password('RecepPass123!')

        doctor = User(full_name='Dr. Test Physician', email='doctor@test.com', role='doctor', is_active=True, age=44, gender='Male')
        doctor.set_password('DocPass123!')

        patient1 = User(full_name='Patient One', email='patient1@test.com', role='patient', is_active=True, age=32, gender='Female')
        patient1.set_password('PatPass123!')

        patient2 = User(full_name='Patient Two', email='patient2@test.com', role='patient', is_active=True, age=45, gender='Male')
        patient2.set_password('PatPass123!')

        db.session.add_all([admin, receptionist, doctor, patient1, patient2])
        db.session.flush()

        staff_rec = Staff(user_id=receptionist.id, department_id=dept_gp.id, staff_type='Receptionist', is_available=True)
        staff_doc = Staff(user_id=doctor.id, department_id=dept_gp.id, staff_type='Doctor', is_available=True)
        db.session.add_all([staff_rec, staff_doc])

        # Seed test hospital setting
        setting = HospitalSetting(
            hospital_name='HospitalFlow General Hospital & Medical Center',
            phone='+1 (555) 019-2830',
            emergency_phone='+1 (555) 911-3569',
            email='care@hospitalflow.ai',
            address='1200 Health Science Boulevard, Suite 400, Metro City, MC 98101',
            opening_hours='24/7 Emergency Care | OPD: Mon - Sat 8:00 AM - 8:00 PM'
        )

        db.session.add(setting)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()

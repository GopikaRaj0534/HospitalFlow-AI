"""
tests/test_queue.py
-------------------
Automated test suite for queue management:
- Patient registration via receptionist
- Unique token generation across departments
- Priority-aware fair queue ordering (Priority 1 > Priority 2 > Priority 3)
- FIFO ordering within same priority level
- Staff-assigned triage priority updates with audit logging
- Full queue status lifecycle (Waiting -> Called -> In Consultation -> Completed / Skipped)
- Prevention of duplicate active queue tickets for the same patient
"""

import pytest
from datetime import timedelta
from models.db_models import db, PatientRegistration, QueueRecord, Department, User, utcnow
from services.queue_service import (
    register_patient_to_queue,
    update_queue_status,
    update_triage_priority,
    recalculate_department_queue
)


def test_receptionist_patient_registration(app):
    """Verifies receptionist can register patient to queue and assign unique token."""
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='GP').first()

        reg, err = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Alice Wonderland',
            patient_phone='555-9876',
            patient_age=28,
            patient_gender='Female',
            triage_priority=3,
            arrival_time=utcnow()
        )

        assert err is None
        assert reg is not None
        assert reg.token_number.startswith('GP-')
        assert reg.queue_record is not None
        assert reg.queue_record.queue_status == 'Waiting'
        assert reg.queue_record.patients_ahead == 0


def test_unique_tokens_in_same_department(app):
    """Verifies successive registrations generate unique token numbers."""
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='GP').first()

        reg1, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Patient Alpha'
        )
        reg2, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Patient Beta'
        )

        assert reg1.token_number != reg2.token_number
        assert reg2.queue_record.patients_ahead >= 1


def test_priority_aware_queue_ordering(app):
    """
    Verifies fair queue ordering:
    A patient with Priority 1 (Emergency) arriving later must be ordered ahead
    of a patient with Priority 3 (Routine) who arrived earlier.
    """
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='EM').first()
        base_time = utcnow()

        # Routine patient arrives first
        reg_routine, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Routine Patient',
            triage_priority=3,
            arrival_time=base_time
        )

        # Emergency patient arrives 5 minutes later
        reg_emergency, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Emergency Patient',
            triage_priority=1,
            arrival_time=base_time + timedelta(minutes=5)
        )

        # Emergency patient must have 0 patients ahead
        q_emerg = db.session.get(QueueRecord, reg_emergency.queue_record.id)
        q_routine = db.session.get(QueueRecord, reg_routine.queue_record.id)

        assert q_emerg.patients_ahead == 0
        assert q_routine.patients_ahead == 1


def test_fifo_ordering_within_same_priority(app):
    """Verifies FIFO queue ordering within the same triage priority level."""
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='GP').first()
        t1 = utcnow()

        reg1, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='First Routine',
            triage_priority=3,
            arrival_time=t1
        )
        reg2, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Second Routine',
            triage_priority=3,
            arrival_time=t1 + timedelta(minutes=2)
        )

        q1 = db.session.get(QueueRecord, reg1.queue_record.id)
        q2 = db.session.get(QueueRecord, reg2.queue_record.id)

        assert q1.patients_ahead < q2.patients_ahead


def test_staff_triage_priority_update(app):
    """Verifies authorized staff can update triage priority and trigger queue reordering."""
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Triage Update Patient',
            triage_priority=3
        )

        success, err = update_triage_priority(reg.id, 1, staff_user_id=recep.id)
        assert success is True
        assert err is None

        updated_reg = db.session.get(PatientRegistration, reg.id)
        assert updated_reg.triage_priority == 1
        assert updated_reg.priority_assigned_by == recep.id
        assert updated_reg.priority_assigned_at is not None


def test_duplicate_active_ticket_prevention(app):
    """Verifies that an active patient cannot accidentally create multiple active queue tokens."""
    with app.app_context():
        patient = User.query.filter_by(email='patient1@test.com').first()
        dept = Department.query.filter_by(code='GP').first()

        reg1, err1 = register_patient_to_queue(
            registered_by_user_id=patient.id,
            department_id=dept.id,
            patient_name=patient.full_name,
            patient_user_id=patient.id
        )
        assert err1 is None
        assert reg1 is not None

        # Attempt second active registration
        reg2, err2 = register_patient_to_queue(
            registered_by_user_id=patient.id,
            department_id=dept.id,
            patient_name=patient.full_name,
            patient_user_id=patient.id
        )
        assert reg2 is None
        assert "already have an active visit" in err2


def test_queue_status_progression(app):
    """Verifies status changes: Waiting -> Called -> In Consultation -> Completed."""
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Charlie Status Test'
        )
        q_id = reg.queue_record.id

        # 1. Call Patient
        success_call, err_call = update_queue_status(q_id, 'Called')
        assert success_call is True
        q_call = db.session.get(QueueRecord, q_id)
        assert q_call.queue_status == 'Called'
        assert q_call.call_time is not None

        # 2. Start Consult
        success, err = update_queue_status(q_id, 'In Consultation')
        assert success is True
        assert err is None

        q = db.session.get(QueueRecord, q_id)
        assert q.queue_status == 'In Consultation'
        assert q.consultation_start_time is not None

        # 3. Complete Visit
        success2, err2 = update_queue_status(q_id, 'Completed')
        assert success2 is True
        q2 = db.session.get(QueueRecord, q_id)
        assert q2.queue_status == 'Completed'
        assert q2.completion_time is not None


def test_queue_status_skipped(app):
    """Verifies patient can be marked as Skipped/Absent."""
    with app.app_context():
        recep = User.query.filter_by(role='receptionist').first()
        dept = Department.query.filter_by(code='GP').first()

        reg, _ = register_patient_to_queue(
            registered_by_user_id=recep.id,
            department_id=dept.id,
            patient_name='Absent Patient'
        )
        q_id = reg.queue_record.id

        success, err = update_queue_status(q_id, 'Skipped')
        assert success is True
        q = db.session.get(QueueRecord, q_id)
        assert q.queue_status == 'Skipped'

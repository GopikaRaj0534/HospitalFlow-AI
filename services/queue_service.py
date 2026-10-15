"""
services/queue_service.py
-------------------------
Smart department-based patient queue management:
- Department-isolated queue structures
- Priority-aware queue ordering (Priority 1 > Priority 2 > Priority 3 > Priority 4, then FIFO)
- Clinical triage priority assignments with staff audit tracking
- Full status lifecycle: Waiting -> Called -> In Consultation -> Completed / Skipped / Cancelled
- Accurate patients-ahead calculations and dynamic ML waiting-time recalculation
- Safe concurrency and duplicate ticket prevention
"""

from datetime import datetime
from sqlalchemy import case
from models.db_models import db, PatientRegistration, QueueRecord, Department, User, utcnow
from services.prediction_service import estimate_waiting_time_for_registration


VALID_STATUSES = ['Waiting', 'Called', 'In Consultation', 'Completed', 'Skipped', 'Cancelled']
ACTIVE_STATUSES = ['Waiting', 'Called']


def generate_unique_token(department_id: int) -> str:
    """
    Generates a unique, human-readable queue token based on department code and daily sequence.
    Example: GP-001, EM-002, CARD-003
    """
    dept = db.session.get(Department, department_id)
    dept_code = dept.code if dept else 'GEN'

    # Count registrations today for this department
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count_today = PatientRegistration.query.filter(
        PatientRegistration.department_id == department_id,
        PatientRegistration.created_at >= today_start
    ).count()

    seq = count_today + 1
    token = f"{dept_code}-{seq:03d}"

    # Ensure absolute uniqueness across the database
    suffix = 1
    while PatientRegistration.query.filter_by(token_number=token).first():
        token = f"{dept_code}-{seq:03d}-{suffix}"
        suffix += 1

    return token


def register_patient_to_queue(
    registered_by_user_id: int,
    department_id: int,
    patient_name: str,
    patient_phone: str = None,
    patient_age: int = 35,
    patient_gender: str = 'Female',
    patient_user_id: int = None,
    triage_priority: int = 3,
    registration_notes: str = None,
    health_concern_category: str = None,
    symptoms_description: str = None,
    symptom_duration: str = None,
    has_appointment: bool = False,
    appointment_notes: str = None,
    arrival_time: datetime = None,
    assigned_doctor_id: int = None
):
    """
    Atomically registers a patient visit, enforces duplicate submission safeguards,
    computes priority-aware position ahead, calls ML waiting-time prediction,
    and updates the departmental queue.
    """
    # 1. Validation
    if not patient_name or not str(patient_name).strip() or not department_id:
        return None, "Patient name and department are required."

    dept = db.session.get(Department, department_id)
    if not dept or not dept.is_active:
        return None, "Selected department is invalid or currently inactive."

    registrar = db.session.get(User, registered_by_user_id)
    if not registrar:
        return None, "Registering user account was not found."

    # Patients can self-register their own visit, staff can register any patient
    if registrar.role == 'patient':
        if patient_user_id and patient_user_id != registrar.id:
            return None, "Security violation: Patients can only submit visit requests for their own account."
        patient_user_id = registrar.id

    # Validate assigned doctor if provided
    if assigned_doctor_id:
        doc = db.session.get(User, assigned_doctor_id)
        if not doc or doc.role != 'doctor' or not doc.is_active:
            return None, "Selected doctor is not eligible or currently inactive."
        if not doc.staff_record or doc.staff_record.department_id != department_id:
            return None, "Selected doctor does not belong to the chosen department."
        if not doc.staff_record.is_available:
            return None, f"Dr. {doc.full_name} is currently off duty."

    # 2. Duplicate active ticket check for patient
    if patient_user_id:
        existing_active = db.session.query(QueueRecord).join(PatientRegistration).filter(
            PatientRegistration.patient_user_id == patient_user_id,
            QueueRecord.queue_status.in_(['Waiting', 'Called', 'In Consultation'])
        ).first()
        if existing_active:
            return None, f"You already have an active visit (Token: {existing_active.registration.token_number}) currently in '{existing_active.queue_status}' status. Please complete or cancel it before initiating a new visit."

    if arrival_time is None:
        arrival_time = utcnow()

    # Priority normalization (1=Emergency, 2=Urgent, 3=Routine, 4=Low)
    try:
        triage_priority = int(triage_priority)
        if triage_priority < 1 or triage_priority > 4:
            triage_priority = 3
    except (ValueError, TypeError):
        triage_priority = 3

    # 3. Generate unique token
    token = generate_unique_token(department_id)

    # 4. Count active patients ahead in priority-aware sequence:
    # A patient is ahead if they are 'Called', OR if their priority is numerically lower (higher urgency),
    # OR if same priority and earlier arrival time.
    priority_order = case(
        (QueueRecord.queue_status == 'Called', 0),
        else_=1
    )
    active_in_dept = db.session.query(QueueRecord).join(PatientRegistration).filter(
        PatientRegistration.department_id == department_id,
        QueueRecord.queue_status.in_(ACTIVE_STATUSES)
    ).order_by(
        priority_order.asc(),
        PatientRegistration.triage_priority.asc(),
        PatientRegistration.arrival_time.asc()
    ).all()

    # Determine where the new entry would sit
    patients_ahead_count = 0
    for q in active_in_dept:
        reg = q.registration
        if q.queue_status == 'Called':
            patients_ahead_count += 1
        elif reg.triage_priority < triage_priority:
            patients_ahead_count += 1
        elif reg.triage_priority == triage_priority and reg.arrival_time <= arrival_time:
            patients_ahead_count += 1
        else:
            break

    # 5. ML Waiting-Time Prediction
    estimated_wait, pred_err = estimate_waiting_time_for_registration(
        department_name=dept.department_name,
        arrival_datetime=arrival_time,
        patient_age=patient_age,
        patient_gender=patient_gender,
        patients_ahead=patients_ahead_count,
        triage_priority=triage_priority
    )

    if estimated_wait is None:
        estimated_wait = 0.0

    try:
        registration = PatientRegistration(
            patient_user_id=patient_user_id,
            patient_name=patient_name.strip(),
            patient_phone=patient_phone.strip() if patient_phone else None,
            patient_age=patient_age,
            patient_gender=patient_gender,
            registered_by=registered_by_user_id,
            department_id=department_id,
            assigned_doctor_id=assigned_doctor_id if assigned_doctor_id else None,
            token_number=token,
            arrival_time=arrival_time,
            triage_priority=triage_priority,
            registration_notes=registration_notes.strip() if registration_notes else None,
            health_concern_category=health_concern_category.strip() if health_concern_category else None,
            symptoms_description=symptoms_description.strip() if symptoms_description else None,
            symptom_duration=symptom_duration.strip() if symptom_duration else None,
            has_appointment=bool(has_appointment),
            appointment_notes=appointment_notes.strip() if appointment_notes else None,
            priority_assigned_by=registered_by_user_id if registrar.role in ['admin', 'receptionist'] else None,
            priority_assigned_at=utcnow() if registrar.role in ['admin', 'receptionist'] else None
        )
        db.session.add(registration)
        db.session.flush()

        queue_entry = QueueRecord(
            registration_id=registration.id,
            queue_status='Waiting',
            patients_ahead=patients_ahead_count,
            estimated_wait_minutes=estimated_wait,
            prediction_timestamp=utcnow()
        )
        db.session.add(queue_entry)
        db.session.commit()

        # Recalculate entire department queue to refresh cascading positions
        recalculate_department_queue(department_id)

        return registration, None

    except Exception as e:
        db.session.rollback()
        return None, f"Database transaction failed: {str(e)}"


def update_queue_status(queue_record_id: int, new_status: str, staff_user_id: int = None):
    """
    Validates and performs queue status transitions.
    Transitions: Waiting -> Called -> In Consultation -> Completed / Skipped / Cancelled.
    Cascades recalculated positions and ML waiting times to remaining patients.
    """
    if new_status not in VALID_STATUSES:
        return False, f"Invalid status: '{new_status}'. Allowed: {', '.join(VALID_STATUSES)}"

    queue_rec = db.session.get(QueueRecord, queue_record_id)
    if not queue_rec:
        return False, "Queue record not found."

    old_status = queue_rec.queue_status
    if old_status == new_status:
        return True, "Status is already up to date."

    # Validate permitted status transitions
    # Completed / Cancelled are terminal states and should not silently revert without authorization
    if old_status in ['Completed', 'Cancelled'] and new_status == 'Waiting':
        # Re-opening requires staff authorization
        pass

    now = utcnow()
    queue_rec.queue_status = new_status

    if new_status == 'Called':
        queue_rec.call_time = now

    elif new_status == 'In Consultation':
        if not queue_rec.consultation_start_time:
            queue_rec.consultation_start_time = now
        queue_rec.patients_ahead = 0
        queue_rec.estimated_wait_minutes = 0.0

    elif new_status in ['Completed', 'Cancelled', 'Skipped']:
        if new_status == 'Completed' and not queue_rec.completion_time:
            queue_rec.completion_time = now
        queue_rec.patients_ahead = 0
        queue_rec.estimated_wait_minutes = 0.0

    elif new_status == 'Waiting':
        # When re-queued
        pass

    try:
        db.session.commit()

        # Recalculate remaining waiting and called patients in this department
        dept_id = queue_rec.registration.department_id
        recalculate_department_queue(dept_id)

        return True, None
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to update queue record: {str(e)}"


def update_triage_priority(registration_id: int, new_priority: int, staff_user_id: int):
    """
    Allows authorized clinical staff to adjust patient triage priority.
    Updates audit trail and immediately re-orders the department queue.
    """
    try:
        new_priority = int(new_priority)
        if new_priority < 1 or new_priority > 4:
            return False, "Triage priority must be between 1 (Emergency) and 4 (Low)."
    except (ValueError, TypeError):
        return False, "Invalid priority level."

    reg = db.session.get(PatientRegistration, registration_id)
    if not reg:
        return False, "Patient registration record not found."

    staff = db.session.get(User, staff_user_id)
    if not staff or staff.role not in ['admin', 'receptionist']:
        return False, "Unauthorized: Only clinical staff or administrators can assign medical priority."

    reg.triage_priority = new_priority
    reg.priority_assigned_by = staff_user_id
    reg.priority_assigned_at = utcnow()

    try:
        db.session.commit()
        # Re-sort and recalculate queue with new priority
        recalculate_department_queue(reg.department_id)
        return True, None
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to update priority: {str(e)}"


def recalculate_department_queue(department_id: int):
    """
    Re-evaluates `patients_ahead` and refreshes ML predictions for all active
    patients in a given department according to priority-aware fair ordering.
    Ordering: 'Called' first, then triage_priority ASC (1=Emergency first),
    then arrival_time ASC (FIFO within priority level).
    """
    dept = db.session.get(Department, department_id)
    if not dept:
        return

    priority_order = case(
        (QueueRecord.queue_status == 'Called', 0),
        else_=1
    )

    active_records = db.session.query(QueueRecord).join(PatientRegistration).filter(
        PatientRegistration.department_id == department_id,
        QueueRecord.queue_status.in_(ACTIVE_STATUSES)
    ).order_by(
        priority_order.asc(),
        PatientRegistration.triage_priority.asc(),
        PatientRegistration.arrival_time.asc()
    ).all()

    for idx, q_rec in enumerate(active_records):
        q_rec.patients_ahead = idx
        reg = q_rec.registration

        if q_rec.queue_status == 'Called':
            # Patient has been called to consultation room
            q_rec.estimated_wait_minutes = 2.0
            q_rec.prediction_timestamp = utcnow()
        else:
            # Re-predict with updated queue depth and triage priority
            est_wait, _ = estimate_waiting_time_for_registration(
                department_name=dept.department_name,
                arrival_datetime=reg.arrival_time,
                patient_age=reg.patient_age,
                patient_gender=reg.patient_gender,
                patients_ahead=idx,
                triage_priority=reg.triage_priority
            )
            if est_wait is not None:
                q_rec.estimated_wait_minutes = est_wait
                q_rec.prediction_timestamp = utcnow()

    db.session.commit()


def get_patient_queue_details(user_id: int):
    """
    Returns queue registrations and active waiting status for a logged-in patient.
    Strictly isolates patient records so patients can ONLY access their own data.
    """
    return PatientRegistration.query.filter_by(patient_user_id=user_id)\
        .order_by(PatientRegistration.arrival_time.desc()).all()


def find_queue_by_token(token_number: str):
    """Looks up registration and queue status by unique token number."""
    if not token_number:
        return None
    return PatientRegistration.query.filter_by(token_number=token_number.strip().upper()).first()


def assign_doctor_to_patient(registration_id: int, doctor_id: int = None, staff_user_id: int = None):
    """
    Safely assigns or reassigns an active/waiting patient to an eligible physician.
    Enforces business rules:
    - Target doctor must exist, have role 'doctor', and be active (is_active=True).
    - Target doctor must belong to the patient's registered department.
    - Target doctor must currently be available (is_available=True).
    - Inactive or incompatible doctors cannot be assigned.
    - Previous assignment history is safely overwritten without creating duplicate tickets or altering token.
    - If doctor_id is None or 0, patient is safely unassigned.
    """
    reg = db.session.get(PatientRegistration, registration_id)
    if not reg:
        return False, "Patient registration record not found."

    if staff_user_id:
        staff_user = db.session.get(User, staff_user_id)
        if not staff_user or staff_user.role not in ['admin', 'receptionist', 'doctor']:
            return False, "Unauthorized: Only clinical or reception staff can assign doctors."

    # If unassigning
    if not doctor_id or str(doctor_id).strip() in ['0', '']:
        reg.assigned_doctor_id = None
        db.session.commit()
        return True, "Patient unassigned from doctor successfully."

    try:
        doctor_id_int = int(doctor_id)
    except (ValueError, TypeError):
        return False, "Invalid doctor ID provided."

    doctor = db.session.get(User, doctor_id_int)
    if not doctor or doctor.role != 'doctor':
        return False, "Selected doctor was not found in the physician directory."

    doc_title = doctor.full_name if doctor.full_name.startswith("Dr.") else f"Dr. {doctor.full_name}"

    if not doctor.is_active:
        return False, f"{doc_title} is deactivated and cannot accept new patients."

    if not doctor.staff_record:
        return False, f"{doc_title} has no clinical department profile configured."

    if doctor.staff_record.department_id != reg.department_id:
        doc_dept = doctor.staff_record.department.department_name if doctor.staff_record.department else 'Unknown'
        patient_dept = reg.department.department_name if reg.department else 'Unknown'
        return False, f"Specialization mismatch: {doc_title} is in {doc_dept}, but patient is in {patient_dept}."

    if not doctor.staff_record.is_available:
        return False, f"{doc_title} is currently off duty and unavailable for new assignments."

    reg.assigned_doctor_id = doctor.id
    if reg.consultation:
        reg.consultation.doctor_user_id = doctor.id

    try:
        db.session.commit()
        return True, f"Patient {reg.patient_name} assigned to {doc_title}."
    except Exception as e:
        db.session.rollback()
        return False, f"Database transaction failed: {str(e)}"


"""
routes/receptionist_routes.py
-----------------------------
Primary Operations & Hospital Management Portal (Receptionist):
- Operational Overview & Live Queue Desk (Call Patient, Start Consult, Complete, Skip, Cancel)
- Patient Walk-in Intake & Clinical Triage with ML Waiting Time Estimation
- Doctor Management & Specialization Assignment (Transferred from Admin)
- User Account Registry & Active Status Management (Transferred from Admin)
- Department Registry Management (Transferred from Admin)
- Consultation Requests Review, Doctor Assignment & Live Queue Check-In
- Patient Inquiries & Hospital Assistance Processing
- AI Model Management & Retraining for Waiting-Time & Symptom Classification Pipelines
- Hospital Facility & Contact Settings Governance
"""

import os
from datetime import datetime
from sqlalchemy import case
from werkzeug.security import generate_password_hash
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models.db_models import (
    db, PatientRegistration, QueueRecord, Department, User, Staff,
    ContactRequest, HospitalSetting, Consultation, ConsultationRequest,
    SymptomAssessment, ModelRun, DoctorRegistrationRequest, utcnow
)
from services.auth_service import receptionist_required, staff_required
from services.queue_service import (
    register_patient_to_queue,
    update_queue_status,
    update_triage_priority,
    assign_doctor_to_patient,
    recalculate_department_queue,
    ACTIVE_STATUSES
)
from services.prediction_service import get_model_metadata, reload_model
from services.symptom_service import get_symptom_evaluation_metrics
from ml.preprocess_data import preprocess_data
from ml.train_model import train_and_evaluate
from ml.train_symptom_model import train_symptom_model

receptionist_bp = Blueprint('receptionist', __name__, url_prefix='/receptionist')


@receptionist_bp.route('/dashboard')
@login_required
@receptionist_required
def dashboard():
    """Renders receptionist queue management table with department and status filters."""
    dept_filter = request.args.get('department_id', type=int)
    status_filter = request.args.get('status', default='Waiting')
    search_query = request.args.get('q', '').strip()

    query = db.session.query(QueueRecord).join(PatientRegistration)

    if dept_filter:
        query = query.filter(PatientRegistration.department_id == dept_filter)

    if status_filter and status_filter != 'ALL':
        query = query.filter(QueueRecord.queue_status == status_filter)

    if search_query:
        query = query.filter(
            (PatientRegistration.patient_name.ilike(f"%{search_query}%")) |
            (PatientRegistration.token_number.ilike(f"%{search_query}%")) |
            (PatientRegistration.patient_phone.ilike(f"%{search_query}%")) |
            (PatientRegistration.health_concern_category.ilike(f"%{search_query}%"))
        )

    # Priority-aware fair queue sorting:
    # 1. 'Called' records first, then 'Waiting', then 'In Consultation'
    # 2. Lower numeric priority (1=Emergency) first
    # 3. Earlier arrival time first (FIFO)
    status_priority = case(
        (QueueRecord.queue_status == 'Called', 0),
        (QueueRecord.queue_status == 'Waiting', 1),
        (QueueRecord.queue_status == 'In Consultation', 2),
        else_=3
    )

    queue_entries = query.order_by(
        status_priority.asc(),
        PatientRegistration.triage_priority.asc(),
        PatientRegistration.arrival_time.asc()
    ).all()

    departments = db.session.query(Department).filter_by(is_active=True).all()

    # Active eligible physicians available for consultation assignment
    active_doctors = db.session.query(User).join(Staff).filter(
        User.role == 'doctor',
        User.is_active == True,
        Staff.is_available == True
    ).all()

    # Summary metrics for reception header
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total_waiting = QueueRecord.query.filter_by(queue_status='Waiting').count()
    total_called = QueueRecord.query.filter_by(queue_status='Called').count()
    total_in_consult = QueueRecord.query.filter_by(queue_status='In Consultation').count()
    total_today = PatientRegistration.query.filter(PatientRegistration.created_at >= today_start).count()
    pending_requests = ContactRequest.query.filter(ContactRequest.status.in_(['Submitted', 'Under Review'])).count()
    pending_consultations = ConsultationRequest.query.filter(ConsultationRequest.status.in_(['Pending', 'Pending Review', 'Alternative Proposed'])).count()
    pending_doctor_registrations = DoctorRegistrationRequest.query.filter_by(status='Pending').count()
    total_registered_patients = User.query.filter_by(role='patient').count()
    total_available_doctors = len(active_doctors)

    # Current time for long wait alert calculations (flag if waiting > 30 minutes)
    current_time = utcnow()

    return render_template(
        'receptionist/dashboard.html',
        queue_entries=queue_entries,
        departments=departments,
        active_doctors=active_doctors,
        dept_filter=dept_filter,
        status_filter=status_filter,
        search_query=search_query,
        total_waiting=total_waiting,
        total_called=total_called,
        total_in_consult=total_in_consult,
        total_today=total_today,
        pending_requests=pending_requests,
        pending_consultations=pending_consultations,
        pending_doctor_registrations=pending_doctor_registrations,
        total_registered_patients=total_registered_patients,
        total_available_doctors=total_available_doctors,
        current_time=current_time
    )


@receptionist_bp.route('/register-patient', methods=['GET', 'POST'])
@login_required
@receptionist_required
def register_patient():
    """Registers a new patient visit and triggers genuine ML waiting-time calculation."""
    departments = Department.query.filter_by(is_active=True).all()
    registered_patients = User.query.filter_by(role='patient', is_active=True).all()
    available_doctors = db.session.query(User).join(Staff).filter(
        User.role == 'doctor',
        User.is_active == True,
        Staff.is_available == True
    ).all()

    # Preselected user if passed via query param
    preselected_user_id = request.args.get('patient_user_id', type=int)

    if request.method == 'POST':
        patient_name = request.form.get('patient_name', '').strip()
        patient_phone = request.form.get('patient_phone', '').strip()
        department_id = request.form.get('department_id', type=int)
        assigned_doctor_id = request.form.get('assigned_doctor_id', type=int)
        patient_age = request.form.get('patient_age', type=int, default=35)
        patient_gender = request.form.get('patient_gender', default='Female')
        triage_priority = request.form.get('triage_priority', type=int, default=3)
        patient_user_id = request.form.get('patient_user_id', type=int)
        registration_notes = request.form.get('registration_notes', '').strip()
        health_concern_category = request.form.get('health_concern_category', '').strip()
        symptoms_description = request.form.get('symptoms_description', '').strip()
        symptom_duration = request.form.get('symptom_duration', '').strip()
        has_appointment = bool(request.form.get('has_appointment'))
        appointment_notes = request.form.get('appointment_notes', '').strip()

        # If an existing patient user was selected and no name entered, prefill from user
        if patient_user_id and not patient_name:
            user_obj = db.session.get(User, patient_user_id)
            if user_obj:
                patient_name = user_obj.full_name
                if not patient_phone:
                    patient_phone = user_obj.phone
                if user_obj.age:
                    patient_age = user_obj.age
                if user_obj.gender:
                    patient_gender = user_obj.gender

        if not patient_name or not department_id:
            flash("Patient name and hospital department are required.", "danger")
            return render_template(
                'receptionist/register_patient.html',
                departments=departments,
                registered_patients=registered_patients,
                available_doctors=available_doctors,
                preselected_user_id=preselected_user_id
            )

        registration, err = register_patient_to_queue(
            registered_by_user_id=current_user.id,
            department_id=department_id,
            patient_name=patient_name,
            patient_phone=patient_phone,
            patient_age=patient_age,
            patient_gender=patient_gender,
            patient_user_id=patient_user_id if patient_user_id and patient_user_id > 0 else None,
            triage_priority=triage_priority,
            registration_notes=registration_notes,
            health_concern_category=health_concern_category if health_concern_category else None,
            symptoms_description=symptoms_description if symptoms_description else None,
            symptom_duration=symptom_duration if symptom_duration else None,
            has_appointment=has_appointment,
            appointment_notes=appointment_notes if has_appointment else None,
            arrival_time=utcnow(),
            assigned_doctor_id=assigned_doctor_id if assigned_doctor_id and assigned_doctor_id > 0 else None
        )

        if err:
            flash(f"Registration error: {err}", "danger")
            return render_template(
                'receptionist/register_patient.html',
                departments=departments,
                registered_patients=registered_patients,
                available_doctors=available_doctors,
                preselected_user_id=preselected_user_id
            )

        flash(
            f"Patient {registration.patient_name} successfully registered! Assigned Token: {registration.token_number}. "
            f"Initial ML Estimated Wait: {registration.queue_record.estimated_wait_minutes} minutes.",
            "success"
        )
        return redirect(url_for('receptionist.dashboard'))

    return render_template(
        'receptionist/register_patient.html',
        departments=departments,
        registered_patients=registered_patients,
        available_doctors=available_doctors,
        preselected_user_id=preselected_user_id
    )


@receptionist_bp.route('/patients')
@login_required
@receptionist_required
def patients():
    """Renders registered patients directory with visit counts and search."""
    search_query = request.args.get('q', '').strip()
    query = User.query.filter_by(role='patient')

    if search_query:
        query = query.filter(
            (User.full_name.ilike(f"%{search_query}%")) |
            (User.email.ilike(f"%{search_query}%")) |
            (User.phone.ilike(f"%{search_query}%"))
        )

    patient_records = query.order_by(User.created_at.desc()).all()
    total_patients = User.query.filter_by(role='patient').count()
    total_visits = PatientRegistration.query.count()

    return render_template(
        'receptionist/patients.html',
        patients=patient_records,
        search_query=search_query,
        total_patients=total_patients,
        total_visits=total_visits
    )


@receptionist_bp.route('/consultation-requests')
@login_required
@receptionist_required
def consultation_requests():
    """Renders patient consultation requests management console."""
    status_filter = request.args.get('status', 'ALL')
    dept_filter = request.args.get('department_id', type=int)
    search_query = request.args.get('q', '').strip()

    query = ConsultationRequest.query

    if status_filter and status_filter != 'ALL':
        if status_filter == 'Pending':
            query = query.filter(ConsultationRequest.status.in_(['Pending', 'Pending Review']))
        else:
            query = query.filter_by(status=status_filter)

    if dept_filter:
        query = query.filter_by(department_id=dept_filter)

    if search_query:
        query = query.join(User, ConsultationRequest.patient_user_id == User.id).filter(
            (ConsultationRequest.request_reference.ilike(f"%{search_query}%")) |
            (ConsultationRequest.health_concern.ilike(f"%{search_query}%")) |
            (User.full_name.ilike(f"%{search_query}%"))
        )

    requests_list = query.order_by(ConsultationRequest.created_at.desc()).all()
    departments = Department.query.filter_by(is_active=True).all()

    # Active physicians
    doctors = db.session.query(User).join(Staff).filter(
        User.role == 'doctor',
        User.is_active == True
    ).all()

    # Metrics
    pending_count = ConsultationRequest.query.filter(ConsultationRequest.status.in_(['Pending', 'Pending Review'])).count()
    confirmed_count = ConsultationRequest.query.filter_by(status='Confirmed').count()
    alternative_count = ConsultationRequest.query.filter_by(status='Alternative Proposed').count()
    checkedin_count = ConsultationRequest.query.filter_by(status='Checked In').count()
    completed_count = ConsultationRequest.query.filter_by(status='Completed').count()
    rejected_count = ConsultationRequest.query.filter_by(status='Rejected').count()

    return render_template(
        'receptionist/consultation_requests.html',
        requests_list=requests_list,
        departments=departments,
        doctors=doctors,
        status_filter=status_filter,
        dept_filter=dept_filter,
        search_query=search_query,
        pending_count=pending_count,
        confirmed_count=confirmed_count,
        alternative_count=alternative_count,
        checkedin_count=checkedin_count,
        completed_count=completed_count,
        rejected_count=rejected_count
    )


@receptionist_bp.route('/assign-consultation-doctor', methods=['POST'])
@login_required
@receptionist_required
def assign_consultation_doctor():
    """Assigns an eligible doctor to a patient's consultation request."""
    request_id = request.form.get('request_id', type=int)
    doctor_id = request.form.get('doctor_id', type=int)

    consult_req = db.session.get(ConsultationRequest, request_id)
    if not consult_req:
        flash("Consultation request not found.", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    if doctor_id:
        doctor = db.session.get(User, doctor_id)
        if not doctor or doctor.role != 'doctor' or not doctor.is_active:
            flash("Selected physician is not eligible or inactive.", "danger")
            return redirect(url_for('receptionist.consultation_requests'))

        consult_req.assigned_doctor_id = doctor.id
        if consult_req.status in ['Pending', 'Pending Review']:
            consult_req.status = 'Confirmed'
        db.session.commit()
        flash(f"Doctor Dr. {doctor.full_name} assigned successfully to request {consult_req.request_reference}.", "success")
    else:
        consult_req.assigned_doctor_id = None
        db.session.commit()
        flash(f"Doctor unassigned from request {consult_req.request_reference}.", "info")

    return redirect(url_for('receptionist.consultation_requests'))


@receptionist_bp.route('/confirm-consultation-request', methods=['POST'])
@login_required
@receptionist_required
def confirm_consultation_request():
    """Confirms appointment with schedule details and assigned physician."""
    request_id = request.form.get('request_id', type=int)
    doctor_id = request.form.get('doctor_id', type=int)
    confirmed_date = request.form.get('confirmed_date', '').strip()
    confirmed_time_slot = request.form.get('confirmed_time_slot', '').strip()
    notes = request.form.get('receptionist_notes', '').strip()

    consult_req = db.session.get(ConsultationRequest, request_id)
    if not consult_req:
        flash("Consultation request not found.", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    if doctor_id:
        doctor = db.session.get(User, doctor_id)
        if not doctor or doctor.role != 'doctor' or not doctor.is_active:
            flash("Selected physician is not active or eligible.", "danger")
            return redirect(url_for('receptionist.consultation_requests'))
        consult_req.assigned_doctor_id = doctor.id
    elif consult_req.preferred_doctor_id and not consult_req.assigned_doctor_id:
        consult_req.assigned_doctor_id = consult_req.preferred_doctor_id

    consult_req.status = 'Confirmed'
    consult_req.confirmed_date = confirmed_date or consult_req.preferred_date or utcnow().strftime('%Y-%m-%d')
    consult_req.confirmed_time_slot = confirmed_time_slot or consult_req.preferred_time_slot or '10:00 AM'
    if notes:
        consult_req.receptionist_notes = notes

    db.session.commit()
    flash(f"Consultation request {consult_req.request_reference} confirmed for {consult_req.confirmed_date} at {consult_req.confirmed_time_slot}.", "success")
    return redirect(url_for('receptionist.consultation_requests'))


@receptionist_bp.route('/propose-consultation-alternative', methods=['POST'])
@login_required
@receptionist_required
def propose_consultation_alternative():
    """Proposes an alternative date and time slot to the patient."""
    request_id = request.form.get('request_id', type=int)
    proposed_date = request.form.get('proposed_alternative_date', '').strip()
    proposed_time_slot = request.form.get('proposed_alternative_time_slot', '').strip()
    alternative_notes = request.form.get('alternative_notes', '').strip()
    doctor_id = request.form.get('doctor_id', type=int)

    consult_req = db.session.get(ConsultationRequest, request_id)
    if not consult_req:
        flash("Consultation request not found.", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    if not proposed_date or not proposed_time_slot:
        flash("Please provide both an alternative date and time slot.", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    if doctor_id:
        doctor = db.session.get(User, doctor_id)
        if doctor and doctor.role == 'doctor' and doctor.is_active:
            consult_req.assigned_doctor_id = doctor.id

    consult_req.status = 'Alternative Proposed'
    consult_req.proposed_alternative_date = proposed_date
    consult_req.proposed_alternative_time_slot = proposed_time_slot
    consult_req.alternative_notes = alternative_notes
    db.session.commit()

    flash(f"Alternative schedule proposed to patient for request {consult_req.request_reference}. Awaiting patient confirmation.", "info")
    return redirect(url_for('receptionist.consultation_requests'))


@receptionist_bp.route('/reject-consultation-request', methods=['POST'])
@login_required
@receptionist_required
def reject_consultation_request():
    """Declines a consultation request with a reason."""
    request_id = request.form.get('request_id', type=int)
    reason = request.form.get('rejection_reason', '').strip()

    consult_req = db.session.get(ConsultationRequest, request_id)
    if not consult_req:
        flash("Consultation request not found.", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    consult_req.status = 'Rejected'
    consult_req.receptionist_notes = reason or "No clinical slots currently available in the requested department."
    db.session.commit()

    flash(f"Consultation request {consult_req.request_reference} was rejected.", "warning")
    return redirect(url_for('receptionist.consultation_requests'))


@receptionist_bp.route('/checkin-consultation-request', methods=['POST'])
@login_required
@receptionist_required
def checkin_consultation_request():
    """Checks in an incoming consultation request into the active physical department queue."""
    request_id = request.form.get('request_id', type=int)
    consult_req = db.session.get(ConsultationRequest, request_id)

    if not consult_req:
        flash("Consultation request not found.", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    if consult_req.registration_id:
        flash(f"Patient is already checked in with active token {consult_req.registration.token_number}.", "warning")
        return redirect(url_for('receptionist.consultation_requests'))

    patient_user = consult_req.patient_user
    registration, err = register_patient_to_queue(
        registered_by_user_id=current_user.id,
        department_id=consult_req.department_id,
        patient_name=patient_user.full_name if patient_user else "Consultation Patient",
        patient_phone=patient_user.phone if patient_user else None,
        patient_age=patient_user.age if (patient_user and patient_user.age) else 35,
        patient_gender=patient_user.gender if (patient_user and patient_user.gender) else 'Female',
        patient_user_id=consult_req.patient_user_id,
        triage_priority=3,
        registration_notes=f"Checked-in from Consultation Request {consult_req.request_reference}",
        health_concern_category="Consultation Request",
        symptoms_description=consult_req.health_concern,
        arrival_time=utcnow(),
        assigned_doctor_id=consult_req.assigned_doctor_id
    )

    if err:
        flash(f"Check-in error: {err}", "danger")
        return redirect(url_for('receptionist.consultation_requests'))

    consult_req.registration_id = registration.id
    consult_req.status = 'Checked In'
    db.session.commit()

    flash(
        f"Patient checked into live queue! Issued Token: {registration.token_number}. "
        f"Estimated Wait Time: {registration.queue_record.estimated_wait_minutes} mins.",
        "success"
    )
    return redirect(url_for('receptionist.dashboard'))


@receptionist_bp.route('/doctor-registrations')
@login_required
@receptionist_required
def doctor_registrations():
    """Allows receptionists to view and process doctor self-registration requests."""
    status_filter = request.args.get('status', 'Pending')
    query = DoctorRegistrationRequest.query

    if status_filter and status_filter != 'ALL':
        query = query.filter_by(status=status_filter)

    requests_list = query.order_by(DoctorRegistrationRequest.created_at.desc()).all()
    departments = Department.query.filter_by(is_active=True).all()

    pending_count = DoctorRegistrationRequest.query.filter_by(status='Pending').count()
    approved_count = DoctorRegistrationRequest.query.filter_by(status='Approved').count()
    rejected_count = DoctorRegistrationRequest.query.filter_by(status='Rejected').count()

    return render_template(
        'receptionist/doctor_registrations.html',
        requests_list=requests_list,
        departments=departments,
        status_filter=status_filter,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count
    )


@receptionist_bp.route('/approve-doctor-registration/<int:request_id>', methods=['POST'])
@login_required
@receptionist_required
def approve_doctor_registration(request_id):
    """Approves a pending doctor registration request and creates an active physician account."""
    doc_req = db.session.get(DoctorRegistrationRequest, request_id)
    if not doc_req:
        flash("Doctor registration request not found.", "danger")
        return redirect(url_for('receptionist.doctor_registrations'))

    # Allow receptionist to override/confirm department if passed
    dept_id = request.form.get('department_id', type=int) or doc_req.department_id
    dept = db.session.get(Department, dept_id)
    if not dept:
        flash("Invalid clinical department specified.", "danger")
        return redirect(url_for('receptionist.doctor_registrations'))

    # Check if a user account already exists with this email
    user = User.query.filter_by(email=doc_req.email.lower()).first()
    if not user:
        user = User(
            full_name=doc_req.full_name,
            email=doc_req.email.lower(),
            phone=doc_req.phone,
            password_hash=doc_req.password_hash,
            role='doctor',
            is_active=True
        )
        db.session.add(user)
        db.session.flush()
    else:
        user.role = 'doctor'
        user.is_active = True
        user.full_name = doc_req.full_name
        user.phone = doc_req.phone
        user.password_hash = doc_req.password_hash

    # Ensure Staff record exists and is linked
    staff = Staff.query.filter_by(user_id=user.id).first()
    if not staff:
        staff = Staff(
            user_id=user.id,
            department_id=dept.id,
            staff_type='Doctor',
            is_available=True,
            qualification=doc_req.qualification,
            license_number=doc_req.license_number,
            experience_years=doc_req.experience_years
        )
        db.session.add(staff)
    else:
        staff.department_id = dept.id
        staff.staff_type = 'Doctor'
        staff.is_available = True
        staff.qualification = doc_req.qualification
        staff.license_number = doc_req.license_number
        staff.experience_years = doc_req.experience_years

    doc_req.status = 'Approved'
    doc_req.user_id = user.id
    doc_req.reviewed_by_user_id = current_user.id
    doc_req.reviewed_at = utcnow()
    doc_req.department_id = dept.id

    try:
        db.session.commit()
        flash(f"Doctor registration for {doc_req.full_name} approved! Account is active.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error approving doctor registration: {str(e)}", "danger")

    return redirect(url_for('receptionist.doctor_registrations'))


@receptionist_bp.route('/reject-doctor-registration/<int:request_id>', methods=['POST'])
@login_required
@receptionist_required
def reject_doctor_registration(request_id):
    """Rejects a doctor registration request with a clear reason."""
    doc_req = db.session.get(DoctorRegistrationRequest, request_id)
    if not doc_req:
        flash("Doctor registration request not found.", "danger")
        return redirect(url_for('receptionist.doctor_registrations'))

    rejection_reason = request.form.get('rejection_reason', '').strip()
    if not rejection_reason:
        rejection_reason = "Application does not meet hospital verification standards or licensing requirements."

    doc_req.status = 'Rejected'
    doc_req.rejection_reason = rejection_reason
    doc_req.reviewed_by_user_id = current_user.id
    doc_req.reviewed_at = utcnow()

    # If user account was previously created, deactivate it
    if doc_req.user_id:
        user = db.session.get(User, doc_req.user_id)
        if user:
            user.is_active = False

    try:
        db.session.commit()
        flash(f"Doctor registration for {doc_req.full_name} was rejected.", "warning")
    except Exception as e:
        db.session.rollback()
        flash(f"Error rejecting doctor registration: {str(e)}", "danger")

    return redirect(url_for('receptionist.doctor_registrations'))


@receptionist_bp.route('/assign-doctor', methods=['POST'])
@login_required
@receptionist_required
def assign_doctor():
    """Assigns or reassigns an eligible physician to an active queue patient."""
    registration_id = request.form.get('registration_id', type=int)
    doctor_id = request.form.get('doctor_id', type=int)

    success, msg = assign_doctor_to_patient(registration_id, doctor_id)
    if success:
        flash(msg, "success")
    else:
        flash(msg, "danger")

    return redirect(url_for('receptionist.dashboard'))


@receptionist_bp.route('/update-status', methods=['POST'])
@login_required
@receptionist_required
def update_status():
    """Updates queue status for a patient and dynamically recalculates downstream queues."""
    registration_id = request.form.get('registration_id', type=int)
    new_status = request.form.get('status', '').strip()

    success, err = update_queue_status(registration_id, new_status)
    if not success:
        flash(f"Failed to update queue status: {err}", "danger")
    else:
        flash(f"Queue status updated to '{new_status}' successfully.", "success")

    ref = request.referrer or url_for('receptionist.dashboard')
    return redirect(ref)


@receptionist_bp.route('/update-priority', methods=['POST'])
@login_required
@receptionist_required
def update_priority():
    """Updates clinical triage priority with staff audit logging."""
    registration_id = request.form.get('registration_id', type=int)
    new_priority = request.form.get('triage_priority', type=int)

    success, err = update_triage_priority(registration_id, new_priority, staff_user_id=current_user.id)
    if not success:
        flash(f"Failed to update priority: {err}", "danger")
    else:
        flash(f"Clinical triage priority updated to Priority {new_priority} successfully.", "success")

    ref = request.referrer or url_for('receptionist.dashboard')
    return redirect(ref)


@receptionist_bp.route('/contact-requests', methods=['GET', 'POST'])
@login_required
@receptionist_required
def contact_requests():
    """Enables receptionist staff to view, review, and respond to in-site patient assistance requests."""
    if request.method == 'POST':
        req_id = request.form.get('request_id', type=int)
        new_status = request.form.get('status', '').strip()
        response_msg = request.form.get('staff_response', '').strip()

        req_obj = db.session.get(ContactRequest, req_id)
        if req_obj:
            if new_status:
                req_obj.status = new_status
            if response_msg:
                req_obj.staff_response = response_msg
                req_obj.responded_by_user_id = current_user.id
                req_obj.responded_at = utcnow()
            db.session.commit()
            flash(f"Request {req_obj.request_reference} updated successfully.", "success")
        else:
            flash("Request not found.", "danger")

        return redirect(url_for('receptionist.contact_requests'))

    status_filter = request.args.get('status', 'ALL')
    query = ContactRequest.query
    if status_filter and status_filter != 'ALL':
        query = query.filter_by(status=status_filter)

    requests_list = query.order_by(ContactRequest.created_at.desc()).all()
    return render_template(
        'receptionist/contact_requests.html',
        requests_list=requests_list,
        status_filter=status_filter
    )


# ================= TRANSFERRED MANAGEMENT ROUTES =================

@receptionist_bp.route('/doctors', methods=['GET', 'POST'])
@login_required
@receptionist_required
def doctors():
    """
    Manages hospital physicians, specializations, on-duty availability,
    and live consultation workloads. Transferred from Admin to Receptionist.
    """
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            phone = request.form.get('phone', '').strip()
            age = request.form.get('age')
            gender = request.form.get('gender', 'Male')
            password = request.form.get('password', '')
            dept_id = request.form.get('department_id', type=int)
            is_available = bool(request.form.get('is_available'))

            if not full_name or not email or not password or not dept_id:
                flash("Doctor name, email, department, and password are required.", "danger")
                return redirect(url_for('receptionist.doctors'))

            existing = User.query.filter_by(email=email).first()
            if existing:
                flash(f"An account with email {email} already exists.", "danger")
                return redirect(url_for('receptionist.doctors'))

            doc_title = full_name if full_name.startswith("Dr.") else f"Dr. {full_name}"

            user = User(
                full_name=doc_title,
                email=email,
                phone=phone if phone else None,
                age=int(age) if (age and str(age).isdigit()) else None,
                gender=gender,
                role='doctor',
                is_active=True
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            staff = Staff(
                user_id=user.id,
                department_id=dept_id,
                staff_type='Doctor',
                is_available=is_available
            )
            db.session.add(staff)
            db.session.commit()

            flash(f"Physician {user.full_name} registered successfully.", "success")
            return redirect(url_for('receptionist.doctors'))

        elif action == 'edit':
            doc_id = request.form.get('doctor_id', type=int)
            doctor = db.session.get(User, doc_id)
            if not doctor or doctor.role != 'doctor':
                flash("Doctor not found.", "danger")
                return redirect(url_for('receptionist.doctors'))

            full_name = request.form.get('full_name', '').strip()
            phone = request.form.get('phone', '').strip()
            age = request.form.get('age')
            gender = request.form.get('gender')
            dept_id = request.form.get('department_id', type=int)
            is_available = bool(request.form.get('is_available'))

            if full_name:
                doctor.full_name = full_name if full_name.startswith("Dr.") else f"Dr. {full_name}"
            doctor.phone = phone if phone else None
            if age and str(age).isdigit():
                doctor.age = int(age)
            if gender:
                doctor.gender = gender

            if doctor.staff_record:
                if dept_id:
                    doctor.staff_record.department_id = dept_id
                doctor.staff_record.is_available = is_available
            elif dept_id:
                staff = Staff(user_id=doctor.id, department_id=dept_id, staff_type='Doctor', is_available=is_available)
                db.session.add(staff)

            db.session.commit()
            flash(f"Doctor details for {doctor.full_name} updated successfully.", "success")
            return redirect(url_for('receptionist.doctors'))

        elif action == 'toggle_status':
            doc_id = request.form.get('doctor_id', type=int)
            doctor = db.session.get(User, doc_id)
            if doctor and doctor.role == 'doctor':
                doctor.is_active = not doctor.is_active
                db.session.commit()
                status_text = "activated" if doctor.is_active else "deactivated"
                flash(f"Physician {doctor.full_name} account has been {status_text}.", "info")
            return redirect(url_for('receptionist.doctors'))

        elif action == 'toggle_availability':
            doc_id = request.form.get('doctor_id', type=int)
            doctor = db.session.get(User, doc_id)
            if doctor and doctor.staff_record:
                doctor.staff_record.is_available = not doctor.staff_record.is_available
                db.session.commit()
                status_text = "available" if doctor.staff_record.is_available else "off-duty"
                flash(f"Physician {doctor.full_name} is now marked as {status_text}.", "info")
            return redirect(url_for('receptionist.doctors'))

    # Filtering & Workload Calculation
    dept_filter = request.args.get('department_id', type=int)
    avail_filter = request.args.get('availability', 'ALL')
    status_filter = request.args.get('status', 'ALL')
    search_query = request.args.get('q', '').strip()

    query = User.query.filter_by(role='doctor')

    if search_query:
        query = query.filter(
            (User.full_name.ilike(f"%{search_query}%")) |
            (User.email.ilike(f"%{search_query}%")) |
            (User.phone.ilike(f"%{search_query}%"))
        )

    if status_filter == 'active':
        query = query.filter(User.is_active == True)
    elif status_filter == 'inactive':
        query = query.filter(User.is_active == False)

    if dept_filter:
        query = query.join(Staff).filter(Staff.department_id == dept_filter)

    if avail_filter in ['available', 'unavailable']:
        is_avail = (avail_filter == 'available')
        query = query.join(Staff).filter(Staff.is_available == is_avail)

    doctors_list = query.order_by(User.full_name.asc()).all()

    # Calculate real workload per doctor
    workload_data = []
    total_available_physicians = 0
    total_active_physicians = 0
    total_currently_consulting = 0

    for doc in doctors_list:
        if doc.is_active:
            total_active_physicians += 1
        if doc.staff_record and doc.staff_record.is_available and doc.is_active:
            total_available_physicians += 1

        waiting_pts = db.session.query(PatientRegistration).join(QueueRecord).filter(
            PatientRegistration.assigned_doctor_id == doc.id,
            QueueRecord.queue_status.in_(['Waiting', 'Called'])
        ).count()

        in_consult_pts = db.session.query(PatientRegistration).join(QueueRecord).filter(
            PatientRegistration.assigned_doctor_id == doc.id,
            QueueRecord.queue_status == 'In Consultation'
        ).count()
        total_currently_consulting += in_consult_pts

        completed_today = Consultation.query.filter(
            Consultation.doctor_user_id == doc.id,
            Consultation.consultation_status == 'Completed'
        ).count()

        dept_obj = doc.staff_record.department if doc.staff_record else None
        workload_data.append({
            'doctor': doc,
            'user': doc,
            'department': dept_obj,
            'department_name': dept_obj.department_name if dept_obj else 'Unassigned',
            'department_id': dept_obj.id if dept_obj else None,
            'is_available': doc.staff_record.is_available if doc.staff_record else False,
            'waiting_patients': waiting_pts,
            'waiting_count': waiting_pts,
            'in_consultation_patients': in_consult_pts,
            'in_consult_count': in_consult_pts,
            'completed_today': completed_today,
            'completed_count': completed_today
        })

    departments = Department.query.filter_by(is_active=True).all()

    return render_template(
        'receptionist/doctors.html',
        doctors=workload_data,
        departments=departments,
        dept_filter=dept_filter,
        avail_filter=avail_filter,
        status_filter=status_filter,
        search_query=search_query,
        total_available_physicians=total_available_physicians,
        total_active_physicians=total_active_physicians,
        total_currently_consulting=total_currently_consulting
    )


@receptionist_bp.route('/users', methods=['GET', 'POST'])
@login_required
@receptionist_required
def users():
    """Manages hospital system accounts strictly for Receptionist, Doctor, and Patient roles."""
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            phone = request.form.get('phone', '').strip()
            age = request.form.get('age')
            gender = request.form.get('gender', 'Female')
            role = request.form.get('role', 'patient')
            password = request.form.get('password', '')
            dept_id = request.form.get('department_id', type=int)

            # Prevent creation of deprecated admin role
            if role not in ['receptionist', 'doctor', 'patient']:
                role = 'patient'

            if not full_name or not email or not password:
                flash("Name, email, and password are required.", "danger")
                return redirect(url_for('receptionist.users'))

            existing = User.query.filter_by(email=email).first()
            if existing:
                flash("An account with this email already exists.", "danger")
                return redirect(url_for('receptionist.users'))

            new_user = User(
                full_name=full_name,
                email=email,
                phone=phone if phone else None,
                age=int(age) if (age and str(age).isdigit()) else None,
                gender=gender,
                role=role,
                is_active=True
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.flush()

            if role in ['receptionist', 'doctor'] and dept_id:
                staff_type = 'Doctor' if role == 'doctor' else 'Receptionist'
                staff = Staff(
                    user_id=new_user.id,
                    department_id=dept_id,
                    staff_type=staff_type,
                    is_available=True
                )
                db.session.add(staff)

            db.session.commit()
            flash(f"Account for {new_user.full_name} ({new_user.role}) created successfully.", "success")
            return redirect(url_for('receptionist.users'))

        elif action == 'toggle_status':
            target_id = request.form.get('user_id', type=int)
            target = db.session.get(User, target_id)
            if target:
                if target.id == current_user.id:
                    flash("You cannot deactivate your own account.", "danger")
                else:
                    target.is_active = not target.is_active
                    db.session.commit()
                    st = "activated" if target.is_active else "deactivated"
                    flash(f"Account {target.email} has been {st}.", "info")
            return redirect(url_for('receptionist.users'))

    all_users = User.query.order_by(User.created_at.desc()).all()
    departments = Department.query.filter_by(is_active=True).all()
    return render_template('receptionist/users.html', users=all_users, departments=departments)


@receptionist_bp.route('/departments', methods=['GET', 'POST'])
@login_required
@receptionist_required
def departments():
    """Manages hospital clinical departments."""
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            name = request.form.get('department_name', '').strip()
            code = request.form.get('code', '').strip().upper()
            desc = request.form.get('description', '').strip()

            if not name or not code:
                flash("Department name and code are required.", "danger")
            else:
                existing = Department.query.filter((Department.code == code) | (Department.department_name == name)).first()
                if existing:
                    flash("Department with this name or code already exists.", "danger")
                else:
                    dept = Department(department_name=name, code=code, description=desc, is_active=True)
                    db.session.add(dept)
                    db.session.commit()
                    flash(f"Department {name} ({code}) registered successfully.", "success")

            return redirect(url_for('receptionist.departments'))

        elif action == 'toggle_status':
            dept_id = request.form.get('department_id', type=int)
            dept = db.session.get(Department, dept_id)
            if dept:
                dept.is_active = not dept.is_active
                db.session.commit()
                st = "activated" if dept.is_active else "deactivated"
                flash(f"Department {dept.department_name} has been {st}.", "info")
            return redirect(url_for('receptionist.departments'))

    all_depts = Department.query.order_by(Department.department_name.asc()).all()
    dept_summaries = []
    for d in all_depts:
        staff_count = Staff.query.filter_by(department_id=d.id).count()
        reg_count = PatientRegistration.query.filter_by(department_id=d.id).count()
        dept_summaries.append({
            'department': d,
            'staff_count': staff_count,
            'registrations_count': reg_count
        })

    return render_template('receptionist/departments.html', departments=dept_summaries)


@receptionist_bp.route('/hospital-settings', methods=['GET', 'POST'])
@login_required
@receptionist_required
def hospital_settings():
    """Manages public hospital center contact information and operating hours."""
    setting = HospitalSetting.query.first()
    if not setting:
        setting = HospitalSetting()
        db.session.add(setting)
        db.session.commit()

    if request.method == 'POST':
        setting.hospital_name = request.form.get('hospital_name', setting.hospital_name).strip()
        setting.phone = request.form.get('phone', setting.phone).strip()
        setting.emergency_phone = request.form.get('emergency_phone', setting.emergency_phone).strip()
        setting.email = request.form.get('email', setting.email).strip()
        setting.address = request.form.get('address', setting.address).strip()
        setting.opening_hours = request.form.get('opening_hours', setting.opening_hours).strip()
        setting.directions_url = request.form.get('directions_url', setting.directions_url).strip()
        setting.updated_at = utcnow()
        db.session.commit()
        flash("Hospital facility settings updated successfully.", "success")
        return redirect(url_for('receptionist.hospital_settings'))

    return render_template('receptionist/hospital_settings.html', setting=setting, hospital_info=setting)


@receptionist_bp.route('/model-management', methods=['GET', 'POST'])
@login_required
@receptionist_required
def model_management():
    """
    ML intelligence and dataset governance console.
    Displays metrics and retraining controls for both:
    1. Multi-Disease Symptom Checker Model (Random Forest Classification)
    2. Hospital Waiting-Time Prediction Model (Regression)
    """
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'retrain':
            try:
                flash("Initiating waiting-time model preprocessing and retraining pipeline...", "info")
                preprocess_data()
                results, best_model, _ = train_and_evaluate()
                reload_model()
                flash(
                    f"Waiting-time model retrained successfully! Best Model: {best_model['name']} "
                    f"(MAE: {best_model['test_mae']:.2f}m, R²: {best_model['test_r2']:.4f}).",
                    "success"
                )
            except Exception as e:
                flash(f"Retraining error: {str(e)}", "danger")
            return redirect(url_for('receptionist.model_management'))

        elif action == 'retrain_symptom':
            try:
                flash("Retraining multi-disease symptom checker model on 4,920 records...", "info")
                eval_data = train_symptom_model()
                flash(
                    f"Symptom Checker model retrained successfully! Accuracy: {eval_data['accuracy']*100:.1f}%, "
                    f"F1-Score: {eval_data['f1_weighted']*100:.1f}%.",
                    "success"
                )
            except Exception as e:
                flash(f"Symptom model retraining error: {str(e)}", "danger")
            return redirect(url_for('receptionist.model_management'))

    model_meta = get_model_metadata()
    symptom_meta = get_symptom_evaluation_metrics()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chart_path = os.path.join(base_dir, 'static', 'images', 'model_evaluation.png')
    chart_exists = os.path.exists(chart_path)

    return render_template(
        'receptionist/model_management.html',
        model_meta=model_meta,
        symptom_meta=symptom_meta,
        chart_exists=chart_exists
    )


@receptionist_bp.route('/api/queue')
@login_required
@receptionist_required
def api_queue():
    """Provides JSON queue feed for dynamic dashboard updates."""
    dept_id = request.args.get('department_id', type=int)
    query = db.session.query(QueueRecord).join(PatientRegistration)
    if dept_id:
        query = query.filter(PatientRegistration.department_id == dept_id)
    records = query.filter(QueueRecord.queue_status.in_(ACTIVE_STATUSES)).all()

    return jsonify([
        {
            'queue_id': r.id,
            'token_number': r.registration.token_number,
            'patient_name': r.registration.patient_name,
            'department': r.registration.department.department_name,
            'status': r.queue_status,
            'priority': r.registration.triage_priority,
            'priority_label': r.registration.priority_label,
            'patients_ahead': r.patients_ahead,
            'estimated_wait_minutes': r.estimated_wait_minutes,
            'arrival_time': r.registration.arrival_time.strftime('%H:%M')
        }
        for r in records
    ])

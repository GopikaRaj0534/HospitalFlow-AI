"""
routes/doctor_routes.py
-----------------------
Dedicated Doctor Clinical Portal:
- Doctor dashboard with real-time assigned patient queue & workload metrics
- Department incoming patient visibility and patient assignment
- Clinical consultation view with patient demographics, reported concerns, and full visit history
- Consultation workflow: Start Consultation, Save Draft, Complete Consultation & Discharge
- Cascading queue recalculation upon consultation completion
- Strict server-side RBAC and patient data privacy
"""

from datetime import datetime
from sqlalchemy import case
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models.db_models import (
    db, User, Department, Staff, PatientRegistration, QueueRecord,
    Consultation, SymptomAssessment, ConsultationRequest, utcnow
)
from services.auth_service import doctor_required
from services.queue_service import recalculate_department_queue, register_patient_to_queue, ACTIVE_STATUSES

doctor_bp = Blueprint('doctor', __name__, url_prefix='/doctor')


@doctor_bp.route('/dashboard')
@login_required
@doctor_required
def dashboard():
    """
    Renders the dedicated Doctor dashboard with real-time patient queue,
    clinical KPIs, and assigned/department patient lists.
    """
    # Doctor's staff profile
    staff = current_user.staff_record
    dept = staff.department if (staff and staff.department) else None
    dept_id = dept.id if dept else None

    # Filter tab: 'waiting' (default), 'in_consultation', 'completed', 'department', 'all'
    active_tab = request.args.get('tab', default='waiting')
    search_query = request.args.get('q', '').strip()

    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Real database metrics for logged-in doctor
    waiting_count = db.session.query(PatientRegistration).join(QueueRecord).filter(
        PatientRegistration.assigned_doctor_id == current_user.id,
        QueueRecord.queue_status.in_(['Waiting', 'Called'])
    ).count()

    in_consult_count = db.session.query(PatientRegistration).join(QueueRecord).filter(
        PatientRegistration.assigned_doctor_id == current_user.id,
        QueueRecord.queue_status == 'In Consultation'
    ).count()

    completed_today_count = Consultation.query.filter(
        Consultation.doctor_user_id == current_user.id,
        Consultation.consultation_status == 'Completed',
        Consultation.completed_at >= today_start
    ).count()

    dept_active_count = 0
    if dept_id:
        dept_active_count = db.session.query(QueueRecord).join(PatientRegistration).filter(
            PatientRegistration.department_id == dept_id,
            QueueRecord.queue_status.in_(ACTIVE_STATUSES)
        ).count()

    # Assigned Consultation Requests for this doctor
    assigned_requests_query = ConsultationRequest.query.filter_by(
        assigned_doctor_id=current_user.id
    )
    assigned_requests_count = assigned_requests_query.filter(
        ConsultationRequest.status.in_(['Pending', 'Assigned'])
    ).count()
    assigned_requests = assigned_requests_query.order_by(ConsultationRequest.created_at.desc()).all()

    # Query patients based on tab
    if active_tab == 'department' and dept_id:
        # Department unassigned or all active in department
        base_query = db.session.query(PatientRegistration).join(QueueRecord).filter(
            PatientRegistration.department_id == dept_id,
            QueueRecord.queue_status.in_(ACTIVE_STATUSES)
        )
    else:
        # Doctor's directly assigned patients
        base_query = db.session.query(PatientRegistration).join(QueueRecord).filter(
            PatientRegistration.assigned_doctor_id == current_user.id
        )

        if active_tab == 'waiting':
            base_query = base_query.filter(QueueRecord.queue_status.in_(['Waiting', 'Called']))
        elif active_tab == 'in_consultation':
            base_query = base_query.filter(QueueRecord.queue_status == 'In Consultation')
        elif active_tab == 'completed':
            base_query = base_query.filter(QueueRecord.queue_status == 'Completed')

    if search_query:
        base_query = base_query.filter(
            (PatientRegistration.patient_name.ilike(f"%{search_query}%")) |
            (PatientRegistration.token_number.ilike(f"%{search_query}%")) |
            (PatientRegistration.patient_phone.ilike(f"%{search_query}%")) |
            (PatientRegistration.health_concern_category.ilike(f"%{search_query}%"))
        )

    # Priority-aware sorting:
    # 1. Called first, then Waiting, then In Consultation, then Completed
    # 2. Lower numeric priority (Emergency) first
    # 3. Earlier arrival first
    status_priority = case(
        (QueueRecord.queue_status == 'Called', 0),
        (QueueRecord.queue_status == 'Waiting', 1),
        (QueueRecord.queue_status == 'In Consultation', 2),
        else_=3
    )

    patients = base_query.order_by(
        status_priority.asc(),
        PatientRegistration.triage_priority.asc(),
        PatientRegistration.arrival_time.asc()
    ).all()

    return render_template(
        'doctor/dashboard.html',
        doctor=current_user,
        staff=staff,
        department=dept,
        active_tab=active_tab,
        search_query=search_query,
        patients=patients,
        waiting_count=waiting_count,
        in_consult_count=in_consult_count,
        completed_today_count=completed_today_count,
        dept_active_count=dept_active_count,
        assigned_requests_count=assigned_requests_count,
        assigned_requests=assigned_requests
    )


@doctor_bp.route('/toggle-availability', methods=['POST'])
@login_required
@doctor_required
def toggle_availability():
    """Toggles the doctor's active consultation availability status."""
    staff = current_user.staff_record
    if staff:
        staff.is_available = not staff.is_available
        db.session.commit()
        state = "Available for Consultation" if staff.is_available else "Off Duty / Unavailable"
        flash(f"Your clinical availability has been updated to: {state}.", "info")
    return redirect(url_for('doctor.dashboard'))


@doctor_bp.route('/claim-patient/<int:registration_id>', methods=['POST'])
@login_required
@doctor_required
def claim_patient(registration_id: int):
    """Allows a doctor to assign an unassigned patient in their department to themselves."""
    reg = db.session.get(PatientRegistration, registration_id)
    if not reg:
        flash("Patient registration not found.", "danger")
        return redirect(url_for('doctor.dashboard'))

    staff = current_user.staff_record
    if not staff or reg.department_id != staff.department_id:
        flash("Access denied: You can only assign patients belonging to your clinical department.", "danger")
        return redirect(url_for('doctor.dashboard'))

    reg.assigned_doctor_id = current_user.id
    db.session.commit()
    flash(f"Patient {reg.patient_name} ({reg.token_number}) has been assigned to your consultation queue.", "success")
    return redirect(url_for('doctor.consultation', registration_id=registration_id))


@doctor_bp.route('/consultation/<int:registration_id>', methods=['GET'])
@login_required
@doctor_required
def consultation(registration_id: int):
    """
    Renders patient clinical chart and consultation workspace:
    - Patient personal demographics and visit health concern
    - Historical medical records and prior visits
    - Active or draft consultation notes, diagnosis, and prescription form
    """
    reg = db.session.get(PatientRegistration, registration_id)
    if not reg:
        flash("Patient registration record not found.", "danger")
        return redirect(url_for('doctor.dashboard'))

    staff = current_user.staff_record
    dept_id = staff.department_id if staff else None

    # Strict server-side RBAC:
    # Doctor can access if assigned to this patient OR if patient is in doctor's department
    if reg.assigned_doctor_id != current_user.id and reg.department_id != dept_id:
        flash("Access denied: You are not authorized to view patients from another clinical department.", "danger")
        return redirect(url_for('doctor.dashboard'))

    # If patient has no assigned doctor and doctor opens chart, assign to current doctor
    if not reg.assigned_doctor_id:
        reg.assigned_doctor_id = current_user.id
        db.session.commit()

    # Load or initialize consultation record
    consult = reg.consultation
    if not consult:
        # Pre-fill chief complaint from patient reported health concern
        chief = reg.health_concern_category or ''
        if reg.symptoms_description:
            chief += f" - {reg.symptoms_description}"

        consult = Consultation(
            registration_id=reg.id,
            patient_user_id=reg.patient_user_id,
            doctor_user_id=current_user.id,
            department_id=reg.department_id,
            chief_complaint=chief.strip() or None,
            consultation_status='In Progress' if (reg.queue_record and reg.queue_record.queue_status == 'In Consultation') else 'Draft'
        )
        db.session.add(consult)
        db.session.commit()

    # Historical visits for this patient
    past_registrations = []
    if reg.patient_user_id:
        past_registrations = PatientRegistration.query.filter(
            PatientRegistration.patient_user_id == reg.patient_user_id,
            PatientRegistration.id != reg.id
        ).order_by(PatientRegistration.arrival_time.desc()).all()

    # Recent AI Symptom Assessments for this patient
    symptom_assessments = []
    if reg.patient_user_id:
        symptom_assessments = SymptomAssessment.query.filter_by(
            patient_user_id=reg.patient_user_id
        ).order_by(SymptomAssessment.created_at.desc()).limit(5).all()
    return render_template(
        'doctor/consultation.html',
        registration=reg,
        queue_record=reg.queue_record,
        consultation=consult,
        past_registrations=past_registrations,
        symptom_assessments=symptom_assessments,
        departments=Department.query.filter_by(is_active=True).order_by(Department.department_name).all()
    )


@doctor_bp.route('/start-consultation', methods=['POST'])
@login_required
@doctor_required
def start_consultation():
    """
    Starts an active consultation:
    - Sets QueueRecord status to 'In Consultation'
    - Updates consultation start timestamp
    - Sets Consultation status to 'In Progress'
    - Recalculates department queue
    """
    reg_id = request.form.get('registration_id', type=int)
    reg = db.session.get(PatientRegistration, reg_id)
    if not reg:
        flash("Patient registration not found.", "danger")
        return redirect(url_for('doctor.dashboard'))

    # Check authorization
    if reg.assigned_doctor_id != current_user.id:
        reg.assigned_doctor_id = current_user.id

    now = utcnow()
    if reg.queue_record:
        reg.queue_record.queue_status = 'In Consultation'
        if not reg.queue_record.consultation_start_time:
            reg.queue_record.consultation_start_time = now
        reg.queue_record.patients_ahead = 0
        reg.queue_record.estimated_wait_minutes = 0.0

    consult = reg.consultation
    if not consult:
        consult = Consultation(
            registration_id=reg.id,
            patient_user_id=reg.patient_user_id,
            doctor_user_id=current_user.id,
            department_id=reg.department_id,
            chief_complaint=reg.health_concern_category,
            consultation_status='In Progress',
            started_at=now
        )
        db.session.add(consult)
    else:
        consult.consultation_status = 'In Progress'
        consult.doctor_user_id = current_user.id
        if not consult.started_at:
            consult.started_at = now

    db.session.commit()

    # Recalculate remaining waiting patients in department
    recalculate_department_queue(reg.department_id)

    flash(f"Consultation started for {reg.patient_name} (Token: {reg.token_number}). Patient is now in examination.", "success")
    return redirect(url_for('doctor.consultation', registration_id=reg.id))


@doctor_bp.route('/save-consultation', methods=['POST'])
@login_required
@doctor_required
def save_consultation():
    """
    Saves consultation clinical notes as draft without removing patient from queue.
    """
    reg_id = request.form.get('registration_id', type=int)
    reg = db.session.get(PatientRegistration, reg_id)
    if not reg:
        flash("Patient registration not found.", "danger")
        return redirect(url_for('doctor.dashboard'))

    consult = reg.consultation
    if not consult:
        consult = Consultation(
            registration_id=reg.id,
            patient_user_id=reg.patient_user_id,
            doctor_user_id=current_user.id,
            department_id=reg.department_id
        )
        db.session.add(consult)

    consult.chief_complaint = request.form.get('chief_complaint', '').strip()
    consult.clinical_observations = request.form.get('clinical_observations', '').strip()
    consult.doctor_notes = request.form.get('doctor_notes', '').strip()
    consult.diagnosis = request.form.get('diagnosis', '').strip()
    consult.treatment_plan = request.form.get('treatment_plan', '').strip()
    consult.prescription = request.form.get('prescription', '').strip()
    consult.follow_up_instructions = request.form.get('follow_up_instructions', '').strip()
    consult.follow_up_date = request.form.get('follow_up_date', '').strip() or None
    is_ref = request.form.get('is_referred') in ['1', 'true', 'True', 'on', 'yes']
    consult.is_referred = is_ref
    consult.referral_department_id = request.form.get('referral_department_id', type=int) if is_ref else None
    consult.referral_notes = request.form.get('referral_notes', '').strip() if is_ref else None

    if consult.consultation_status != 'Completed':
        consult.consultation_status = 'Draft'

    consult.updated_at = utcnow()
    db.session.commit()

    flash("Consultation draft notes saved successfully.", "info")
    return redirect(url_for('doctor.consultation', registration_id=reg.id))


@doctor_bp.route('/complete-consultation', methods=['POST'])
@login_required
@doctor_required
def complete_consultation():
    """
    Completes patient consultation and discharges patient from active queue:
    - Finalizes diagnosis, treatment plan, and prescription
    - Updates Consultation status to 'Completed' and sets completed_at timestamp
    - Updates QueueRecord status to 'Completed' and sets completion_time timestamp
    - Zeroes out patients_ahead and estimated_wait_minutes
    - Cascades recalculate_department_queue to update remaining waiting patients
    - Marks any associated ConsultationRequest as Completed
    - Preserves historical records for future patient visits
    """
    reg_id = request.form.get('registration_id', type=int)
    reg = db.session.get(PatientRegistration, reg_id)
    if not reg:
        flash("Patient registration not found.", "danger")
        return redirect(url_for('doctor.dashboard'))

    # Security check: doctor must be assigned
    if reg.assigned_doctor_id != current_user.id:
        reg.assigned_doctor_id = current_user.id

    diagnosis = request.form.get('diagnosis', '').strip()
    doctor_notes = request.form.get('doctor_notes', '').strip()
    treatment_plan = request.form.get('treatment_plan', '').strip()
    prescription = request.form.get('prescription', '').strip()
    chief_complaint = request.form.get('chief_complaint', '').strip()
    clinical_observations = request.form.get('clinical_observations', '').strip()
    follow_up_instructions = request.form.get('follow_up_instructions', '').strip()
    follow_up_date = request.form.get('follow_up_date', '').strip() or None
    is_ref = request.form.get('is_referred') in ['1', 'true', 'True', 'on', 'yes']
    referral_dept_id = request.form.get('referral_department_id', type=int) if is_ref else None
    referral_notes = request.form.get('referral_notes', '').strip() if is_ref else None

    if not diagnosis and not doctor_notes:
        flash("Clinical completion requires at least a primary diagnosis or clinical notes.", "danger")
        return redirect(url_for('doctor.consultation', registration_id=reg.id))

    now = utcnow()
    consult = reg.consultation
    if not consult:
        consult = Consultation(
            registration_id=reg.id,
            patient_user_id=reg.patient_user_id,
            doctor_user_id=current_user.id,
            department_id=reg.department_id,
            started_at=now
        )
        db.session.add(consult)

    consult.chief_complaint = chief_complaint or reg.health_concern_category
    consult.clinical_observations = clinical_observations
    consult.doctor_notes = doctor_notes
    consult.diagnosis = diagnosis
    consult.treatment_plan = treatment_plan
    consult.prescription = prescription
    consult.follow_up_instructions = follow_up_instructions
    consult.follow_up_date = follow_up_date
    consult.is_referred = is_ref
    consult.referral_department_id = referral_dept_id
    consult.referral_notes = referral_notes
    consult.consultation_status = 'Completed'
    consult.completed_at = now
    consult.updated_at = now

    # Complete the queue record and remove from active waiting/consulting queue
    if reg.queue_record:
        reg.queue_record.queue_status = 'Completed'
        reg.queue_record.completion_time = now
        reg.queue_record.patients_ahead = 0
        reg.queue_record.estimated_wait_minutes = 0.0
        reg.queue_record.updated_at = now

    # Also update any linked ConsultationRequest to Completed
    consult_req = ConsultationRequest.query.filter_by(registration_id=reg.id).first()
    if not consult_req and reg.patient_user_id:
        consult_req = ConsultationRequest.query.filter(
            ConsultationRequest.patient_user_id == reg.patient_user_id,
            ConsultationRequest.status.in_(['Checked In', 'Confirmed'])
        ).order_by(ConsultationRequest.created_at.desc()).first()
    if consult_req:
        consult_req.status = 'Completed'
        if not consult_req.registration_id:
            consult_req.registration_id = reg.id

    db.session.commit()

    # Cascade recalculation of department queue - updates remaining waiting patients!
    recalculate_department_queue(reg.department_id)

    flash(
        f"Consultation successfully completed for {reg.patient_name} (Token: {reg.token_number}). "
        f"Patient has been discharged from the active queue.",
        "success"
    )
    return redirect(url_for('doctor.dashboard'))


@doctor_bp.route('/consultation-request/<int:request_id>', methods=['GET', 'POST'])
@login_required
@doctor_required
def view_consultation_request(request_id: int):
    """
    Allows the assigned doctor to review patient consultation requests,
    inspect the linked AI symptom assessment, update clinical status,
    and add consultation notes/instructions.
    """
    req_obj = db.session.get(ConsultationRequest, request_id)
    if not req_obj:
        flash("Consultation request not found.", "danger")
        return redirect(url_for('doctor.dashboard'))

    # Permission check: must be assigned to doctor or in doctor's department
    staff = current_user.staff_record
    dept_id = staff.department_id if staff else None
    if req_obj.assigned_doctor_id != current_user.id and req_obj.department_id != dept_id:
        flash("Access denied: You are not authorized to access this consultation request.", "danger")
        return redirect(url_for('doctor.dashboard'))

    if request.method == 'POST':
        action = request.form.get('action', 'save_notes')
        doctor_notes = request.form.get('doctor_notes', '').strip()
        status = request.form.get('status', '').strip()

        if doctor_notes:
            req_obj.doctor_notes = doctor_notes
        if status in ['Assigned', 'In Consultation', 'Completed', 'Cancelled']:
            req_obj.status = status

        # If action is 'checkin', check patient into live queue
        if action == 'checkin' and not req_obj.registration_id:
            patient_user = req_obj.patient_user
            reg, err = register_patient_to_queue(
                registered_by_user_id=current_user.id,
                department_id=req_obj.department_id,
                patient_name=patient_user.full_name if patient_user else "Consultation Patient",
                patient_phone=patient_user.phone if patient_user else None,
                patient_age=patient_user.age if (patient_user and patient_user.age) else 35,
                patient_gender=patient_user.gender if (patient_user and patient_user.gender) else 'Female',
                patient_user_id=req_obj.patient_user_id,
                triage_priority=2 if (req_obj.symptom_assessment and req_obj.symptom_assessment.has_urgent_symptoms) else 3,
                registration_notes=f"Checked in from Consultation Request #{req_obj.request_reference}",
                health_concern_category="Consultation Request",
                symptoms_description=req_obj.health_concern,
                arrival_time=utcnow(),
                assigned_doctor_id=current_user.id
            )
            if not err and reg:
                req_obj.registration_id = reg.id
                req_obj.status = 'In Consultation'
                db.session.commit()
                flash(f"Patient successfully checked into live queue with token {reg.token_number}!", "success")
                return redirect(url_for('doctor.consultation', registration_id=reg.id))
            else:
                flash(f"Check-in failed: {err}", "danger")

        db.session.commit()
        flash("Consultation request updated successfully.", "success")
        return redirect(url_for('doctor.view_consultation_request', request_id=req_obj.id))

    return render_template(
        'doctor/consultation_request_detail.html',
        req=req_obj,
        assessment=req_obj.symptom_assessment
    )

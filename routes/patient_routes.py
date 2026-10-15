"""
routes/patient_routes.py
------------------------
Routes for patient dashboard, profile management, health concern / symptom submission,
queue tracking with ML waiting-time predictions, and hospital contact requests.
Strictly isolates patient records to enforce privacy.
"""

import json
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from models.db_models import (
    db, PatientRegistration, QueueRecord, Department, User, Staff,
    ContactRequest, HospitalSetting, SymptomAssessment,
    ConsultationRequest, Consultation, utcnow
)
from services.auth_service import patient_required, update_patient_profile
from services.queue_service import (
    get_patient_queue_details,
    find_queue_by_token,
    register_patient_to_queue
)
from services.symptom_service import predict_condition, get_symptom_catalog

patient_bp = Blueprint('patient', __name__, url_prefix='/patient')

HEALTH_CONCERN_CATEGORIES = [
    "Fever",
    "Cough, Cold, or Respiratory Symptoms",
    "Headache or Migraine",
    "Stomach Pain or Digestive Problems",
    "Skin Problems / Rashes",
    "General Weakness or Fatigue",
    "Injury or Physical Pain",
    "Chronic-Condition-Related Concerns",
    "Other Health Concerns"
]

SYMPTOM_DURATIONS = [
    "Less than 24 hours",
    "1 to 3 days",
    "4 to 7 days",
    "More than a week"
]


@patient_bp.route('/dashboard')
@login_required
@patient_required
def dashboard():
    """
    Renders patient dashboard showing current active queue ticket,
    AI-estimated wait time, personal profile summary, consultation requests,
    symptom assessment history, and past consultation visit history.
    """
    registrations = get_patient_queue_details(current_user.id)

    active_reg = None
    past_registrations = []

    for reg in registrations:
        if reg.queue_record and reg.queue_record.queue_status in ['Waiting', 'Called', 'In Consultation']:
            if active_reg is None:
                active_reg = reg
            else:
                past_registrations.append(reg)
        else:
            past_registrations.append(reg)

    departments = Department.query.filter_by(is_active=True).all()
    hospital_info = HospitalSetting.query.first()

    # Patient's consultation requests
    consultation_requests = ConsultationRequest.query.filter_by(
        patient_user_id=current_user.id
    ).order_by(ConsultationRequest.created_at.desc()).all()

    # Patient's symptom assessments (latest 5)
    symptom_assessments = SymptomAssessment.query.filter_by(
        patient_user_id=current_user.id
    ).order_by(SymptomAssessment.created_at.desc()).limit(5).all()

    return render_template(
        'patient/dashboard.html',
        active_reg=active_reg,
        past_registrations=past_registrations,
        departments=departments,
        hospital_info=hospital_info,
        consultation_requests=consultation_requests,
        symptom_assessments=symptom_assessments
    )


@patient_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@patient_required
def profile():
    """Enables patient to view and update permitted personal demographic details."""
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        age = request.form.get('age')
        gender = request.form.get('gender')

        success, err = update_patient_profile(
            user_id=current_user.id,
            full_name=full_name,
            phone=phone,
            age=age,
            gender=gender
        )

        if success:
            flash("Your personal profile details have been successfully updated.", "success")
            return redirect(url_for('patient.profile'))
        else:
            flash(f"Profile update error: {err}", "danger")

    return render_template('patient/profile.html')


@patient_bp.route('/submit-concern', methods=['GET', 'POST'])
@login_required
@patient_required
def submit_concern():
    """
    Dedicated health-concern and symptom submission form.
    Creates a new hospital visit, assigns to chosen department,
    calculates initial ML waiting time, and adds to queue.
    Prevents duplicate active visits for the same patient.
    """
    # Check if patient already has an active visit
    active_visit = db.session.query(QueueRecord).join(PatientRegistration).filter(
        PatientRegistration.patient_user_id == current_user.id,
        QueueRecord.queue_status.in_(['Waiting', 'Called', 'In Consultation'])
    ).first()

    if active_visit:
        flash(
            f"You already have an active consultation ticket ({active_visit.registration.token_number}) in progress. "
            "Please complete or cancel your existing ticket before submitting a new visit.",
            "warning"
        )
        return redirect(url_for('patient.dashboard'))

    departments = Department.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        category = request.form.get('health_concern_category', '').strip()
        symptoms_desc = request.form.get('symptoms_description', '').strip()
        duration = request.form.get('symptom_duration', '').strip()
        department_id = request.form.get('department_id', type=int)
        has_appointment = bool(request.form.get('has_appointment'))
        appointment_notes = request.form.get('appointment_notes', '').strip()

        # Validation
        if not category:
            flash("Please select your primary health concern category.", "danger")
            return render_template(
                'patient/submit_concern.html',
                departments=departments,
                categories=HEALTH_CONCERN_CATEGORIES,
                durations=SYMPTOM_DURATIONS
            )

        if not symptoms_desc or len(symptoms_desc) < 5:
            flash("Please provide a brief description of your symptoms (at least 5 characters).", "danger")
            return render_template(
                'patient/submit_concern.html',
                departments=departments,
                categories=HEALTH_CONCERN_CATEGORIES,
                durations=SYMPTOM_DURATIONS,
                selected_category=category,
                symptoms_description=symptoms_desc,
                selected_duration=duration,
                selected_dept=department_id
            )

        if not department_id:
            flash("Please select the appropriate hospital department.", "danger")
            return render_template(
                'patient/submit_concern.html',
                departments=departments,
                categories=HEALTH_CONCERN_CATEGORIES,
                durations=SYMPTOM_DURATIONS,
                selected_category=category,
                symptoms_description=symptoms_desc,
                selected_duration=duration
            )

        # Register to queue with initial normal/routine priority (triage priority 3)
        # Staff can subsequently review symptoms and assign appropriate medical priority
        registration, err = register_patient_to_queue(
            registered_by_user_id=current_user.id,
            department_id=department_id,
            patient_name=current_user.full_name,
            patient_phone=current_user.phone,
            patient_age=current_user.age if current_user.age else 35,
            patient_gender=current_user.gender if current_user.gender else 'Female',
            patient_user_id=current_user.id,
            triage_priority=3,
            registration_notes=f"Patient-reported: {category}",
            health_concern_category=category,
            symptoms_description=symptoms_desc,
            symptom_duration=duration,
            has_appointment=has_appointment,
            appointment_notes=appointment_notes if has_appointment else None,
            arrival_time=utcnow()
        )

        if err:
            flash(f"Submission error: {err}", "danger")
            return render_template(
                'patient/submit_concern.html',
                departments=departments,
                categories=HEALTH_CONCERN_CATEGORIES,
                durations=SYMPTOM_DURATIONS
            )

        flash(
            f"Health concern submitted successfully! Assigned Token: {registration.token_number}. "
            f"Estimated waiting time: {registration.queue_record.estimated_wait_minutes} minutes.",
            "success"
        )
        return redirect(url_for('patient.dashboard'))

    return render_template(
        'patient/submit_concern.html',
        departments=departments,
        categories=HEALTH_CONCERN_CATEGORIES,
        durations=SYMPTOM_DURATIONS
    )


@patient_bp.route('/contact-requests', methods=['GET', 'POST'])
@login_required
@patient_required
def contact_requests():
    """
    Allows a logged-in patient to submit in-site hospital assistance requests
    (inquiries, appointment requests, callbacks) and view staff responses.
    Does NOT create a queue token.
    """
    hospital_info = HospitalSetting.query.first()

    if request.method == 'POST':
        request_type = request.form.get('request_type', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        pref_method = request.form.get('preferred_contact_method', 'Email')
        pref_time = request.form.get('preferred_callback_time', '').strip()

        if not request_type or not subject or not message:
            flash("Please complete the request type, subject, and message fields.", "danger")
        elif len(message) < 10:
            flash("Message description must be at least 10 characters long.", "danger")
        else:
            # Generate unique request reference
            ref_count = ContactRequest.query.count() + 1
            ref_str = f"REQ-{utcnow().year}-{ref_count:04d}"

            req_obj = ContactRequest(
                request_reference=ref_str,
                patient_user_id=current_user.id,
                patient_name=current_user.full_name,
                patient_email=current_user.email,
                patient_phone=current_user.phone,
                request_type=request_type,
                subject=subject,
                message=message,
                preferred_contact_method=pref_method,
                preferred_callback_time=pref_time if pref_time else None,
                status='Submitted',
                created_at=utcnow()
            )
            db.session.add(req_obj)
            db.session.commit()

            flash(f"Your hospital request has been submitted under reference {ref_str}. Our staff will review it shortly.", "success")
            return redirect(url_for('patient.contact_requests'))

    user_requests = ContactRequest.query.filter_by(patient_user_id=current_user.id)\
        .order_by(ContactRequest.created_at.desc()).all()

    return render_template(
        'patient/contact_requests.html',
        user_requests=user_requests,
        hospital_info=hospital_info
    )


@patient_bp.route('/link-token', methods=['POST'])
@login_required
@patient_required
def link_token():
    """
    Enables a patient to link an existing walk-in queue token to their account
    if the receptionist registered them without an account ID.
    """
    token_str = request.form.get('token_number', '').strip().upper()
    if not token_str:
        flash("Please enter a valid token number.", "warning")
        return redirect(url_for('patient.dashboard'))

    reg = find_queue_by_token(token_str)
    if not reg:
        flash(f"No queue registration found matching token '{token_str}'.", "danger")
        return redirect(url_for('patient.dashboard'))

    if reg.patient_user_id and reg.patient_user_id != current_user.id:
        flash("Security alert: This token is already linked to another patient profile.", "danger")
        return redirect(url_for('patient.dashboard'))

    reg.patient_user_id = current_user.id
    db.session.commit()
    flash(f"Token {token_str} has been successfully linked to your patient dashboard!", "success")
    return redirect(url_for('patient.dashboard'))


@patient_bp.route('/api/status')
@login_required
@patient_required
def api_status():
    """Provides asynchronous JSON polling for patient's active ticket."""
    registrations = get_patient_queue_details(current_user.id)
    active_reg = None
    for reg in registrations:
        if reg.queue_record and reg.queue_record.queue_status in ['Waiting', 'Called', 'In Consultation']:
            active_reg = reg
            break

    if not active_reg or not active_reg.queue_record:
        return jsonify({'has_active': False})

    q = active_reg.queue_record
    return jsonify({
        'has_active': True,
        'token_number': active_reg.token_number,
        'department': active_reg.department.department_name,
        'queue_status': q.queue_status,
        'priority_label': active_reg.priority_label,
        'patients_ahead': q.patients_ahead,
        'estimated_wait_minutes': q.estimated_wait_minutes,
        'arrival_time': active_reg.arrival_time.strftime('%I:%M %p'),
        'last_updated': q.updated_at.strftime('%I:%M:%S %p')
    })


@patient_bp.route('/symptom-checker', methods=['GET', 'POST'])
@login_required
@patient_required
def symptom_checker():
    """
    ML-powered Symptom Checker and Disease Assessment interface.
    Allows patients to select symptoms, duration, and severity,
    evaluates using trained Random Forest model, and provides preliminary
    differential assessments with medical safety disclaimers.
    """
    catalog = get_symptom_catalog()
    durations = SYMPTOM_DURATIONS
    severities = ["Mild", "Moderate", "Severe"]

    if request.method == 'POST':
        selected_symptoms = request.form.getlist('symptoms')
        duration = request.form.get('duration', '').strip()
        severity = request.form.get('severity', 'Moderate').strip()

        if not selected_symptoms:
            flash("Please select at least one symptom from the list below to assess.", "warning")
            return render_template(
                'patient/symptom_checker.html',
                catalog=catalog,
                durations=durations,
                severities=severities,
                selected_duration=duration,
                selected_severity=severity
            )

        # Model prediction
        assessment_result = predict_condition(selected_symptoms, duration, severity)
        if not assessment_result.get('success') and not assessment_result.get('is_inconclusive'):
            flash(assessment_result.get('error', 'Unable to complete symptom assessment.'), "danger")
            return render_template(
                'patient/symptom_checker.html',
                catalog=catalog,
                durations=durations,
                severities=severities
            )

        # Save to database
        ref_count = SymptomAssessment.query.count() + 1
        ref_str = f"SYM-{utcnow().year}-{ref_count:04d}"

        new_assessment = SymptomAssessment(
            assessment_reference=ref_str,
            patient_user_id=current_user.id,
            selected_symptoms=json.dumps(assessment_result.get('submitted_symptoms', [])),
            symptom_duration=duration,
            severity_level=severity,
            predicted_disease=assessment_result.get('primary_condition', 'Inconclusive Assessment'),
            confidence_score=assessment_result.get('confidence_score'),
            top_predictions=json.dumps(assessment_result.get('top_alternatives', [])),
            has_urgent_symptoms=assessment_result.get('has_urgent_symptoms', False),
            model_version=assessment_result.get('model_version', '1.0.0')
        )
        db.session.add(new_assessment)
        db.session.commit()

        return render_template(
            'patient/symptom_checker_result.html',
            assessment=new_assessment,
            result=assessment_result
        )

    return render_template(
        'patient/symptom_checker.html',
        catalog=catalog,
        durations=durations,
        severities=severities
    )


@patient_bp.route('/assessments')
@login_required
@patient_required
def assessments():
    """Renders patient's private symptom assessment history."""
    all_assessments = SymptomAssessment.query.filter_by(
        patient_user_id=current_user.id
    ).order_by(SymptomAssessment.created_at.desc()).all()
    return render_template('patient/assessments.html', assessments=all_assessments)


@patient_bp.route('/assessment/<int:id>')
@login_required
@patient_required
def view_assessment(id):
    """Views a past symptom assessment report with strict patient ownership check."""
    assessment = db.session.get(SymptomAssessment, id)
    if not assessment or assessment.patient_user_id != current_user.id:
        flash("Assessment record not found or access unauthorized.", "danger")
        return redirect(url_for('patient.dashboard'))
    return render_template('patient/symptom_checker_result.html', assessment=assessment, result=assessment.to_dict())


@patient_bp.route('/doctors')
@login_required
@patient_required
def doctors():
    """Renders directory of hospital physicians with their departments, qualifications, and experience."""
    dept_id = request.args.get('department_id', type=int)
    search_q = request.args.get('q', '').strip()

    query = db.session.query(User).join(Staff).filter(
        User.role == 'doctor',
        User.is_active == True
    )

    if dept_id:
        query = query.filter(Staff.department_id == dept_id)

    if search_q:
        query = query.filter(
            (User.full_name.ilike(f"%{search_q}%")) |
            (Staff.qualification.ilike(f"%{search_q}%"))
        )

    doctors_list = query.order_by(User.full_name.asc()).all()
    departments = Department.query.filter_by(is_active=True).all()

    return render_template(
        'patient/doctors.html',
        doctors=doctors_list,
        departments=departments,
        selected_dept_id=dept_id,
        search_q=search_q
    )


@patient_bp.route('/request-consultation', methods=['GET', 'POST'])
@login_required
@patient_required
def request_consultation():
    """
    Allows a patient to submit a formal doctor consultation request,
    optionally linked to a previous AI symptom assessment or chosen physician.
    """
    departments = Department.query.filter_by(is_active=True).all()
    assessment_id = request.args.get('assessment_id', type=int)
    preselected_doctor_id = request.args.get('doctor_id', type=int)
    preselected_dept_id = request.args.get('department_id', type=int)
    linked_assessment = None

    if assessment_id:
        linked_assessment = db.session.get(SymptomAssessment, assessment_id)
        if linked_assessment and linked_assessment.patient_user_id != current_user.id:
            linked_assessment = None

    preferred_doc = None
    if preselected_doctor_id:
        preferred_doc = db.session.get(User, preselected_doctor_id)
        if preferred_doc and (preferred_doc.role != 'doctor' or not preferred_doc.is_active):
            preferred_doc = None
        elif preferred_doc and preferred_doc.staff_record and not preselected_dept_id:
            preselected_dept_id = preferred_doc.staff_record.department_id

    # Active physicians for optional dropdown selection
    available_doctors = db.session.query(User).join(Staff).filter(
        User.role == 'doctor',
        User.is_active == True
    ).all()

    if request.method == 'POST':
        dept_id = request.form.get('department_id', type=int)
        concern = request.form.get('health_concern', '').strip()
        pref_date = request.form.get('preferred_date', '').strip()
        pref_slot = request.form.get('preferred_time_slot', 'Morning (8:00 AM - 12:00 PM)')
        preferred_doctor_id = request.form.get('preferred_doctor_id', type=int)
        notes = request.form.get('additional_notes', '').strip()
        form_assessment_id = request.form.get('assessment_id', type=int)

        if not dept_id or not concern:
            flash("Please select a hospital department and describe your health concern.", "danger")
            return render_template(
                'patient/request_consultation.html',
                departments=departments,
                available_doctors=available_doctors,
                linked_assessment=linked_assessment,
                preferred_doc=preferred_doc,
                preselected_dept_id=dept_id,
                concern=concern,
                pref_date=pref_date,
                notes=notes
            )

        ref_count = ConsultationRequest.query.count() + 1
        ref_str = f"CR-{utcnow().year}-{ref_count:04d}"

        consult_req = ConsultationRequest(
            request_reference=ref_str,
            patient_user_id=current_user.id,
            symptom_assessment_id=form_assessment_id if form_assessment_id else None,
            department_id=dept_id,
            preferred_doctor_id=preferred_doctor_id if preferred_doctor_id else None,
            health_concern=concern,
            preferred_date=pref_date,
            preferred_time_slot=pref_slot,
            additional_notes=notes,
            status='Pending Review'
        )
        db.session.add(consult_req)

        if form_assessment_id:
            ass_obj = db.session.get(SymptomAssessment, form_assessment_id)
            if ass_obj and ass_obj.patient_user_id == current_user.id:
                ass_obj.consultation_requested = True

        db.session.commit()
        flash(
            f"Consultation request {ref_str} submitted successfully! Hospital reception will review and confirm your schedule.",
            "success"
        )
        return redirect(url_for('patient.consultation_requests'))

    # Prefill health concern if linked from symptom assessment
    prefilled_concern = ""
    if linked_assessment:
        sym_data = linked_assessment.to_dict()
        sym_names = [
            s.get('name', str(s)) if isinstance(s, dict) else str(s)
            for s in sym_data.get('selected_symptoms', [])
        ]
        prefilled_concern = (
            f"Preliminary AI Assessment: {linked_assessment.predicted_disease}\n"
            f"Reported Symptoms: {', '.join(sym_names)}\n"
            f"Duration: {linked_assessment.symptom_duration or 'Not specified'} | Severity: {linked_assessment.severity_level or 'Moderate'}"
        )

    return render_template(
        'patient/request_consultation.html',
        departments=departments,
        available_doctors=available_doctors,
        linked_assessment=linked_assessment,
        preferred_doc=preferred_doc,
        preselected_dept_id=preselected_dept_id,
        prefilled_concern=prefilled_concern
    )


@patient_bp.route('/consultation-requests')
@login_required
@patient_required
def consultation_requests():
    """Renders patient's consultation requests and statuses."""
    requests_list = ConsultationRequest.query.filter_by(
        patient_user_id=current_user.id
    ).order_by(ConsultationRequest.created_at.desc()).all()
    return render_template('patient/consultation_requests.html', requests_list=requests_list)


@patient_bp.route('/accept-alternative/<int:id>', methods=['POST'])
@login_required
@patient_required
def accept_alternative(id):
    """Allows patient to accept receptionist's proposed alternative consultation schedule."""
    req = db.session.get(ConsultationRequest, id)
    if not req or req.patient_user_id != current_user.id:
        flash("Consultation request not found or access unauthorized.", "danger")
        return redirect(url_for('patient.consultation_requests'))

    if req.status != 'Alternative Proposed':
        flash("No active alternative proposal to accept for this request.", "warning")
        return redirect(url_for('patient.consultation_requests'))

    req.status = 'Confirmed'
    req.confirmed_date = req.proposed_alternative_date
    req.confirmed_time_slot = req.proposed_alternative_time_slot
    db.session.commit()

    flash(f"You accepted the proposed appointment schedule for {req.confirmed_date} at {req.confirmed_time_slot}!", "success")
    return redirect(url_for('patient.consultation_requests'))


@patient_bp.route('/decline-alternative/<int:id>', methods=['POST'])
@login_required
@patient_required
def decline_alternative(id):
    """Allows patient to decline the proposed alternative schedule."""
    req = db.session.get(ConsultationRequest, id)
    if not req or req.patient_user_id != current_user.id:
        flash("Consultation request not found or access unauthorized.", "danger")
        return redirect(url_for('patient.consultation_requests'))

    req.status = 'Cancelled'
    db.session.commit()

    flash("You declined the proposed schedule. The consultation request has been cancelled.", "info")
    return redirect(url_for('patient.consultation_requests'))


@patient_bp.route('/medical-records')
@login_required
@patient_required
def medical_records():
    """Renders list of patient's completed consultations and official clinical records."""
    records = Consultation.query.filter_by(
        patient_user_id=current_user.id,
        consultation_status='Completed'
    ).order_by(Consultation.completed_at.desc()).all()

    return render_template('patient/medical_records.html', records=records)


@patient_bp.route('/medical-records/<int:id>')
@login_required
@patient_required
def view_medical_record(id):
    """Renders a detailed, printable clinical consultation record."""
    consult = db.session.get(Consultation, id)
    if not consult or consult.patient_user_id != current_user.id:
        flash("Medical record not found or access unauthorized.", "danger")
        return redirect(url_for('patient.medical_records'))

    hospital_info = HospitalSetting.query.first()
    return render_template('patient/medical_record_detail.html', consult=consult, hospital_info=hospital_info)


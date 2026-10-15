"""
models/db_models.py
-------------------
SQLAlchemy ORM models representing HospitalFlow AI database entities.
Updated with patient profiles, visit health concerns, smart queue statuses,
audit trails, and hospital contact requests.
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def utcnow():
    """Returns timezone-naive UTC datetime for consistent multi-database compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(25), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum('receptionist', 'doctor', 'patient', name='user_roles'), nullable=False, default='patient', index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    registrations = db.relationship('PatientRegistration', foreign_keys='PatientRegistration.patient_user_id', backref='patient_user', lazy=True)
    registered_patients = db.relationship('PatientRegistration', foreign_keys='PatientRegistration.registered_by', backref='registrar', lazy=True)
    staff_record = db.relationship('Staff', backref='user', uselist=False, cascade='all, delete-orphan')
    assigned_patients = db.relationship('PatientRegistration', foreign_keys='PatientRegistration.assigned_doctor_id', backref='assigned_doctor', lazy=True)
    doctor_consultations = db.relationship('Consultation', foreign_keys='Consultation.doctor_user_id', backref='doctor_user', lazy=True)
    patient_consultations = db.relationship('Consultation', foreign_keys='Consultation.patient_user_id', backref='patient_user', lazy=True)
    symptom_assessments = db.relationship('SymptomAssessment', backref='patient_user', lazy=True, cascade='all, delete-orphan')
    patient_consultation_requests = db.relationship('ConsultationRequest', foreign_keys='ConsultationRequest.patient_user_id', backref='patient_user', lazy=True, cascade='all, delete-orphan')
    assigned_consultation_requests = db.relationship('ConsultationRequest', foreign_keys='ConsultationRequest.assigned_doctor_id', backref='assigned_doctor', lazy=True)
    preferred_consultation_requests = db.relationship('ConsultationRequest', foreign_keys='ConsultationRequest.preferred_doctor_id', backref='preferred_doctor', lazy=True)
    reviewed_doctor_registrations = db.relationship('DoctorRegistrationRequest', foreign_keys='DoctorRegistrationRequest.reviewed_by_user_id', backref='reviewer', lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        # Admin role is completely deprecated and removed; always returns False
        return False

    @property
    def is_receptionist(self) -> bool:
        return self.role == 'receptionist'

    @property
    def is_doctor(self) -> bool:
        return self.role == 'doctor'

    @property
    def is_patient(self) -> bool:
        return self.role == 'patient'

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'age': self.age,
            'gender': self.gender,
            'role': self.role,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    department_name = db.Column(db.String(80), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    # Relationships
    staff = db.relationship('Staff', backref='department', lazy=True)
    registrations = db.relationship('PatientRegistration', backref='department', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'department_name': self.department_name,
            'code': self.code,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class Staff(db.Model):
    __tablename__ = 'staff'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False)
    staff_type = db.Column(db.String(50), nullable=False)  # 'Receptionist', 'Doctor', 'Nurse', 'Admin'
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    qualification = db.Column(db.String(100), nullable=True)
    license_number = db.Column(db.String(100), nullable=True)
    experience_years = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'full_name': self.user.full_name if self.user else None,
            'email': self.user.email if self.user else None,
            'department_id': self.department_id,
            'department_name': self.department.department_name if self.department else None,
            'staff_type': self.staff_type,
            'is_available': self.is_available,
            'qualification': self.qualification,
            'license_number': self.license_number,
            'experience_years': self.experience_years,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }


class PatientRegistration(db.Model):
    __tablename__ = 'patient_registrations'

    id = db.Column(db.Integer, primary_key=True)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    patient_name = db.Column(db.String(120), nullable=False)
    patient_phone = db.Column(db.String(25), nullable=True)
    patient_age = db.Column(db.Integer, nullable=False, default=35)
    patient_gender = db.Column(db.String(10), nullable=False, default='Female')
    registered_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False, index=True)
    token_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    arrival_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    triage_priority = db.Column(db.Integer, nullable=False, default=3)  # 1=Emergency, 2=Urgent, 3=Routine, 4=Low
    registration_notes = db.Column(db.Text, nullable=True)

    # Enhanced patient-reported health concern details
    health_concern_category = db.Column(db.String(100), nullable=True)
    symptoms_description = db.Column(db.Text, nullable=True)
    symptom_duration = db.Column(db.String(50), nullable=True)
    has_appointment = db.Column(db.Boolean, default=False, nullable=False)
    appointment_notes = db.Column(db.String(255), nullable=True)

    # Clinical Priority Audit Trail
    priority_assigned_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    priority_assigned_at = db.Column(db.DateTime, nullable=True)

    # Doctor assignment
    assigned_doctor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    queue_record = db.relationship('QueueRecord', backref='registration', uselist=False, cascade='all, delete-orphan')
    priority_assigner = db.relationship('User', foreign_keys=[priority_assigned_by], lazy=True)
    consultation = db.relationship('Consultation', backref='registration', uselist=False, cascade='all, delete-orphan')

    @property
    def priority_label(self) -> str:
        labels = {
            1: "Priority 1 - Immediate Emergency",
            2: "Priority 2 - Urgent Attention",
            3: "Priority 3 - Routine Consultation",
            4: "Priority 4 - Low Priority"
        }
        return labels.get(self.triage_priority, f"Priority {self.triage_priority}")

    @property
    def priority_badge_class(self) -> str:
        return f"badge-priority-{self.triage_priority}"

    def to_dict(self):
        return {
            'id': self.id,
            'patient_user_id': self.patient_user_id,
            'patient_name': self.patient_name,
            'patient_phone': self.patient_phone,
            'patient_age': self.patient_age,
            'patient_gender': self.patient_gender,
            'token_number': self.token_number,
            'department_id': self.department_id,
            'department_name': self.department.department_name if self.department else 'Unknown',
            'department_code': self.department.code if self.department else 'N/A',
            'assigned_doctor_id': self.assigned_doctor_id,
            'assigned_doctor_name': self.assigned_doctor.full_name if self.assigned_doctor else None,
            'arrival_time': self.arrival_time.strftime('%Y-%m-%d %H:%M') if self.arrival_time else None,
            'triage_priority': self.triage_priority,
            'priority_label': self.priority_label,
            'health_concern_category': self.health_concern_category,
            'symptoms_description': self.symptoms_description,
            'symptom_duration': self.symptom_duration,
            'has_appointment': self.has_appointment,
            'appointment_notes': self.appointment_notes,
            'registration_notes': self.registration_notes,
            'queue_status': self.queue_record.queue_status if self.queue_record else None,
            'estimated_wait_minutes': self.queue_record.estimated_wait_minutes if self.queue_record else None,
            'patients_ahead': self.queue_record.patients_ahead if self.queue_record else 0,
            'priority_assigned_by': self.priority_assigner.full_name if self.priority_assigner else None,
            'priority_assigned_at': self.priority_assigned_at.strftime('%Y-%m-%d %H:%M') if self.priority_assigned_at else None,
            'consultation': self.consultation.to_dict() if self.consultation else None
        }


class QueueRecord(db.Model):
    __tablename__ = 'queue_records'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('patient_registrations.id', ondelete='CASCADE'), unique=True, nullable=False)
    # Queue statuses: 'Waiting', 'Called', 'In Consultation', 'Completed', 'Skipped', 'Cancelled'
    queue_status = db.Column(
        db.String(30),
        default='Waiting',
        nullable=False,
        index=True
    )
    patients_ahead = db.Column(db.Integer, nullable=False, default=0)
    estimated_wait_minutes = db.Column(db.Float, nullable=False, default=0.0)
    prediction_timestamp = db.Column(db.DateTime, default=utcnow, nullable=False)
    call_time = db.Column(db.DateTime, nullable=True)
    consultation_start_time = db.Column(db.DateTime, nullable=True)
    completion_time = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'registration_id': self.registration_id,
            'queue_status': self.queue_status,
            'patients_ahead': self.patients_ahead,
            'estimated_wait_minutes': self.estimated_wait_minutes,
            'prediction_timestamp': self.prediction_timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.prediction_timestamp else None,
            'call_time': self.call_time.strftime('%Y-%m-%d %H:%M:%S') if self.call_time else None,
            'consultation_start_time': self.consultation_start_time.strftime('%Y-%m-%d %H:%M:%S') if self.consultation_start_time else None,
            'completion_time': self.completion_time.strftime('%Y-%m-%d %H:%M:%S') if self.completion_time else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }


class Consultation(db.Model):
    __tablename__ = 'consultations'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('patient_registrations.id', ondelete='CASCADE'), unique=True, nullable=False, index=True)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    doctor_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False)

    # Clinical Consultation Fields
    chief_complaint = db.Column(db.Text, nullable=True)
    clinical_observations = db.Column(db.Text, nullable=True)
    doctor_notes = db.Column(db.Text, nullable=True)
    diagnosis = db.Column(db.Text, nullable=True)
    treatment_plan = db.Column(db.Text, nullable=True)
    prescription = db.Column(db.Text, nullable=True)
    follow_up_instructions = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.String(50), nullable=True)
    referral_department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    referral_notes = db.Column(db.Text, nullable=True)
    is_referred = db.Column(db.Boolean, default=False, nullable=False)

    # Status: 'In Progress', 'Draft', 'Completed'
    consultation_status = db.Column(db.String(30), default='In Progress', nullable=False, index=True)

    started_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Direct relationships
    department = db.relationship('Department', foreign_keys=[department_id], lazy=True)
    referral_department = db.relationship('Department', foreign_keys=[referral_department_id], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'registration_id': self.registration_id,
            'patient_user_id': self.patient_user_id,
            'doctor_user_id': self.doctor_user_id,
            'doctor_name': self.doctor_user.full_name if self.doctor_user else None,
            'department_id': self.department_id,
            'department_name': self.department.department_name if self.department else None,
            'chief_complaint': self.chief_complaint,
            'clinical_observations': self.clinical_observations,
            'doctor_notes': self.doctor_notes,
            'diagnosis': self.diagnosis,
            'treatment_plan': self.treatment_plan,
            'prescription': self.prescription,
            'follow_up_instructions': self.follow_up_instructions,
            'follow_up_date': self.follow_up_date,
            'referral_department_id': self.referral_department_id,
            'referral_department_name': self.referral_department.department_name if self.referral_department else None,
            'referral_notes': self.referral_notes,
            'is_referred': self.is_referred,
            'consultation_status': self.consultation_status,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else None,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }


class ContactRequest(db.Model):
    __tablename__ = 'contact_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_reference = db.Column(db.String(30), unique=True, nullable=False, index=True)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    patient_name = db.Column(db.String(120), nullable=False)
    patient_email = db.Column(db.String(120), nullable=False)
    patient_phone = db.Column(db.String(25), nullable=True)
    request_type = db.Column(db.String(50), nullable=False)  # 'General Inquiry', 'Appointment Request', 'Callback Request', 'Visit Assistance'
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    preferred_contact_method = db.Column(db.String(20), default='Email', nullable=False)  # 'Email', 'Phone'
    preferred_callback_time = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(30), default='Submitted', nullable=False, index=True)  # 'Submitted', 'Under Review', 'Responded To', 'Closed'
    staff_response = db.Column(db.Text, nullable=True)
    responded_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    responded_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Relationships
    patient = db.relationship('User', foreign_keys=[patient_user_id], backref=db.backref('contact_requests', lazy=True))
    responder = db.relationship('User', foreign_keys=[responded_by_user_id], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'request_reference': self.request_reference,
            'patient_user_id': self.patient_user_id,
            'patient_name': self.patient_name,
            'patient_email': self.patient_email,
            'patient_phone': self.patient_phone,
            'request_type': self.request_type,
            'subject': self.subject,
            'message': self.message,
            'preferred_contact_method': self.preferred_contact_method,
            'preferred_callback_time': self.preferred_callback_time,
            'status': self.status,
            'staff_response': self.staff_response,
            'responded_by': self.responder.full_name if self.responder else None,
            'responded_at': self.responded_at.strftime('%Y-%m-%d %H:%M') if self.responded_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }


class HospitalSetting(db.Model):
    __tablename__ = 'hospital_settings'

    id = db.Column(db.Integer, primary_key=True)
    hospital_name = db.Column(db.String(150), nullable=False, default='HospitalFlow General Hospital & Medical Center')
    phone = db.Column(db.String(30), nullable=False, default='+1 (555) 019-2830')
    emergency_phone = db.Column(db.String(30), nullable=False, default='+1 (555) 911-3569')
    email = db.Column(db.String(120), nullable=False, default='care@hospitalflow.ai')
    address = db.Column(db.String(255), nullable=False, default='1200 Health Science Boulevard, Suite 400, Metro City, MC 98101')
    opening_hours = db.Column(db.String(255), nullable=False, default='24/7 Emergency Care | OPD: Mon - Sat 8:00 AM - 8:00 PM')
    directions_url = db.Column(db.String(255), nullable=True, default='https://maps.google.com')
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    def to_dict(self):
        return {
            'hospital_name': self.hospital_name,
            'phone': self.phone,
            'emergency_phone': self.emergency_phone,
            'email': self.email,
            'address': self.address,
            'opening_hours': self.opening_hours,
            'directions_url': self.directions_url
        }


class ModelRun(db.Model):
    __tablename__ = 'model_runs'

    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(80), nullable=False)
    dataset_reference = db.Column(db.String(255), nullable=False)
    mae = db.Column(db.Float, nullable=False)
    rmse = db.Column(db.Float, nullable=False)
    r2_score = db.Column(db.Float, nullable=False)
    model_version = db.Column(db.String(20), nullable=False, default='1.0.0')
    training_status = db.Column(db.String(30), nullable=False, default='COMPLETED')
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'model_name': self.model_name,
            'dataset_reference': self.dataset_reference,
            'mae': self.mae,
            'rmse': self.rmse,
            'r2_score': self.r2_score,
            'model_version': self.model_version,
            'training_status': self.training_status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class SymptomAssessment(db.Model):
    __tablename__ = 'symptom_assessments'

    id = db.Column(db.Integer, primary_key=True)
    assessment_reference = db.Column(db.String(30), unique=True, nullable=False, index=True)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    selected_symptoms = db.Column(db.Text, nullable=False)
    symptom_duration = db.Column(db.String(50), nullable=True)
    severity_level = db.Column(db.String(30), nullable=True)
    predicted_disease = db.Column(db.String(150), nullable=False)
    confidence_score = db.Column(db.Float, nullable=True)
    top_predictions = db.Column(db.Text, nullable=True)
    has_urgent_symptoms = db.Column(db.Boolean, default=False, nullable=False)
    model_version = db.Column(db.String(20), default='1.0.0', nullable=False)
    consultation_requested = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    # Relationships
    consultation_requests = db.relationship('ConsultationRequest', backref='symptom_assessment', lazy=True)

    def to_dict(self):
        import json
        try:
            symptoms_list = json.loads(self.selected_symptoms) if self.selected_symptoms else []
        except Exception:
            symptoms_list = self.selected_symptoms.split(',') if self.selected_symptoms else []

        try:
            alternatives = json.loads(self.top_predictions) if self.top_predictions else []
        except Exception:
            alternatives = []

        return {
            'id': self.id,
            'assessment_reference': self.assessment_reference,
            'patient_user_id': self.patient_user_id,
            'patient_name': self.patient_user.full_name if self.patient_user else 'Unknown',
            'selected_symptoms': symptoms_list,
            'symptom_duration': self.symptom_duration,
            'severity_level': self.severity_level,
            'predicted_disease': self.predicted_disease,
            'confidence_score': self.confidence_score,
            'top_predictions': alternatives,
            'has_urgent_symptoms': self.has_urgent_symptoms,
            'model_version': self.model_version,
            'consultation_requested': self.consultation_requested,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None
        }


class ConsultationRequest(db.Model):
    __tablename__ = 'consultation_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_reference = db.Column(db.String(30), unique=True, nullable=False, index=True)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    symptom_assessment_id = db.Column(db.Integer, db.ForeignKey('symptom_assessments.id', ondelete='SET NULL'), nullable=True, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False, index=True)
    preferred_doctor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    assigned_doctor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)

    # Clinical details
    health_concern = db.Column(db.Text, nullable=False)
    preferred_date = db.Column(db.String(50), nullable=True)
    preferred_time_slot = db.Column(db.String(50), nullable=True)
    additional_notes = db.Column(db.Text, nullable=True)

    # Status: 'Pending Review', 'Confirmed', 'Alternative Proposed', 'Rejected', 'Cancelled', 'Checked In', 'Completed'
    status = db.Column(db.String(30), default='Pending Review', nullable=False, index=True)

    # Staff and Doctor processing notes
    receptionist_notes = db.Column(db.Text, nullable=True)
    doctor_notes = db.Column(db.Text, nullable=True)

    # Alternative proposal fields (when requested slot is unavailable)
    proposed_alternative_date = db.Column(db.String(50), nullable=True)
    proposed_alternative_time_slot = db.Column(db.String(50), nullable=True)
    alternative_notes = db.Column(db.Text, nullable=True)

    # Confirmed schedule
    confirmed_date = db.Column(db.String(50), nullable=True)
    confirmed_time_slot = db.Column(db.String(50), nullable=True)

    # Optional linkage to active queue ticket if checked in
    registration_id = db.Column(db.Integer, db.ForeignKey('patient_registrations.id', ondelete='SET NULL'), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    # Direct relationships
    department = db.relationship('Department', foreign_keys=[department_id], lazy=True)
    registration = db.relationship('PatientRegistration', foreign_keys=[registration_id], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'request_reference': self.request_reference,
            'patient_user_id': self.patient_user_id,
            'patient_name': self.patient_user.full_name if self.patient_user else 'Unknown',
            'patient_email': self.patient_user.email if self.patient_user else '',
            'patient_phone': self.patient_user.phone if self.patient_user else '',
            'symptom_assessment_id': self.symptom_assessment_id,
            'department_id': self.department_id,
            'department_name': self.department.department_name if self.department else 'Unknown',
            'preferred_doctor_id': self.preferred_doctor_id,
            'preferred_doctor_name': self.preferred_doctor.full_name if self.preferred_doctor else None,
            'assigned_doctor_id': self.assigned_doctor_id,
            'assigned_doctor_name': self.assigned_doctor.full_name if self.assigned_doctor else None,
            'health_concern': self.health_concern,
            'preferred_date': self.preferred_date,
            'preferred_time_slot': self.preferred_time_slot,
            'additional_notes': self.additional_notes,
            'status': self.status,
            'receptionist_notes': self.receptionist_notes,
            'doctor_notes': self.doctor_notes,
            'proposed_alternative_date': self.proposed_alternative_date,
            'proposed_alternative_time_slot': self.proposed_alternative_time_slot,
            'alternative_notes': self.alternative_notes,
            'confirmed_date': self.confirmed_date,
            'confirmed_time_slot': self.confirmed_time_slot,
            'registration_id': self.registration_id,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }


class DoctorRegistrationRequest(db.Model):
    __tablename__ = 'doctor_registration_requests'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(25), nullable=True)
    qualification = db.Column(db.String(100), nullable=False)
    specialization = db.Column(db.String(100), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False, index=True)
    license_number = db.Column(db.String(100), nullable=False)
    experience_years = db.Column(db.Integer, default=0, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(30), default='Pending', nullable=False, index=True)  # 'Pending', 'Approved', 'Rejected'
    rejection_reason = db.Column(db.Text, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    department = db.relationship('Department', foreign_keys=[department_id], lazy=True)
    user = db.relationship('User', foreign_keys=[user_id], lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'qualification': self.qualification,
            'specialization': self.specialization,
            'department_id': self.department_id,
            'department_name': self.department.department_name if self.department else None,
            'license_number': self.license_number,
            'experience_years': self.experience_years,
            'status': self.status,
            'rejection_reason': self.rejection_reason,
            'reviewed_by_name': self.reviewer.full_name if self.reviewer else None,
            'reviewed_at': self.reviewed_at.strftime('%Y-%m-%d %H:%M') if self.reviewed_at else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else None
        }


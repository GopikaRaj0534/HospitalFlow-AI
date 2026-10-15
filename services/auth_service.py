"""
services/auth_service.py
------------------------
Authentication and authorization services:
- Secure login, password hashing, and session fixation defense
- Public patient registration with demographic validation (age, gender, phone)
- Patient profile update management
- Strict role-based access control decorators (Admin, Receptionist, Patient)
"""

from functools import wraps
from flask import session, redirect, url_for, flash, abort, request
from flask_login import current_user, login_user, logout_user
from models.db_models import db, User, utcnow, DoctorRegistrationRequest, Department, Staff


def role_required(allowed_roles):
    """Decorator to enforce strict server-side role-based access control."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('auth.login', next=request.url))
            
            if current_user.role not in allowed_roles:
                flash("Access denied: You do not have permission to view that resource.", "danger")
                if current_user.role == 'receptionist':
                    return redirect(url_for('receptionist.dashboard'))
                elif current_user.role == 'doctor':
                    return redirect(url_for('doctor.dashboard'))
                else:
                    return redirect(url_for('patient.dashboard'))
            
            if not current_user.is_active:
                logout_user()
                session.clear()
                flash("Your account has been deactivated. Please contact hospital staff.", "danger")
                return redirect(url_for('auth.login'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def receptionist_required(f):
    """Enforces Receptionist management authorization (the main operational & administrative role)."""
    return role_required(['receptionist'])(f)


def admin_required(f):
    """Admin role has been removed; redirects/aliases to Receptionist management."""
    return role_required(['receptionist'])(f)


def doctor_required(f):
    """Enforces Doctor clinical authorization."""
    return role_required(['doctor'])(f)


def staff_required(f):
    """Allows hospital management staff (Receptionist)."""
    return role_required(['receptionist'])(f)


def clinical_required(f):
    """Allows clinical operations staff (Doctor or Receptionist)."""
    return role_required(['receptionist', 'doctor'])(f)


def patient_required(f):
    """Enforces Patient portal authorization."""
    return role_required(['patient'])(f)


def authenticate_user(email: str, password: str):
    """
    Validates user credentials against hashed password in database.
    If the account was a self-registered doctor pending review or rejected,
    returns a clear, informative status message.
    Refreshes session upon successful login to prevent session fixation.
    """
    if not email or not password:
        return None, "Email and password are required."

    email_clean = email.strip().lower()
    user = User.query.filter_by(email=email_clean).first()

    if not user:
        # Check if there is an unapproved/rejected doctor registration request
        doc_req = DoctorRegistrationRequest.query.filter_by(email=email_clean).order_by(DoctorRegistrationRequest.id.desc()).first()
        if doc_req:
            if doc_req.status == 'Pending':
                return None, "Your doctor registration is pending receptionist verification and approval. Please check back later."
            elif doc_req.status == 'Rejected':
                reason = f" (Reason: {doc_req.rejection_reason})" if doc_req.rejection_reason else ""
                return None, f"Your doctor registration application was declined by hospital administration.{reason}"
        return None, "Invalid email or password."

    if not user.check_password(password):
        return None, "Invalid email or password."

    if not user.is_active:
        # Check if doctor request was rejected or account deactivated
        doc_req = DoctorRegistrationRequest.query.filter_by(user_id=user.id).order_by(DoctorRegistrationRequest.id.desc()).first()
        if doc_req and doc_req.status == 'Rejected':
            reason = f" (Reason: {doc_req.rejection_reason})" if doc_req.rejection_reason else ""
            return None, f"Your doctor account was declined or deactivated.{reason}"
        return None, "Your account has been deactivated. Please contact hospital administration."

    # Regenerate session to protect against session fixation
    session.clear()
    session.permanent = True
    login_user(user, remember=False)

    return user, None


def register_patient_account(
    full_name: str,
    email: str,
    phone: str,
    password: str,
    confirm_password: str,
    age: int = None,
    gender: str = 'Female'
):
    """
    Validates and registers a new patient account with demographic details.
    Restricted strictly to the 'patient' role for public registration.
    """
    # Required field validations
    if not full_name or not email or not password:
        return None, "All required fields must be filled."

    name_clean = full_name.strip()
    email_clean = email.strip().lower()
    phone_clean = phone.strip() if phone else None

    if len(name_clean) < 2:
        return None, "Full name must be at least 2 characters."

    if '@' not in email_clean or '.' not in email_clean:
        return None, "Please provide a valid email address."

    if len(password) < 6:
        return None, "Password must be at least 6 characters long."

    if password != confirm_password:
        return None, "Passwords do not match."

    # Age validation
    age_val = None
    if age is not None and str(age).strip() != '':
        try:
            age_val = int(age)
            if age_val < 0 or age_val > 115:
                return None, "Age must be between 0 and 115."
        except (ValueError, TypeError):
            return None, "Age must be a valid number."

    # Gender validation
    gender_clean = (gender or 'Female').strip().capitalize()
    if gender_clean not in ['Female', 'Male', 'Other']:
        gender_clean = 'Female'

    # Check for existing email to prevent duplicate accounts
    existing_user = User.query.filter_by(email=email_clean).first()
    if existing_user:
        return None, "An account with this email address is already registered."

    try:
        new_user = User(
            full_name=name_clean,
            email=email_clean,
            phone=phone_clean,
            age=age_val,
            gender=gender_clean,
            role='patient',
            is_active=True
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return new_user, None
    except Exception as e:
        db.session.rollback()
        return None, f"Registration failed due to a database error: {str(e)}"


def update_patient_profile(
    user_id: int,
    full_name: str,
    phone: str = None,
    age: int = None,
    gender: str = None
):
    """Updates permitted demographic profile information for an existing patient."""
    user = db.session.get(User, user_id)
    if not user:
        return False, "User account not found."

    name_clean = (full_name or '').strip()
    if len(name_clean) < 2:
        return False, "Full name must be at least 2 characters."

    user.full_name = name_clean
    user.phone = phone.strip() if phone else None

    if age is not None and str(age).strip() != '':
        try:
            age_int = int(age)
            if 0 <= age_int <= 115:
                user.age = age_int
        except (ValueError, TypeError):
            pass

    if gender:
        g_clean = gender.strip().capitalize()
        if g_clean in ['Female', 'Male', 'Other']:
            user.gender = g_clean

    user.updated_at = utcnow()

    try:
        db.session.commit()
        return True, None
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to update profile: {str(e)}"


def register_doctor_request(
    full_name: str,
    email: str,
    phone: str,
    department_id: int,
    qualification: str,
    license_number: str,
    experience_years: int,
    password: str,
    confirm_password: str,
    specialization: str = None
):
    """
    Validates and registers a new doctor registration request in 'Pending' status.
    Requires receptionist review and approval before an active User/Staff account is created.
    Subspecialization is optional; specialization defaults to the selected department name.
    """
    if not full_name or not email or not department_id or not qualification or not license_number or not password:
        return None, "All required physician credentials and contact fields must be provided."

    name_clean = full_name.strip()
    email_clean = email.strip().lower()
    phone_clean = phone.strip() if phone else None
    qual_clean = qualification.strip()
    lic_clean = license_number.strip()

    if len(name_clean) < 2:
        return None, "Full name must be at least 2 characters."

    if '@' not in email_clean or '.' not in email_clean:
        return None, "Please provide a valid professional email address."

    if len(password) < 6:
        return None, "Password must be at least 6 characters long."

    if password != confirm_password:
        return None, "Passwords do not match."

    try:
        exp_int = int(experience_years) if experience_years is not None else 0
        if exp_int < 0 or exp_int > 60:
            return None, "Years of experience must be between 0 and 60."
    except (ValueError, TypeError):
        return None, "Experience must be a valid number."

    dept = db.session.get(Department, int(department_id))
    if not dept:
        return None, "Selected department does not exist."

    spec_clean = (specialization or '').strip() or dept.department_name

    # Check for existing user account
    existing_user = User.query.filter_by(email=email_clean).first()
    if existing_user:
        return None, "An active account with this email address already exists. Please sign in."

    # Check for existing doctor registration request
    existing_req = DoctorRegistrationRequest.query.filter_by(email=email_clean).first()
    if existing_req:
        if existing_req.status == 'Pending':
            return None, "A doctor registration with this email is already awaiting receptionist verification."
        elif existing_req.status == 'Approved':
            return None, "This doctor registration has already been approved. Please log in."
        elif existing_req.status == 'Rejected':
            # Allow re-applying by updating previous rejected record to Pending with updated details
            existing_req.full_name = name_clean
            existing_req.phone = phone_clean
            existing_req.department_id = dept.id
            existing_req.specialization = spec_clean
            existing_req.qualification = qual_clean
            existing_req.license_number = lic_clean
            existing_req.experience_years = exp_int
            existing_req.set_password(password)
            existing_req.status = 'Pending'
            existing_req.rejection_reason = None
            existing_req.reviewed_by_user_id = None
            existing_req.reviewed_at = None
            existing_req.updated_at = utcnow()
            db.session.commit()
            return existing_req, None

    try:
        new_req = DoctorRegistrationRequest(
            full_name=name_clean,
            email=email_clean,
            phone=phone_clean,
            department_id=dept.id,
            specialization=spec_clean,
            qualification=qual_clean,
            license_number=lic_clean,
            experience_years=exp_int,
            status='Pending'
        )
        new_req.set_password(password)
        db.session.add(new_req)
        db.session.commit()
        return new_req, None
    except Exception as e:
        db.session.rollback()
        return None, f"Registration failed due to a database error: {str(e)}"


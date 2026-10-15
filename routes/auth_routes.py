"""
routes/auth_routes.py
---------------------
Routes for user authentication, session management, and public patient registration.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import current_user, login_user, logout_user
from models.db_models import Department
from services.auth_service import authenticate_user, register_patient_account, register_doctor_request

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    """
    Public entry point for HospitalFlow AI.
    Renders professional public landing page for visitors.
    If authenticated, redirects to the user's role-specific dashboard.
    """
    if current_user.is_authenticated:
        if current_user.role == 'receptionist':
            return redirect(url_for('receptionist.dashboard'))
        elif current_user.role == 'doctor':
            return redirect(url_for('doctor.dashboard'))
        else:
            return redirect(url_for('patient.dashboard'))
    return render_template('landing.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    next_url = request.args.get('next')

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        user, error = authenticate_user(email, password)
        if error:
            flash(error, 'danger')
            return render_template('auth/login.html', email=email, next=next_url)

        flash(f"Welcome back, {user.full_name}!", 'success')
        
        # Safe redirection to requested URL if internal
        if next_url and next_url.startswith('/'):
            return redirect(next_url)

        # Role-based dashboard redirection (Receptionist, Doctor, Patient)
        if user.role == 'receptionist':
            return redirect(url_for('receptionist.dashboard'))
        elif user.role == 'doctor':
            return redirect(url_for('doctor.dashboard'))
        else:
            return redirect(url_for('patient.dashboard'))

    return render_template('auth/login.html', next=next_url)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Public registration endpoint strictly restricted to the 'patient' role.
    Receptionist and Doctor accounts cannot be created publicly here.
    Captures essential demographic details (name, email, phone, age, gender).
    """
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        age = request.form.get('age')
        gender = request.form.get('gender', 'Female')
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        user, error = register_patient_account(
            full_name=full_name,
            email=email,
            phone=phone,
            password=password,
            confirm_password=confirm_password,
            age=age,
            gender=gender
        )
        if error:
            flash(error, 'danger')
            return render_template(
                'auth/register.html',
                full_name=full_name,
                email=email,
                phone=phone,
                age=age,
                gender=gender
            )

        # Log in newly registered patient and transition them directly to health concern submission
        login_user(user, remember=False)
        flash("Registration successful! Please submit your health concern below to join the department queue.", 'success')
        return redirect(url_for('patient.submit_concern'))

    return render_template('auth/register.html')


@auth_bp.route('/register/doctor', methods=['GET', 'POST'])
def register_doctor():
    """
    Dedicated doctor self-registration endpoint.
    Collects physician qualifications, medical license number, and desired department.
    Puts the registration in 'Pending' status awaiting Receptionist review and approval.
    """
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    departments = Department.query.filter_by(is_active=True).order_by(Department.department_name.asc()).all()

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        department_id = request.form.get('department_id')
        specialization = request.form.get('specialization', '').strip() or None
        qualification = request.form.get('qualification', '').strip()
        license_number = request.form.get('license_number', '').strip()
        experience_years = request.form.get('experience_years')
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        req, error = register_doctor_request(
            full_name=full_name,
            email=email,
            phone=phone,
            department_id=department_id,
            qualification=qualification,
            license_number=license_number,
            experience_years=experience_years,
            password=password,
            confirm_password=confirm_password,
            specialization=specialization
        )

        if error:
            flash(error, 'danger')
            return render_template(
                'auth/register_doctor.html',
                departments=departments,
                full_name=full_name,
                email=email,
                phone=phone,
                department_id=department_id,
                qualification=qualification,
                license_number=license_number,
                experience_years=experience_years
            )

        flash("Doctor registration submitted successfully! Your application is pending receptionist verification and approval before login access is activated.", 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_doctor.html', departments=departments)


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    logout_user()
    session.clear()
    flash("You have been securely logged out.", "info")
    return redirect(url_for('auth.index'))


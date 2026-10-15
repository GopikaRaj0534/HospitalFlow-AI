"""
routes/admin_routes.py
----------------------
Legacy Admin routes deprecation router.
The Admin role has been completely removed from HospitalFlow AI in accordance with
the 3-role architectural mandate (Receptionist, Doctor, Patient).
All management capabilities have been transferred to the Receptionist portal.
These legacy routes redirect permanently to their respective Receptionist endpoints.
"""

from flask import Blueprint, redirect, url_for

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/')
@admin_bp.route('/dashboard')
def dashboard():
    return redirect(url_for('receptionist.dashboard'), code=307)


@admin_bp.route('/doctors', methods=['GET', 'POST'])
def doctors():
    return redirect(url_for('receptionist.doctors'), code=307)


@admin_bp.route('/users', methods=['GET', 'POST'])
def users():
    return redirect(url_for('receptionist.users'), code=307)


@admin_bp.route('/departments', methods=['GET', 'POST'])
def departments():
    return redirect(url_for('receptionist.departments'), code=307)


@admin_bp.route('/contact-requests', methods=['GET', 'POST'])
def contact_requests():
    return redirect(url_for('receptionist.contact_requests'), code=307)


@admin_bp.route('/hospital-settings', methods=['GET', 'POST'])
def hospital_settings():
    return redirect(url_for('receptionist.hospital_settings'), code=307)


@admin_bp.route('/model-management', methods=['GET', 'POST'])
def model_management():
    return redirect(url_for('receptionist.model_management'), code=307)

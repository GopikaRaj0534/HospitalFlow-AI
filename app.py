"""
app.py
------
HospitalFlow AI - AI-Based Hospital Waiting-Time Prediction and Patient Flow Optimization System.
Main Flask application entry point using the Application Factory pattern.
"""

import os
from flask import Flask, render_template
from flask_login import LoginManager
from config import config_by_name
from models.db_models import db, User, HospitalSetting
from routes.auth_routes import auth_bp
from routes.patient_routes import patient_bp
from routes.receptionist_routes import receptionist_bp
from routes.admin_routes import admin_bp
from routes.doctor_routes import doctor_bp


def create_app(config_name=None):
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))

    # Initialize SQLAlchemy
    db.init_app(app)

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.login_message = "Please sign in to access this portal."
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(receptionist_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(doctor_bp)

    # Public Hospital Contact Page
    @app.route('/contact')
    def contact():
        setting = HospitalSetting.query.first()
        if not setting:
            setting = HospitalSetting()
        return render_template('contact.html', hospital_info=setting)

    # Global Error Handlers
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('base.html', error_title="403 - Forbidden Access",
                               error_msg="You do not have administrative authorization to access this clinical resource."), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('base.html', error_title="404 - Page Not Found",
                               error_msg="The requested hospital page or queue record was not found."), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('base.html', error_title="500 - Internal Server Error",
                               error_msg="A system exception occurred. Hospital administrators have been logged."), 500

    # Context processors
    @app.context_processor
    def inject_global_vars():
        setting = None
        try:
            setting = HospitalSetting.query.first()
        except Exception:
            pass
        return {
            'app_name': 'HospitalFlow AI',
            'current_year': 2026,
            'hospital_info': setting
        }

    return app


app = create_app()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Run HospitalFlow AI server")
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', 5000)), help="Port to listen on")
    args, _ = parser.parse_known_args()
    print(f"Starting HospitalFlow AI on http://127.0.0.1:{args.port} ...")
    app.run(host='127.0.0.1', port=args.port, debug=True)

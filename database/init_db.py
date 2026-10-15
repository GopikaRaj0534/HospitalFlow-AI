"""
database/init_db.py
-------------------
Initializes the MySQL database (XAMPP), executes schema & seed scripts,
applies safe schema migrations (preserving existing patient records and database data),
and sets up default accounts and hospital settings securely.
"""

import os
import sys
import json
import pymysql
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'hospitalflow_ai')

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')
SEED_PATH = os.path.join(os.path.dirname(__file__), 'seed_departments.sql')
MODEL_REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'evaluation_report.json')


def apply_safe_migrations(cursor):
    """
    Safely inspects existing tables and applies backward-compatible column
    and table additions without dropping or corrupting existing data.
    """
    print("Applying safe database migrations...")

    # Helper to check if a column exists
    def column_exists(table, col):
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """,
            (DB_NAME, table, col)
        )
        return cursor.fetchone()[0] > 0

    # 1. Check users table
    if not column_exists('users', 'age'):
        cursor.execute("ALTER TABLE users ADD COLUMN age INT NULL AFTER phone")
        print("  + Added column 'age' to users table.")
    if not column_exists('users', 'gender'):
        cursor.execute("ALTER TABLE users ADD COLUMN gender VARCHAR(10) NULL AFTER age")
        print("  + Added column 'gender' to users table.")

    # Safely consolidate duplicate receptionist account into single Sarah Jenkins account
    try:
        cursor.execute("SELECT id FROM users WHERE email = 'receptionist@hospitalflow.ai'")
        sarah_row = cursor.fetchone()
        cursor.execute("SELECT id FROM users WHERE email = 'admin@hospitalflow.ai'")
        admin_row = cursor.fetchone()
        if admin_row and sarah_row:
            sarah_id = sarah_row[0]
            admin_id = admin_row[0]
            cursor.execute("UPDATE patient_registrations SET registered_by = %s WHERE registered_by = %s", (sarah_id, admin_id))
            cursor.execute("UPDATE patient_registrations SET priority_assigned_by = %s WHERE priority_assigned_by = %s", (sarah_id, admin_id))
            cursor.execute("UPDATE contact_requests SET responded_by_user_id = %s WHERE responded_by_user_id = %s", (sarah_id, admin_id))
            cursor.execute("UPDATE doctor_registration_requests SET reviewed_by_user_id = %s WHERE reviewed_by_user_id = %s", (sarah_id, admin_id))
            cursor.execute("DELETE FROM staff WHERE user_id = %s", (admin_id,))
            cursor.execute("DELETE FROM users WHERE id = %s", (admin_id,))
            print("  + Safely consolidated duplicate Receptionist account into Sarah Jenkins.")
        cursor.execute("UPDATE users SET role = 'receptionist' WHERE role = 'admin'")
        cursor.execute("UPDATE staff SET staff_type = 'Receptionist' WHERE staff_type = 'Admin'")
    except Exception as e:
        print(f"  Note on admin account migration: {e}")

    # Ensure users role ENUM strictly supports exactly three roles: 'receptionist', 'doctor', 'patient'
    try:
        cursor.execute("ALTER TABLE users MODIFY COLUMN role ENUM('receptionist', 'doctor', 'patient') NOT NULL DEFAULT 'patient'")
        print("  + Updated users.role ENUM to exactly 3 roles ('receptionist', 'doctor', 'patient').")
    except Exception as e:
        print(f"  Note on users role ENUM: {e}")

    # 2. Check patient_registrations table
    if not column_exists('patient_registrations', 'health_concern_category'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN health_concern_category VARCHAR(100) NULL AFTER registration_notes")
        print("  + Added column 'health_concern_category' to patient_registrations.")
    if not column_exists('patient_registrations', 'symptoms_description'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN symptoms_description TEXT NULL AFTER health_concern_category")
        print("  + Added column 'symptoms_description' to patient_registrations.")
    if not column_exists('patient_registrations', 'symptom_duration'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN symptom_duration VARCHAR(50) NULL AFTER symptoms_description")
        print("  + Added column 'symptom_duration' to patient_registrations.")
    if not column_exists('patient_registrations', 'has_appointment'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN has_appointment BOOLEAN NOT NULL DEFAULT FALSE AFTER symptom_duration")
        print("  + Added column 'has_appointment' to patient_registrations.")
    if not column_exists('patient_registrations', 'appointment_notes'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN appointment_notes VARCHAR(255) NULL AFTER has_appointment")
        print("  + Added column 'appointment_notes' to patient_registrations.")
    if not column_exists('patient_registrations', 'priority_assigned_by'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN priority_assigned_by INT NULL AFTER appointment_notes")
        cursor.execute("ALTER TABLE patient_registrations ADD CONSTRAINT fk_priority_user FOREIGN KEY (priority_assigned_by) REFERENCES users(id) ON DELETE SET NULL")
        print("  + Added column 'priority_assigned_by' and FK to patient_registrations.")
    if not column_exists('patient_registrations', 'priority_assigned_at'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN priority_assigned_at DATETIME NULL AFTER priority_assigned_by")
        print("  + Added column 'priority_assigned_at' to patient_registrations.")
    if not column_exists('patient_registrations', 'assigned_doctor_id'):
        cursor.execute("ALTER TABLE patient_registrations ADD COLUMN assigned_doctor_id INT NULL AFTER priority_assigned_at")
        cursor.execute("ALTER TABLE patient_registrations ADD CONSTRAINT fk_assigned_doctor FOREIGN KEY (assigned_doctor_id) REFERENCES users(id) ON DELETE SET NULL")
        cursor.execute("ALTER TABLE patient_registrations ADD INDEX idx_reg_assigned_doctor (assigned_doctor_id)")
        print("  + Added column 'assigned_doctor_id' and FK to patient_registrations.")

    # 3. Check queue_records table
    if not column_exists('queue_records', 'call_time'):
        cursor.execute("ALTER TABLE queue_records ADD COLUMN call_time DATETIME NULL AFTER prediction_timestamp")
        print("  + Added column 'call_time' to queue_records.")

    # Ensure queue_status column supports all workflow statuses: Waiting, Called, In Consultation, Completed, Skipped, Cancelled
    try:
        cursor.execute("ALTER TABLE queue_records MODIFY COLUMN queue_status VARCHAR(30) NOT NULL DEFAULT 'Waiting'")
        print("  + Updated queue_records.queue_status to flexible VARCHAR(30) to support extended states.")
    except Exception as e:
        print(f"  Note on queue_records status: {e}")

    # 4. Check consultations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            registration_id INT NOT NULL UNIQUE,
            patient_user_id INT NULL,
            doctor_user_id INT NOT NULL,
            department_id INT NOT NULL,
            chief_complaint TEXT NULL,
            clinical_observations TEXT NULL,
            doctor_notes TEXT NULL,
            diagnosis TEXT NULL,
            treatment_plan TEXT NULL,
            prescription TEXT NULL,
            follow_up_instructions TEXT NULL,
            consultation_status VARCHAR(30) NOT NULL DEFAULT 'In Progress',
            started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (registration_id) REFERENCES patient_registrations(id) ON DELETE CASCADE,
            FOREIGN KEY (patient_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (doctor_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
            INDEX idx_consult_reg (registration_id),
            INDEX idx_consult_patient (patient_user_id),
            INDEX idx_consult_doctor (doctor_user_id),
            INDEX idx_consult_status (consultation_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 4. Check contact_requests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contact_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            request_reference VARCHAR(30) NOT NULL UNIQUE,
            patient_user_id INT NOT NULL,
            patient_name VARCHAR(120) NOT NULL,
            patient_email VARCHAR(120) NOT NULL,
            patient_phone VARCHAR(25) NULL,
            request_type VARCHAR(50) NOT NULL,
            subject VARCHAR(200) NOT NULL,
            message TEXT NOT NULL,
            preferred_contact_method VARCHAR(20) NOT NULL DEFAULT 'Email',
            preferred_callback_time VARCHAR(50) NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'Submitted',
            staff_response TEXT NULL,
            responded_by_user_id INT NULL,
            responded_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (responded_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
            INDEX idx_contact_ref (request_reference),
            INDEX idx_contact_patient (patient_user_id),
            INDEX idx_contact_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 5. Check hospital_settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hospital_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hospital_name VARCHAR(150) NOT NULL DEFAULT 'HospitalFlow General Hospital & Medical Center',
            phone VARCHAR(30) NOT NULL DEFAULT '+1 (555) 019-2830',
            emergency_phone VARCHAR(30) NOT NULL DEFAULT '+1 (555) 911-3569',
            email VARCHAR(120) NOT NULL DEFAULT 'care@hospitalflow.ai',
            address VARCHAR(255) NOT NULL DEFAULT '1200 Health Science Boulevard, Suite 400, Metro City, MC 98101',
            opening_hours VARCHAR(255) NOT NULL DEFAULT '24/7 Emergency Care | OPD: Mon - Sat 8:00 AM - 8:00 PM',
            directions_url VARCHAR(255) NULL DEFAULT 'https://maps.google.com',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)

    # 6. Check symptom_assessments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS symptom_assessments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            assessment_reference VARCHAR(30) NOT NULL UNIQUE,
            patient_user_id INT NOT NULL,
            selected_symptoms TEXT NOT NULL,
            symptom_duration VARCHAR(50) NULL,
            severity_level VARCHAR(30) NULL,
            predicted_disease VARCHAR(150) NOT NULL,
            confidence_score FLOAT NULL,
            top_predictions TEXT NULL,
            has_urgent_symptoms BOOLEAN NOT NULL DEFAULT FALSE,
            model_version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
            consultation_requested BOOLEAN NOT NULL DEFAULT FALSE,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_user_id) REFERENCES users(id) ON DELETE CASCADE,
            INDEX idx_sym_ref (assessment_reference),
            INDEX idx_sym_patient (patient_user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)
    print("  + Checked/created 'symptom_assessments' table.")

    # 7. Check consultation_requests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consultation_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            request_reference VARCHAR(30) NOT NULL UNIQUE,
            patient_user_id INT NOT NULL,
            symptom_assessment_id INT NULL,
            department_id INT NOT NULL,
            preferred_doctor_id INT NULL,
            assigned_doctor_id INT NULL,
            health_concern TEXT NOT NULL,
            preferred_date VARCHAR(50) NULL,
            preferred_time_slot VARCHAR(50) NULL,
            additional_notes TEXT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'Pending Review',
            receptionist_notes TEXT NULL,
            doctor_notes TEXT NULL,
            proposed_alternative_date VARCHAR(50) NULL,
            proposed_alternative_time_slot VARCHAR(50) NULL,
            alternative_notes TEXT NULL,
            confirmed_date VARCHAR(50) NULL,
            confirmed_time_slot VARCHAR(50) NULL,
            registration_id INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (symptom_assessment_id) REFERENCES symptom_assessments(id) ON DELETE SET NULL,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
            FOREIGN KEY (preferred_doctor_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (assigned_doctor_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (registration_id) REFERENCES patient_registrations(id) ON DELETE SET NULL,
            INDEX idx_cr_ref (request_reference),
            INDEX idx_cr_patient (patient_user_id),
            INDEX idx_cr_pref_doc (preferred_doctor_id),
            INDEX idx_cr_doctor (assigned_doctor_id),
            INDEX idx_cr_dept (department_id),
            INDEX idx_cr_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)
    print("  + Checked/created 'consultation_requests' table.")

    # Apply incremental updates to consultation_requests if table previously existed
    if not column_exists('consultation_requests', 'preferred_doctor_id'):
        cursor.execute("ALTER TABLE consultation_requests ADD COLUMN preferred_doctor_id INT NULL AFTER department_id")
        cursor.execute("ALTER TABLE consultation_requests ADD CONSTRAINT fk_cr_pref_doc FOREIGN KEY (preferred_doctor_id) REFERENCES users(id) ON DELETE SET NULL")
        print("  + Added column 'preferred_doctor_id' to consultation_requests.")
    if not column_exists('consultation_requests', 'proposed_alternative_date'):
        cursor.execute("ALTER TABLE consultation_requests ADD COLUMN proposed_alternative_date VARCHAR(50) NULL AFTER doctor_notes")
        print("  + Added column 'proposed_alternative_date' to consultation_requests.")
    if not column_exists('consultation_requests', 'proposed_alternative_time_slot'):
        cursor.execute("ALTER TABLE consultation_requests ADD COLUMN proposed_alternative_time_slot VARCHAR(50) NULL AFTER proposed_alternative_date")
        print("  + Added column 'proposed_alternative_time_slot' to consultation_requests.")
    if not column_exists('consultation_requests', 'alternative_notes'):
        cursor.execute("ALTER TABLE consultation_requests ADD COLUMN alternative_notes TEXT NULL AFTER proposed_alternative_time_slot")
        print("  + Added column 'alternative_notes' to consultation_requests.")
    if not column_exists('consultation_requests', 'confirmed_date'):
        cursor.execute("ALTER TABLE consultation_requests ADD COLUMN confirmed_date VARCHAR(50) NULL AFTER alternative_notes")
        print("  + Added column 'confirmed_date' to consultation_requests.")
    if not column_exists('consultation_requests', 'confirmed_time_slot'):
        cursor.execute("ALTER TABLE consultation_requests ADD COLUMN confirmed_time_slot VARCHAR(50) NULL AFTER confirmed_date")
        print("  + Added column 'confirmed_time_slot' to consultation_requests.")

    # 8. Check staff table additions
    if not column_exists('staff', 'qualification'):
        cursor.execute("ALTER TABLE staff ADD COLUMN qualification VARCHAR(100) NULL AFTER is_available")
        print("  + Added column 'qualification' to staff.")
    if not column_exists('staff', 'license_number'):
        cursor.execute("ALTER TABLE staff ADD COLUMN license_number VARCHAR(100) NULL AFTER qualification")
        print("  + Added column 'license_number' to staff.")
    if not column_exists('staff', 'experience_years'):
        cursor.execute("ALTER TABLE staff ADD COLUMN experience_years INT NOT NULL DEFAULT 0 AFTER license_number")
        print("  + Added column 'experience_years' to staff.")

    # 9. Check consultations table additions
    if not column_exists('consultations', 'follow_up_date'):
        cursor.execute("ALTER TABLE consultations ADD COLUMN follow_up_date VARCHAR(50) NULL AFTER follow_up_instructions")
        print("  + Added column 'follow_up_date' to consultations.")
    if not column_exists('consultations', 'referral_department_id'):
        cursor.execute("ALTER TABLE consultations ADD COLUMN referral_department_id INT NULL AFTER follow_up_date")
        cursor.execute("ALTER TABLE consultations ADD CONSTRAINT fk_consult_ref_dept FOREIGN KEY (referral_department_id) REFERENCES departments(id) ON DELETE SET NULL")
        print("  + Added column 'referral_department_id' to consultations.")
    if not column_exists('consultations', 'referral_notes'):
        cursor.execute("ALTER TABLE consultations ADD COLUMN referral_notes TEXT NULL AFTER referral_department_id")
        print("  + Added column 'referral_notes' to consultations.")
    if not column_exists('consultations', 'is_referred'):
        cursor.execute("ALTER TABLE consultations ADD COLUMN is_referred BOOLEAN NOT NULL DEFAULT FALSE AFTER referral_notes")
        print("  + Added column 'is_referred' to consultations.")

    # 10. Check doctor_registration_requests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS doctor_registration_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            full_name VARCHAR(120) NOT NULL,
            email VARCHAR(120) NOT NULL UNIQUE,
            phone VARCHAR(25) NULL,
            qualification VARCHAR(100) NOT NULL,
            specialization VARCHAR(100) NOT NULL,
            department_id INT NOT NULL,
            license_number VARCHAR(100) NOT NULL,
            experience_years INT NOT NULL DEFAULT 0,
            password_hash VARCHAR(255) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'Pending',
            rejection_reason TEXT NULL,
            reviewed_by_user_id INT NULL,
            reviewed_at DATETIME NULL,
            user_id INT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
            FOREIGN KEY (reviewed_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            INDEX idx_dr_email (email),
            INDEX idx_dr_status (status),
            INDEX idx_dr_dept (department_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """)
    print("  + Checked/created 'doctor_registration_requests' table.")

    # Seed default hospital setting if empty
    cursor.execute("SELECT COUNT(*) FROM hospital_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO hospital_settings (hospital_name, phone, emergency_phone, email, address, opening_hours, directions_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            'HospitalFlow General Hospital & Medical Center',
            '+1 (555) 019-2830',
            '+1 (555) 911-3569',
            'care@hospitalflow.ai',
            '1200 Health Science Boulevard, Suite 400, Metro City, MC 98101',
            '24/7 Emergency Care | OPD: Mon - Sat 8:00 AM - 8:00 PM',
            'https://maps.google.com'
        ))
        print("  + Seeded default hospital contact settings.")

    print("Safe database migrations completed successfully.")


def init_database():
    print("=" * 60)
    print("HospitalFlow AI - Database Initialization & Safe Migration")
    print("=" * 60)
    print(f"Connecting to MySQL server at {DB_HOST}:{DB_PORT} as '{DB_USER}'...")

    try:
        # Step 1: Connect to server without database to create DB if needed
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            autocommit=True
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        print(f"Database `{DB_NAME}` verified/created.")
        cursor.close()
        conn.close()

        # Step 2: Connect to specific database
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            autocommit=False
        )
        cursor = conn.cursor()

        # Execute base schema tables
        print("Executing schema.sql...")
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]
        for stmt in statements:
            if stmt.upper().startswith('CREATE DATABASE') or stmt.upper().startswith('USE '):
                continue
            cursor.execute(stmt)
        conn.commit()

        # Execute department seed
        print("Executing seed_departments.sql...")
        with open(SEED_PATH, 'r', encoding='utf-8') as f:
            seed_sql = f.read()
        statements = [stmt.strip() for stmt in seed_sql.split(';') if stmt.strip()]
        for stmt in statements:
            if stmt.upper().startswith('USE '):
                continue
            cursor.execute(stmt)
        conn.commit()
        print("Departments successfully seeded.")

        # Apply safe incremental migrations
        apply_safe_migrations(cursor)
        conn.commit()

        # Step 3: Seed initial default accounts if not present
        users_to_seed = [
            {
                'full_name': 'Sarah Jenkins (Lead Receptionist)',
                'email': 'receptionist@hospitalflow.ai',
                'phone': '+1 (555) 019-8822',
                'age': 34,
                'gender': 'Female',
                'password': 'Reception@12345',
                'role': 'receptionist'
            },
            {
                'full_name': 'Michael Chen (Patient)',
                'email': 'patient@hospitalflow.ai',
                'phone': '+1 (555) 019-3344',
                'age': 35,
                'gender': 'Male',
                'password': 'Patient@12345',
                'role': 'patient'
            },
            {
                'full_name': 'Dr. Alexander Smith, MD',
                'email': 'dr.smith@hospitalflow.ai',
                'phone': '+1 (555) 019-4567',
                'age': 45,
                'gender': 'Male',
                'password': 'Doctor@12345',
                'role': 'doctor'
            },
            {
                'full_name': 'Dr. Priya Patel, MD',
                'email': 'dr.patel@hospitalflow.ai',
                'phone': '+1 (555) 019-7890',
                'age': 39,
                'gender': 'Female',
                'password': 'Doctor@12345',
                'role': 'doctor'
            }
        ]

        for u in users_to_seed:
            cursor.execute("SELECT id FROM users WHERE email = %s", (u['email'],))
            exists = cursor.fetchone()
            if not exists:
                pwd_hash = generate_password_hash(u['password'])
                cursor.execute(
                    """
                    INSERT INTO users (full_name, email, phone, age, gender, password_hash, role, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (u['full_name'], u['email'], u['phone'], u['age'], u['gender'], pwd_hash, u['role'])
                )
                print(f"Created default {u['role']} user: {u['email']}")
            else:
                # Update age and gender if null
                cursor.execute(
                    "UPDATE users SET age = COALESCE(age, %s), gender = COALESCE(gender, %s) WHERE email = %s",
                    (u['age'], u['gender'], u['email'])
                )
        conn.commit()

        # Step 4: Associate staff records for receptionist and doctors
        cursor.execute("SELECT id FROM users WHERE email = %s", ('receptionist@hospitalflow.ai',))
        rec_user = cursor.fetchone()
        cursor.execute("SELECT id FROM departments WHERE code = 'GP'")
        gp_dept = cursor.fetchone()
        if rec_user and gp_dept:
            cursor.execute("SELECT id FROM staff WHERE user_id = %s", (rec_user[0],))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO staff (user_id, department_id, staff_type, is_available) VALUES (%s, %s, 'Receptionist', 1)",
                    (rec_user[0], gp_dept[0])
                )
                conn.commit()
                print("Staff record created for Lead Receptionist.")

        # Associate staff record for Dr. Alexander Smith (General Practice)
        cursor.execute("SELECT id FROM users WHERE email = %s", ('dr.smith@hospitalflow.ai',))
        smith_user = cursor.fetchone()
        if smith_user and gp_dept:
            cursor.execute("SELECT id FROM staff WHERE user_id = %s", (smith_user[0],))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO staff (user_id, department_id, staff_type, is_available) VALUES (%s, %s, 'Doctor', 1)",
                    (smith_user[0], gp_dept[0])
                )
                conn.commit()
                print("Staff record created for Dr. Alexander Smith (General Practice).")

        # Associate staff record for Dr. Priya Patel (Cardiology)
        cursor.execute("SELECT id FROM users WHERE email = %s", ('dr.patel@hospitalflow.ai',))
        patel_user = cursor.fetchone()
        cursor.execute("SELECT id FROM departments WHERE code = 'CARD'")
        card_dept = cursor.fetchone()
        if patel_user and card_dept:
            cursor.execute("SELECT id FROM staff WHERE user_id = %s", (patel_user[0],))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO staff (user_id, department_id, staff_type, is_available) VALUES (%s, %s, 'Doctor', 1)",
                    (patel_user[0], card_dept[0])
                )
                conn.commit()
                print("Staff record created for Dr. Priya Patel (Cardiology).")

        # Step 5: Record initial model run in model_runs table if report exists
        if os.path.exists(MODEL_REPORT_PATH):
            with open(MODEL_REPORT_PATH, 'r', encoding='utf-8') as f:
                rep = json.load(f)
            best_model = rep.get('best_model', 'Random Forest')
            metrics = rep.get('best_metrics', {})
            mae = metrics.get('mae', 0.0)
            rmse = metrics.get('rmse', 0.0)
            r2 = metrics.get('r2_score', 0.0)

            cursor.execute("SELECT COUNT(*) FROM model_runs")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    """
                    INSERT INTO model_runs (model_name, dataset_reference, mae, rmse, r2_score, model_version, training_status)
                    VALUES (%s, %s, %s, %s, %s, '1.0.0', 'COMPLETED')
                    """,
                    (best_model, rep.get('dataset', 'Hospital_ER.csv'), mae, rmse, r2)
                )
                conn.commit()
                print(f"Initial model run audit record inserted ({best_model}, MAE: {mae}).")

        cursor.close()
        conn.close()
        print("\nDatabase initialization & migration completed successfully!")
        return True

    except Exception as e:
        print(f"Database initialization failed: {e}", file=sys.stderr)
        raise e


if __name__ == '__main__':
    init_database()

-- HospitalFlow AI Database Schema
-- Compatible with MySQL / MariaDB (XAMPP)

CREATE DATABASE IF NOT EXISTS hospitalflow_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hospitalflow_ai;

-- 1. Users Table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    phone VARCHAR(25) NULL,
    age INT NULL,
    gender VARCHAR(10) NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('receptionist', 'doctor', 'patient') NOT NULL DEFAULT 'patient',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_role (role),
    INDEX idx_user_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Departments Table
CREATE TABLE IF NOT EXISTS departments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    department_name VARCHAR(80) NOT NULL UNIQUE,
    code VARCHAR(10) NOT NULL UNIQUE,
    description TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_dept_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Staff Table
CREATE TABLE IF NOT EXISTS staff (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    department_id INT NOT NULL,
    staff_type VARCHAR(50) NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    qualification VARCHAR(100) NULL,
    license_number VARCHAR(100) NULL,
    experience_years INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
    INDEX idx_staff_user (user_id),
    INDEX idx_staff_dept (department_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Patient Registrations Table
CREATE TABLE IF NOT EXISTS patient_registrations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patient_user_id INT NULL,
    patient_name VARCHAR(120) NOT NULL,
    patient_phone VARCHAR(25) NULL,
    patient_age INT NOT NULL DEFAULT 35,
    patient_gender VARCHAR(10) NOT NULL DEFAULT 'Female',
    registered_by INT NOT NULL,
    department_id INT NOT NULL,
    token_number VARCHAR(30) NOT NULL UNIQUE,
    arrival_time DATETIME NOT NULL,
    triage_priority INT NOT NULL DEFAULT 3 COMMENT '1=Emergency, 2=Urgent, 3=Routine, 4=Low',
    registration_notes TEXT NULL,
    health_concern_category VARCHAR(100) NULL,
    symptoms_description TEXT NULL,
    symptom_duration VARCHAR(50) NULL,
    has_appointment BOOLEAN NOT NULL DEFAULT FALSE,
    appointment_notes VARCHAR(255) NULL,
    priority_assigned_by INT NULL,
    priority_assigned_at DATETIME NULL,
    assigned_doctor_id INT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (registered_by) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
    FOREIGN KEY (priority_assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (assigned_doctor_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_reg_token (token_number),
    INDEX idx_reg_patient_user (patient_user_id),
    INDEX idx_reg_dept (department_id),
    INDEX idx_reg_assigned_doctor (assigned_doctor_id),
    INDEX idx_reg_arrival (arrival_time),
    INDEX idx_reg_priority (triage_priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. Queue Records Table
CREATE TABLE IF NOT EXISTS queue_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    registration_id INT NOT NULL UNIQUE,
    queue_status VARCHAR(30) NOT NULL DEFAULT 'Waiting',
    patients_ahead INT NOT NULL DEFAULT 0,
    estimated_wait_minutes FLOAT NOT NULL DEFAULT 0.0,
    prediction_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    call_time DATETIME NULL,
    consultation_start_time DATETIME NULL,
    completion_time DATETIME NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (registration_id) REFERENCES patient_registrations(id) ON DELETE CASCADE,
    INDEX idx_queue_status (queue_status),
    INDEX idx_queue_reg (registration_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Consultations Table
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
    follow_up_date VARCHAR(50) NULL,
    referral_department_id INT NULL,
    referral_notes TEXT NULL,
    is_referred BOOLEAN NOT NULL DEFAULT FALSE,
    consultation_status VARCHAR(30) NOT NULL DEFAULT 'In Progress',
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (registration_id) REFERENCES patient_registrations(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (doctor_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
    FOREIGN KEY (referral_department_id) REFERENCES departments(id) ON DELETE SET NULL,
    INDEX idx_consult_reg (registration_id),
    INDEX idx_consult_patient (patient_user_id),
    INDEX idx_consult_doctor (doctor_user_id),
    INDEX idx_consult_status (consultation_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. In-Site Contact Requests Table
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

-- 7. Hospital Settings Table
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

-- 8. Model Runs / Audit Table
CREATE TABLE IF NOT EXISTS model_runs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_name VARCHAR(80) NOT NULL,
    dataset_reference VARCHAR(255) NOT NULL,
    mae FLOAT NOT NULL,
    rmse FLOAT NOT NULL,
    r2_score FLOAT NOT NULL,
    model_version VARCHAR(20) NOT NULL,
    training_status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. Symptom Assessments Table (ML Disease Classifier)
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

-- 10. Consultation Requests Table
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

-- 11. Doctor Self-Registration Requests Table
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


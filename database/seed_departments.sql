-- HospitalFlow AI Department Seed Data
USE hospitalflow_ai;

INSERT INTO departments (department_name, code, description, is_active) VALUES
('Emergency Department', 'EM', 'Acute critical care, trauma triage, and rapid stabilization services.', 1),
('General Practice', 'GP', 'Primary healthcare consultations, routine screenings, and general medical care.', 1),
('Orthopedics', 'ORT', 'Musculoskeletal diagnostics, bone fracture care, and joint injury consultations.', 1),
('Cardiology', 'CARD', 'Cardiovascular evaluation, ECG assessment, and heart care consultations.', 1),
('Neurology', 'NEUR', 'Nervous system diagnostics, stroke recovery monitoring, and neurological consultations.', 1),
('Gastroenterology', 'GAST', 'Digestive tract care, abdominal pain evaluation, and GI consultations.', 1),
('Physiotherapy', 'PHYS', 'Physical rehabilitation, mobility restoration, and post-injury therapy.', 1),
('Renal', 'REN', 'Nephrology consultations, kidney function monitoring, and renal patient care.', 1)
ON DUPLICATE KEY UPDATE description=VALUES(description);

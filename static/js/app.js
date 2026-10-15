/**
 * HospitalFlow AI - Client-Side Interactivity & Polling
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Password Visibility Toggle
    const toggleBtns = document.querySelectorAll('.password-toggle-btn');
    toggleBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (input) {
                if (input.type === 'password') {
                    input.type = 'text';
                    btn.textContent = 'Hide';
                } else {
                    input.type = 'password';
                    btn.textContent = 'Show';
                }
            }
        });
    });

    // 2. Client-side Form Validation
    const authForms = document.querySelectorAll('form[data-validate="true"]');
    authForms.forEach(form => {
        form.addEventListener('submit', (e) => {
            const pwd = form.querySelector('input[name="password"]');
            const confirmPwd = form.querySelector('input[name="confirm_password"]');
            if (pwd && confirmPwd) {
                if (pwd.value !== confirmPwd.value) {
                    e.preventDefault();
                    alert("Passwords do not match. Please verify both entries.");
                    confirmPwd.focus();
                }
            }
        });
    });

    // 3. Client-side Table Search Filter (for instant responsiveness)
    const searchInputs = document.querySelectorAll('[data-table-search]');
    searchInputs.forEach(input => {
        const tableId = input.getAttribute('data-table-search');
        const table = document.getElementById(tableId);
        if (table) {
            input.addEventListener('keyup', () => {
                const term = input.value.toLowerCase().trim();
                const rows = table.querySelectorAll('tbody tr');
                rows.forEach(row => {
                    const text = row.innerText.toLowerCase();
                    row.style.display = text.includes(term) ? '' : 'none';
                });
            });
        }
    });

    // 4. Asynchronous Queue Poller for Patient Dashboard
    const patientLiveContainer = document.getElementById('patient-live-status');
    if (patientLiveContainer) {
        setInterval(async () => {
            try {
                const res = await fetch('/patient/api/status');
                if (res.ok) {
                    const data = await res.json();
                    if (data.has_active) {
                        const waitElem = document.getElementById('live-wait-minutes');
                        const aheadElem = document.getElementById('live-patients-ahead');
                        const statusElem = document.getElementById('live-queue-status');
                        const updateElem = document.getElementById('live-last-updated');

                        if (waitElem) waitElem.textContent = data.estimated_wait_minutes;
                        if (aheadElem) aheadElem.textContent = data.patients_ahead;
                        if (statusElem) {
                            if (data.queue_status === 'Called') {
                                statusElem.textContent = 'Called — Proceed to Consultation';
                                statusElem.className = 'badge badge-called';
                            } else if (data.queue_status === 'Waiting') {
                                statusElem.textContent = 'Waiting for Doctor';
                                statusElem.className = 'badge badge-waiting';
                            } else if (data.queue_status === 'In Consultation') {
                                statusElem.textContent = 'In Consultation';
                                statusElem.className = 'badge badge-consult';
                            } else {
                                statusElem.textContent = data.queue_status;
                                statusElem.className = 'badge badge-completed';
                            }
                        }
                        if (updateElem) updateElem.textContent = data.last_updated;
                    }
                }
            } catch (err) {
                console.debug('Polling wait time status:', err);
            }
        }, 10000); // Poll every 10 seconds
    }
});

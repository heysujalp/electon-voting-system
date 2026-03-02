/**
 * ElectON V2 — Ballot page logic
 * Handles radio selection styling and vote submission.
 */

(function () {
    'use strict';

    const form = document.getElementById('voteForm');
    if (!form) return;

    const voteUrl = form.dataset.voteUrl;
    const btn = document.getElementById('submitVoteBtn');
    const errorDiv = document.getElementById('voteError');

    // ── Custom radio selection styling ──
    document.querySelectorAll('.candidate-option').forEach(label => {
        label.addEventListener('click', () => {
            const radio = label.querySelector('input[type="radio"]');
            const name = radio.name;
            document.querySelectorAll(`label:has(input[name="${name}"])`)
                .forEach(l => l.classList.remove('selected'));
            label.classList.add('selected');
        });
    });

    // ── Form submission ──
    if (!btn || !voteUrl) return;

    let submitting = false;  // Double-submit guard (FE-09)

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        if (submitting) return;
        submitting = true;
        if (errorDiv) errorDiv.style.display = 'none';  // FE-08: null check

        if (!confirm('Are you sure you want to submit your vote? This cannot be changed.')) {
            submitting = false;  // FE-08: reset guard on cancel
            return;
        }

        const formData = new FormData(this);
        const votes = {};
        for (const [key, value] of formData.entries()) {
            if (key.startsWith('post_')) {
                votes[key.replace('post_', '')] = value;
            }
        }

        // FE-19: Validate all positions have a selection before submitting
        // Posts with data-abstain="true" are allowed to have no selection
        const allPosts = form.querySelectorAll('.post-section');
        const missing = [];
        allPosts.forEach(section => {
            const radios = section.querySelectorAll('input[type="radio"]');
            if (!radios.length) return;
            const name = radios[0].name;
            const hasSelection = formData.get(name);
            if (!hasSelection) {
                const allowsAbstain = section.dataset.abstain === 'true';
                if (!allowsAbstain) {
                    missing.push(name);
                }
            }
        });
        if (missing.length > 0) {
            showError('Please make a selection for all positions before submitting.');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Submitting...';

        try {
            const resp = await fetch(voteUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': formData.get('csrfmiddlewaretoken'),
                },
                body: JSON.stringify({ votes }),
            });
            const data = await resp.json();
            if (data.success) {
                // Show confirmation before redirect
                btn.innerHTML = '<i class="fas fa-check-circle me-2"></i>Vote Recorded!';
                btn.style.background = 'var(--apple-green, #34c759)';
                btn.style.borderColor = 'var(--apple-green, #34c759)';

                // Brief delay to show success state, then redirect
                setTimeout(() => {
                    window.location.href = data.redirect_url;
                }, 800);
            } else {
                showError(data.message);
            }
        } catch (err) {
            showError('An error occurred. Please try again.');
        }
    });

    function showError(msg) {
        errorDiv.textContent = msg;
        errorDiv.style.display = 'block';
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-check-circle me-2"></i>Submit Vote';
        submitting = false;
    }
})();

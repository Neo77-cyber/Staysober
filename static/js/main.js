document.addEventListener('DOMContentLoaded', function() {
    const radios = document.querySelectorAll('input[name="habit_choice"]');
    const customInput = document.getElementById('custom_habit');
    const form = document.querySelector('form');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = document.getElementById('btn-text');
    const spinner = document.getElementById('spinner');

    // Handle Custom Habit Input visibility
    radios.forEach(r => {
        r.addEventListener('change', (e) => {
            if(e.target.value === 'custom') {
                customInput.style.display = 'block';
                customInput.required = true;
                customInput.focus();
            } else {
                customInput.style.display = 'none';
                customInput.required = false;
            }
        });
    });

    // Form Submission Spinner
    form.addEventListener('submit', () => {
        btnText.style.display = 'none';
        spinner.style.display = 'block';
        submitBtn.disabled = true;
    });

    // Auto-hide messages
    setTimeout(function() {
        let messages = document.querySelectorAll('.alert');
        messages.forEach(function(msg) {
            msg.style.transition = "opacity 0.5s ease";
            msg.style.opacity = "0";
            setTimeout(() => msg.remove(), 500);
        });
    }, 5000);
});

 const CSRF = "{{ csrf_token }}";

    function handleClockIn(btn) {
        const card = btn.closest('.habit-card');
        if (card.classList.contains('done')) return;

        markDone(card);
    }

    function markDone(card) {
        const habitId = card.dataset.habitId;

        fetch(`/habits/${habitId}/mark-done/`, {
            method: "POST",
            headers: { "X-CSRFToken": CSRF, "Content-Type": "application/json" }
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === "success") {
                const streakEl = document.getElementById(`streak-${habitId}`);
                if (streakEl) streakEl.textContent = data.current_streak;

                card.classList.add('done');

                
                const btn = card.querySelector('.clock-in-btn');
                if (btn) {
                    const badge = document.createElement('div');
                    badge.className = 'done-badge';
                    badge.textContent = 'CLOCKED IN';
                    btn.replaceWith(badge);
                }

                showCelebration(data.current_streak);
            } else {
                location.reload();
            }
        })
        .catch(() => location.reload());
    }

    function showCelebration(streak) {
        document.getElementById("celebEmoji").textContent = "";
        document.getElementById("celebTitle").textContent = "Clocked in!";
        document.getElementById("celebMsg").textContent = `${streak} day streak. Don't stop now.`;
        document.getElementById("celebrationOverlay").classList.remove("hidden");
    }

    
    document.body.addEventListener('htmx:afterOnLoad', (e) => {
        
    });
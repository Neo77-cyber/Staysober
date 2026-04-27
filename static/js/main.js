document.addEventListener('DOMContentLoaded', () => {

    
    document.querySelectorAll('.toggle-password-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = btn.closest('.relative').querySelector('input');
            const eyeIcon = btn.querySelector('.eye-icon');
            const eyeSlashIcon = btn.querySelector('.eye-slash-icon');
            if (!input) return;

            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            eyeIcon.classList.toggle('hidden', isPassword);
            eyeSlashIcon.classList.toggle('hidden', !isPassword);
        });
    });

    
    const habitRadios = document.querySelectorAll('input[name="habit_choice"]');
    const customInput = document.getElementById('custom_habit');

    habitRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            if (!customInput) return;
            const isCustom = e.target.value === 'something-else';
            customInput.classList.toggle('hidden', !isCustom);
            customInput.required = isCustom;
            if (isCustom) customInput.focus();
        });
    });

   
    const checkedRadio = document.querySelector('input[name="habit_choice"]:checked');
    if (checkedRadio && checkedRadio.value === 'something-else' && customInput) {
        customInput.classList.remove('hidden');
        customInput.required = true;
    }


    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function (e) {
            
            const selectedRadio = form.querySelector('input[name="habit_choice"]:checked');
            if (selectedRadio && selectedRadio.value === 'something-else') {
                selectedRadio.value = 'custom';
            }

            if (this.hasAttribute('hx-post') || this.hasAttribute('hx-get')) return;
            
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                const btnText = submitBtn.querySelector('.btn-text');
                const spinner = submitBtn.querySelector('.btn-spinner');
                submitBtn.disabled = true;
                submitBtn.classList.add('opacity-80', 'cursor-not-allowed');
                if (btnText) btnText.classList.add('hidden');
                if (spinner) spinner.classList.remove('hidden');
            }
        });
    });

    
    setTimeout(() => {
        document.querySelectorAll('.alert-msg, .alert, .django-message').forEach(msg => {
            msg.style.transition = 'opacity 0.5s ease';
            msg.style.opacity = '0';
            setTimeout(() => msg.remove(), 500);
        });
    }, 5000);

});


function handleClockIn(btn) {
    const card = btn.closest('.habit-card');
    if (!card || card.classList.contains('done')) return;
    markDone(card);
}

function markDone(card) {
    const habitId = card.dataset.habitId;
    const CSRF = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

    
    const btn = card.querySelector('.clock-in-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '...';
        btn.classList.add('opacity-50', 'cursor-not-allowed');
    }

    fetch(`/habits/${habitId}/mark-done/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF, 'Content-Type': 'application/json' },
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            
            const streakEl = document.getElementById(`streak-${habitId}`);
            if (streakEl) streakEl.textContent = data.current_streak;

            
            const progressBar = card.querySelector('.bg-violet-600');
            if (progressBar) {
                const pct = Math.min((data.current_streak / 30) * 100, 100);
                progressBar.style.width = pct + '%';
            }

            
            card.classList.add('done', 'opacity-80', 'border-violet-500/30');
            card.dataset.marked = 'true';

            
            const btnContainer = card.querySelector('.clock-in-btn')?.parentElement;
            if (btnContainer) {
                btnContainer.innerHTML = `
                    <div class="done-badge flex flex-col items-center gap-1">
                        <div class="bg-violet-500/20 p-2 rounded-full">
                            <svg class="w-5 h-5 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
                            </svg>
                        </div>
                        <span class="text-[10px] font-extrabold uppercase tracking-widest text-violet-400">
                            Clocked In
                        </span>
                    </div>
                `;
            }

            showCelebration(data.current_streak);

            const totalStreakEl = document.getElementById('totalStreak');
                if (totalStreakEl && data.total_streak !== undefined) {
                    totalStreakEl.textContent = data.total_streak;
                }

        } else if (data.status === 'banned') {
            window.location.href = '/banned/';

        } else {
            
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Clock In';
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }
    })
    .catch(() => {
        
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Clock In';
            btn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
    });
}


function showCelebration(streak) {
    const overlay = document.getElementById('celebrationOverlay');
    const emoji   = document.getElementById('celebEmoji');
    const title   = document.getElementById('celebTitle');
    const msg     = document.getElementById('celebMsg');

    if (!overlay) return;

    
    if (streak >= 30) {
        emoji.textContent = '';
        title.textContent = 'Legend Status';
        msg.textContent   = `30 days strong. You actually did it.`;
    } else if (streak >= 21) {
        emoji.textContent = '';
        title.textContent = 'On Fire';
        msg.textContent   = `${streak} days. This is a lifestyle now.`;
    } else if (streak >= 14) {
        emoji.textContent = '';
        title.textContent = 'Two Weeks Deep';
        msg.textContent   = `${streak} days straight. No weak links.`;
    } else if (streak >= 7) {
        emoji.textContent = '';
        title.textContent = 'One Week Done';
        msg.textContent   = `${streak} days. The habit is forming.`;
    } else if (streak === 1) {
        emoji.textContent = '';
        title.textContent = 'Day One Done';
        msg.textContent   = `Every legend starts somewhere. Let's go.`;
    } else {
        emoji.textContent = '';
        title.textContent = `Day ${streak}`;
        msg.textContent   = `Keep the streak alive. Don't stop now.`;
    }

    overlay.classList.remove('hidden');
}
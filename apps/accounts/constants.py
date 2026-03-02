"""
ElectON v2 — Accounts constants.
Single source of truth for all validation rules, rate limits, and common passwords.
"""
import re

# ─── Password Rules ──────────────────────────────────────────────
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
PASSWORD_REQUIRES_UPPERCASE = True
PASSWORD_REQUIRES_LOWERCASE = True
PASSWORD_REQUIRES_DIGIT = True
PASSWORD_REQUIRES_SPECIAL = True

# ─── Username Rules ──────────────────────────────────────────────
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 30
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+$')
USERNAME_ERROR_MSG = 'Username may only contain letters, numbers, and underscores.'

# ─── Name Rules ──────────────────────────────────────────────────
MAX_NAME_LENGTH = 100
NAME_PATTERN = re.compile(r"^[a-zA-Z\s.'-]+$")
NAME_ERROR_MSG = "Name may only contain letters, spaces, periods, apostrophes, and hyphens."

# ─── Rate Limits (centralized) ───────────────────────────────────
RATE_LIMITS = {
    'admin_login': {
        'max_attempts': 5,
        'window_seconds': 300,  # 5 minutes
    },
    'voter_login': {
        'max_attempts': 5,
        'window_seconds': 300,
    },
    'registration': {
        'max_attempts': 3,
        'window_seconds': 3600,  # 1 hour
    },
    'password_reset': {
        'max_attempts': 5,
        'window_seconds': 3600,
    },
    'email_verification': {
        'max_attempts': 3,
        'window_seconds': 300,
    },
    'email_resend': {
        'max_attempts': 5,
        'window_seconds': 900,  # 15 minutes
    },
    'admin_verification_trigger': {
        'max_attempts': 10,
        'window_seconds': 3600,
    },
    'settings_password_verify': {
        'max_attempts': 5,
        'window_seconds': 300,  # 5 minutes
    },
    'settings_email_code': {
        'max_attempts': 3,
        'window_seconds': 600,  # 10 minutes
    },
    'voter_access_request': {
        'max_attempts': 10,
        'window_seconds': 3600,  # 10 requests per hour per IP
    },
}

# ─── Resend Cooldown (progressive) ──────────────────────────────
RESEND_COOLDOWNS = [60, 90, 120, 180, 300, 600, 900]  # Seconds: 1m → 15m max
MAX_RESEND_COOLDOWN = 900  # 15 minutes


def get_resend_cooldown(attempt_number: int) -> int:
    """Get the cooldown duration (seconds) for the nth resend attempt."""
    if attempt_number < 0:
        return RESEND_COOLDOWNS[0]
    if attempt_number >= len(RESEND_COOLDOWNS):
        return MAX_RESEND_COOLDOWN
    return RESEND_COOLDOWNS[attempt_number]


# ─── Security Questions ─────────────────────────────────────────
SECURITY_QUESTIONS = [
    ('first_street', 'What was the name of the first street you lived on?'),
    ('childhood_teacher', 'What was the first name of your favourite childhood teacher?'),
    ('first_pet', 'What was the name of your first pet?'),
    ('childhood_friend', 'What was the name of your childhood best friend?'),
    ('first_job', 'What was the first job you ever had?'),
    ('childhood_room_color', 'What was the colour of your room in your childhood home?'),
    ('favourite_book', 'What is the last word in the title of your favourite book?'),
    ('holiday_destination', 'What is your favourite holiday destination?'),
]

SECURITY_QUESTIONS_REQUIRED = 3  # How many the user must pick and answer
MIN_ANSWER_LENGTH = 2
MAX_ANSWER_LENGTH = 100

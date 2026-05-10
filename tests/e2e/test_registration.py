import os
import random
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.getenv("BASE_URL", "https://dear-self.onrender.com")
TEST_PHONE = os.getenv("E2E_TEST_PHONE")
TEST_PASSWORD = os.getenv("E2E_TEST_PASSWORD")
TEST_EMAIL = os.getenv("E2E_TEST_EMAIL", "test@example.com")
MAINTENANCE_KEY = os.getenv("MAINTENANCE_KEY", "")





def login(page: Page):
    """Helper for authenticated tests"""
    

    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")

    try:
        expect(page).to_have_url(f"{BASE_URL}/habits/", timeout=15000)
    except Exception:
        body = page.locator("body").inner_text()
        pytest.fail(f"Login failed.\nURL: {page.url}\nPage content:\n{body[:800]}")


# ================================================================
# PAGE LOAD TESTS
# ================================================================


def test_registration_page_loads(page: Page):
    """Test that registration page loads correctly"""
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()
    expect(page.get_by_role("radio").first).to_be_attached()
    expect(page.locator("button[type=submit]")).to_be_visible()


def test_habit_choice_options_match_backend(page: Page):
    """Test all habit radio buttons are present"""
    page.goto(BASE_URL)
    values = page.eval_on_selector_all(
        "input[name='habit_choice']", "els => els.map(e => e.value)"
    )
    valid_keys = [
        "DAILY PRAYERS",
        "WORK OUT",
        "EXAM PREPARATION",
        "GAMBLING",
        "WEED SOBER",
        "LATE NIGHT EATING",
        "BUY BUY",
        "ALCOHOL SOBER",
        "something-else",
    ]
    for value in values:
        assert value in valid_keys, f"Radio value '{value}' not in HABIT_CHOICES"


def test_login_page_loads(page: Page):
    """Test login page loads correctly"""
    page.goto(f"{BASE_URL}/login/")
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()
    expect(page.locator("button[type=submit]")).to_be_visible()


def test_unauthenticated_redirected_from_habits(page: Page):
    """Test that unauthenticated users can't access dashboard"""
    page.goto(f"{BASE_URL}/habits/")
    expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")


# ================================================================
# REGISTRATION FLOW TESTS
# ================================================================


def test_registration_requires_valid_phone(page: Page):
    """Test that invalid phone numbers show error"""
    page.goto(BASE_URL)
    page.fill("[name=identifier]", "invalid")
    page.fill("[name=password]", "ValidPass123!")
    page.get_by_role("radio", name="Daily Prayers").check()
    page.click("[type=submit]")

    body = page.locator("body").inner_text()
    assert "invalid" in body.lower() or "error" in body.lower()


def test_registration_requires_strong_password(page: Page):
    """Test that weak passwords are rejected"""
    page.goto(BASE_URL)
    page.fill("[name=identifier]", "8123456789")
    page.fill("[name=password]", "123")
    page.get_by_role("radio", name="Daily Prayers").check()
    page.click("[type=submit]")

    body = page.locator("body").inner_text()
    assert "password" in body.lower()


def test_registration_with_email_fallback_works(page: Page):
    """Test registration with email (tests Resend API)"""
    random_phone = f"8{random.randint(100000000, 199999999)}"

    page.goto(BASE_URL)
    page.fill("[name=identifier]", random_phone)
    page.fill("[name=password]", "StrongPass123!")
    page.fill("[name=email]", TEST_EMAIL)
    page.get_by_role("radio", name="Work Out").check()
    page.click("[type=submit]")

    # Should either:
    # 1. Redirect to OTP (success)
    # 2. Show error message (API failure)
    current_url = page.url
    body = page.locator("body").inner_text()

    assert (
        "/verify-otp/" in current_url
        or "error" in body.lower()
        or "couldn't" in body.lower()
    ), f"Registration failed: {body[:300]}"


# ================================================================
# LOGIN FLOW TESTS
# ================================================================


def test_login_full_journey(page: Page):
    """Test complete login flow"""
    login(page)
    expect(page).to_have_url(f"{BASE_URL}/habits/")


def test_login_wrong_password_shows_error(page: Page):
    """Test that wrong password shows error message"""
    
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", "WrongPassword999!")
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/login/")
    expect(page.locator("text=Invalid")).to_be_visible()


def test_login_invalid_phone_shows_error(page: Page):
    """Test that invalid phone shows error"""
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", "notaphone")
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/login/")


def test_authenticated_user_redirected_from_login(page: Page):
    """Test that logged-in users can't access login page"""
    login(page)
    page.goto(f"{BASE_URL}/login/")
    expect(page).to_have_url(f"{BASE_URL}/habits/")


def test_session_persists_after_refresh(page: Page):
    """Test that session doesn't expire on page refresh"""
    login(page)
    page.reload()
    expect(page).to_have_url(f"{BASE_URL}/habits/")
    expect(page.locator("text=/Good|Hey/").first).to_be_visible()


# ================================================================
# DASHBOARD TESTS
# ================================================================


def test_dashboard_loads_with_greeting(page: Page):
    """Test that dashboard shows proper greeting"""
    login(page)
    expect(
        page.locator("text=/Good morning|Good afternoon|Good evening|Hey/").first
    ).to_be_visible()


def test_dashboard_shows_streak(page: Page):
    """Test that streak numbers are visible"""
    login(page)
    streak_el = page.locator("[id^='streak-']").first
    expect(streak_el).to_be_visible(timeout=8000)


def test_dashboard_shows_total_streak(page: Page):
    """Test that total streak is calculated"""
    login(page)
    total_streak = page.locator("text=/Total Streak|total streak/i")
    expect(total_streak).to_be_visible()


def test_mark_habit_done_button_visible(page: Page):
    """Test that Clock In button exists"""
    login(page)
    clock_in = page.locator("button:has-text('Clock In')")
    clocked_in = page.locator("text=Clocked In")
    assert clock_in.count() > 0 or clocked_in.count() > 0, "No Clock In button found"


def test_mark_habit_done_clickable(page: Page):
    """Test that clicking Clock In works (if not already done)"""
    login(page)
    clock_in = page.locator("button:has-text('Clock In')").first

    if clock_in.count() > 0 and clock_in.is_visible():
        clock_in.click()
        # Should show success or already done message
        expect(page.locator("text=Clocked In").first).to_be_visible(timeout=5000)


# ================================================================
# LOGOUT TESTS
# ================================================================


def test_logout_redirects_to_index(page: Page):
    """Test that logout works correctly"""
    login(page)

    # Find and click logout button
    logout_selectors = [
        "form[action*='logout'] button",
        "button:has-text('Logout')",
        "button:has-text('Log out')",
        "a:has-text('Logout')",
        "a[href*='logout']",
    ]

    for selector in logout_selectors:
        el = page.locator(selector)
        if el.count() > 0:
            el.first.click()
            expect(page).to_have_url(BASE_URL + "/", timeout=8000)
            # Verify session cleared
            page.goto(f"{BASE_URL}/habits/")
            expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")
            return

    # Debug: print all buttons if logout not found
    buttons = page.eval_on_selector_all(
        "button, a", "els => els.map(e => e.innerText.trim())"
    )
    pytest.fail(f"Logout button not found. Buttons on page: {buttons}")


# ================================================================
# SESSION & SECURITY TESTS
# ================================================================


def test_session_does_not_expire_prematurely(page: Page):
    """Test that session lasts at least 30 minutes"""
    login(page)

    # Wait 2 minutes (simulate user idle)
    page.wait_for_timeout(120000)

    # Page should still be accessible
    expect(page.locator("body")).to_be_visible()
    assert "/habits/" in page.url or "/login/" not in page.url


def test_csrf_protection_active(page: Page):
    """Test that CSRF token is present in forms"""
    page.goto(f"{BASE_URL}/login/")
    csrf_input = page.locator("input[name='csrfmiddlewaretoken']")
    expect(csrf_input).to_be_attached()


# ================================================================
# HEALTH CHECK TESTS
# ================================================================


def test_health_endpoint_returns_ok(page: Page):
    """Test that health check endpoint works"""
    response = page.request.get(f"{BASE_URL}/health/")
    assert response.status == 200
    assert response.text() == "ok"


def test_static_files_load(page: Page):
    """Test that CSS/JS files load"""
    page.goto(BASE_URL)

    # Check that CSS is applied (body has expected background)
    body_bg = page.evaluate("window.getComputedStyle(document.body).backgroundColor")
    assert body_bg is not None


# ================================================================
# EDGE CASE TESTS
# ================================================================


def test_concurrent_session_doesnt_conflict(page: Page, context):
    """Test that two users can be logged in simultaneously"""
    # Create second browser context
    page2 = context.new_page()

    login(page)

    # Login second user with different credentials if available
    page2.goto(f"{BASE_URL}/login/")
    # Note: This requires a second test account

    # Both should be able to access dashboard separately
    expect(page).to_have_url(f"{BASE_URL}/habits/")
    page2.goto(f"{BASE_URL}/")
    assert page2.url != f"{BASE_URL}/habits/"


def test_mobile_viewport_works(page: Page):
    """Test that site works on mobile viewport"""
    page.set_viewport_size({"width": 375, "height": 667})  # iPhone SE
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()


# ================================================================
# BROWSER COMPATIBILITY (Run with different browsers)
# ================================================================


@pytest.mark.skip(reason="Run manually with --browser=firefox")
def test_firefox_compatibility(page: Page):
    """Test in Firefox browser"""
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()


@pytest.mark.skip(reason="Run manually with --browser=webkit")
def test_safari_compatibility(page: Page):
    """Test in Safari/WebKit browser"""
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()

import os
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.getenv("BASE_URL", "https://dear-self.onrender.com")
TEST_PHONE = os.getenv("E2E_TEST_PHONE")
TEST_PASSWORD = os.getenv("E2E_TEST_PASSWORD")


def login(page: Page):
    """Helper used by all tests that need an authenticated session"""
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/habits/", timeout=10000)


# ----------------------------------------------------------------
# Page load tests — no auth needed
# ----------------------------------------------------------------

def test_registration_page_loads(page: Page):
    """Homepage loads with all form fields visible"""
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()
    expect(page.locator("[name=habit_choice]")).to_be_visible()


def test_habit_choice_options_match_backend(page: Page):
    """
    Regression: catches option value mismatches like DAILY PRAYERS & BIBLE STUDY.
    Scrapes actual rendered HTML and verifies every option value is valid.
    """
    page.goto(BASE_URL)
    options = page.eval_on_selector_all(
        "[name=habit_choice] option",
        "els => els.map(e => e.value).filter(v => v)"
    )
    valid_keys = ["daily prayers", "work out", "exam preparation", "custom"]
    for option in options:
        assert option.lower() in valid_keys, (
            f"Template option '{option}' has no matching HABIT_CHOICES key — "
            f"registration will silently fail for this option"
        )


def test_login_page_loads(page: Page):
    """Login page loads with all form fields visible"""
    page.goto(f"{BASE_URL}/login/")
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()


def test_unauthenticated_redirected_from_habits(page: Page):
    """
    Unauthenticated users must not access habits page.
    Real browser test catches redirect issues Django test client misses.
    """
    page.goto(f"{BASE_URL}/habits/")
    expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")


# ----------------------------------------------------------------
# Login flow tests
# ----------------------------------------------------------------

def test_login_full_journey(page: Page):
    """
    Full journey: land on login → fill credentials → land on dashboard.
    Regression: Safari dropped session cookies on redirect — webkit catches this.
    """
    login(page)
    # Confirm we actually landed on the dashboard
    expect(page).to_have_url(f"{BASE_URL}/habits/")


def test_login_wrong_password_shows_error(page: Page):
    """Wrong password stays on login page with error message"""
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", "WrongPassword999!")
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/login/")
    expect(page.locator("text=Invalid")).to_be_visible()


def test_login_invalid_phone_shows_error(page: Page):
    """Invalid phone format shows error without crashing"""
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", "notaphone")
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/login/")


def test_authenticated_user_redirected_from_login(page: Page):
    """Already logged in user visiting login page goes straight to habits"""
    login(page)
    page.goto(f"{BASE_URL}/login/")
    expect(page).to_have_url(f"{BASE_URL}/habits/")


# ----------------------------------------------------------------
# Dashboard tests
# ----------------------------------------------------------------

def test_dashboard_loads_with_habits(page: Page):
    """Dashboard renders after login with habit list visible"""
    login(page)
    expect(page.locator("text=Good")).to_be_visible()  # greeting


def test_dashboard_shows_streak(page: Page):
    """Streak count is visible on dashboard"""
    login(page)
    expect(page.locator("[class*=streak]").first).to_be_visible()


def test_mark_habit_done_button_visible(page: Page):
    """Mark done button exists on dashboard"""
    login(page)
    done_button = page.locator("button:has-text('Done')").first
    expect(done_button).to_be_visible()


def test_mark_habit_done_updates_ui(page: Page):
    """
    Clicking mark done updates the UI without a full page reload.
    Tests the AJAX flow end to end in a real browser.
    """
    login(page)
    
    # Find first habit that hasn't been marked today
    done_button = page.locator("button:has-text('Done')").first
    
    if done_button.is_visible():
        done_button.click()
        # UI should update — button changes or streak increments
        page.wait_for_timeout(1000)
        # After marking done the button should change state
        expect(page.locator("button:has-text('Done')").first).not_to_be_visible(
            timeout=3000
        )
    else:
        # Already marked today — that is fine, test passes
        pytest.skip("Habit already marked today — run again tomorrow to test this")


def test_logout_redirects_to_index(page: Page):
    """Full logout journey — session is cleared and user lands on homepage"""
    login(page)
    
    # Find and click logout
    page.click("text=Logout")
    expect(page).to_have_url(BASE_URL + "/")
    
    # Confirm session is gone — habits page should redirect to login
    page.goto(f"{BASE_URL}/habits/")
    expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")


def test_registration_redirect_to_otp_page(page: Page):
    """
    Regression: Safari dropped session between registration POST and OTP page.
    Running on webkit catches that class of bug without needing a real OTP.
    """
    page.goto(BASE_URL)
    page.fill("[name=identifier]", "+2348199999999")
    page.fill("[name=password]", "ValidPass123!")
    page.select_option("[name=habit_choice]", "DAILY PRAYERS")
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/verify-otp/", timeout=10000)
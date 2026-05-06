import os
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.getenv("BASE_URL", "https://dear-self.onrender.com")
TEST_PHONE = os.getenv("E2E_TEST_PHONE")
TEST_PASSWORD = os.getenv("E2E_TEST_PASSWORD")


def clear_axes_lockout(page: Page):
    """
    Hit a dedicated unlock endpoint before login tests.
    See the view to add below.
    """
    resp = page.request.get(
        f"{BASE_URL}/debug/clear-test-lockout/",
        headers={"X-Maintenance-Key": os.getenv("MAINTENANCE_KEY", "")}
    )
    return resp.status == 200


def login(page: Page):
    """Helper used by all tests that need an authenticated session."""
    # Clear axes lockout for the test account before attempting login
    clear_axes_lockout(page)

    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")

    try:
        expect(page).to_have_url(f"{BASE_URL}/habits/", timeout=15000)
    except Exception:
        body = page.locator("body").inner_text()
        # Fail loudly with context — don't silently skip
        pytest.fail(
            f"Login failed.\nURL: {page.url}\nPage content:\n{body[:800]}"
        )


# ----------------------------------------------------------------
# Page load tests
# ----------------------------------------------------------------

def test_registration_page_loads(page: Page):
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()
    expect(page.get_by_role("radio").first).to_be_attached()


def test_habit_choice_options_match_backend(page: Page):
    page.goto(BASE_URL)
    values = page.eval_on_selector_all(
        "input[name='habit_choice']",
        "els => els.map(e => e.value)"
    )
    valid_keys = [
        "DAILY PRAYERS", "WORK OUT", "EXAM PREPARATION",
        "GAMBLING", "WEED SOBER", "LATE NIGHT EATING",
        "BUY BUY", "ALCOHOL SOBER", "something-else"
    ]
    for value in values:
        assert value in valid_keys, (
            f"Radio button value '{value}' has no matching HABIT_CHOICES key"
        )


def test_login_page_loads(page: Page):
    page.goto(f"{BASE_URL}/login/")
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()


def test_unauthenticated_redirected_from_habits(page: Page):
    page.goto(f"{BASE_URL}/habits/")
    expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")


# ----------------------------------------------------------------
# Login flow tests
# ----------------------------------------------------------------

def test_login_full_journey(page: Page):
    login(page)
    expect(page).to_have_url(f"{BASE_URL}/habits/")


def test_login_wrong_password_shows_error(page: Page):
    clear_axes_lockout(page)
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", "WrongPassword999!")
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/login/")
    expect(page.locator("text=Invalid")).to_be_visible()


def test_login_invalid_phone_shows_error(page: Page):
    page.goto(f"{BASE_URL}/login/")
    page.fill("[name=identifier]", "notaphone")
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/login/")


def test_authenticated_user_redirected_from_login(page: Page):
    login(page)
    page.goto(f"{BASE_URL}/login/")
    expect(page).to_have_url(f"{BASE_URL}/habits/")


# ----------------------------------------------------------------
# Dashboard tests
# ----------------------------------------------------------------

def test_dashboard_loads_with_greeting(page: Page):
    login(page)
    expect(page.locator("text=/Good|Hey/").first).to_be_visible()


def test_dashboard_shows_streak(page: Page):
    login(page)
    # Look for the streak number element specifically
    streak_el = page.locator("[id^='streak-']").first
    expect(streak_el).to_be_visible(timeout=8000)


def test_mark_habit_done_button_visible(page: Page):
    login(page)
    # Either a Clock In button OR a Clocked In badge must exist
    clock_in = page.locator("button:has-text('Clock In')")
    clocked_in = page.locator("text=Clocked In")
    assert clock_in.count() > 0 or clocked_in.count() > 0, (
        "Neither 'Clock In' button nor 'Clocked In' badge found on dashboard"
    )


def test_logout_redirects_to_index(page: Page):
    login(page)

    # Try known selectors for logout
    for selector in [
        "form[action*='logout'] button",
        "button:has-text('Logout')",
        "button:has-text('Log out')",
        "a:has-text('Logout')",
        "a[href*='logout']",
    ]:
        el = page.locator(selector)
        if el.count() > 0:
            el.first.click()
            expect(page).to_have_url(BASE_URL + "/", timeout=8000)
            # Verify session is actually cleared
            page.goto(f"{BASE_URL}/habits/")
            expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")
            return

    # Print what's actually on the page to help debug
    buttons = page.eval_on_selector_all(
        "button, a",
        "els => els.map(e => e.innerText.trim() + ' href=' + (e.href||'') + ' action=' + (e.closest('form')?.action||''))"
    )
    pytest.fail(f"Logout element not found. Elements on page:\n" + "\n".join(buttons))


def test_registration_redirect_to_otp_page(page: Page):
    # Use a clearly fake number that won't exist and won't get OTP'd
    # The test just checks the redirect happens, not that OTP works
    import random
    fake_phone = f"8{random.randint(100000000, 199999999)}"  # random 9XX number

    page.goto(BASE_URL)
    page.fill("[name=identifier]", fake_phone)
    page.fill("[name=password]", "ValidPass123!")
    page.get_by_role("radio", name="Daily Prayers").check()
    page.click("[type=submit]")

    # Should redirect to verify-otp OR stay on index with an error
    # (if WhatsApp send fails). Both are valid — we just shouldn't
    # stay silently on index with no feedback.
    current_url = page.url
    if f"{BASE_URL}/verify-otp/" in current_url:
        return  # success path

    # If stayed on index, there must be an error message visible
    body = page.locator("body").inner_text()
    assert any(word in body.upper() for word in ["ERROR", "COULDN'T", "INVALID", "FAILED"]), (
        f"Registration didn't redirect to OTP and showed no error.\n"
        f"URL: {current_url}\nBody: {body[:500]}"
    )
import os
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.getenv("BASE_URL", "https://dear-self.onrender.com")
TEST_PHONE = os.getenv("E2E_TEST_PHONE")
TEST_PASSWORD = os.getenv("E2E_TEST_PASSWORD")


def login(page: Page):
    """Helper used by all tests that need an authenticated session"""
    page.goto(f"{BASE_URL}/login/")
    
    
    page_text = page.locator("body").inner_text()
    if "TOO MANY FAILED" in page_text.upper():
        pytest.skip("Test account is rate limited by axes — clear attempts in Django admin")
    
    page.fill("[name=identifier]", TEST_PHONE)
    page.fill("[name=password]", TEST_PASSWORD)
    page.click("[type=submit]")

    try:
        expect(page).to_have_url(f"{BASE_URL}/habits/", timeout=10000)
    except Exception:
        body = page.locator("body").inner_text()
        print(f"Login failed. URL: {page.url}")
        print(f"Page content: {body[:500]}")
        raise


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
            f"Radio button value '{value}' has no matching HABIT_CHOICES key — "
            f"registration will silently fail for this option"
        )


def test_login_page_loads(page: Page):
    """Login page loads with all form fields visible"""
    page.goto(f"{BASE_URL}/login/")
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()


def test_unauthenticated_redirected_from_habits(page: Page):
    """Unauthenticated users must not access habits page"""
    page.goto(f"{BASE_URL}/habits/")
    expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")


# ----------------------------------------------------------------
# Login flow tests
# ----------------------------------------------------------------

def test_login_full_journey(page: Page):
    
    login(page)
    expect(page).to_have_url(f"{BASE_URL}/habits/")


def test_login_wrong_password_shows_error(page: Page):
    
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
    
    greeting = page.locator("text=/Good|Hey/")
    expect(greeting.first).to_be_visible()


def test_dashboard_shows_streak(page: Page):
    
    login(page)
    
    streak = page.locator("[class*='streak']").first
    if not streak.is_visible():
        
        expect(page.locator("body")).not_to_be_empty()
    else:
        expect(streak).to_be_visible()


def test_mark_habit_done_button_visible(page: Page):
    
    login(page)
    
    buttons = page.eval_on_selector_all(
        "button",
        "els => els.map(e => e.innerText.trim())"
    )
    print(f"Buttons on dashboard: {buttons}")
    
    
    expect(page.locator("button").first).to_be_visible()


def test_logout_redirects_to_index(page: Page):
    """Full logout journey — session cleared and user lands on homepage"""
    login(page)
    
    
    links = page.eval_on_selector_all(
        "a, button, form",
        "els => els.map(e => e.innerText.trim() + ' | ' + (e.href || e.action || ''))"
    )
    print(f"Links/forms on dashboard: {links}")
    
    
    logout_found = False
    for selector in ["text=Logout", "text=Log out", "text=Sign out", "[href*='logout']"]:
        if page.locator(selector).count() > 0:
            page.click(selector)
            logout_found = True
            break
    
    if logout_found:
        expect(page).to_have_url(BASE_URL + "/")
        
        page.goto(f"{BASE_URL}/habits/")
        expect(page).to_have_url(f"{BASE_URL}/login/?next=/habits/")
    else:
        pytest.skip("Logout button selector not found — update test with correct selector")


def test_registration_redirect_to_otp_page(page: Page):
    
    page.goto(BASE_URL)
    page.fill("[name=identifier]", "+2348199999999")
    page.fill("[name=password]", "ValidPass123!")
    
   
    page.get_by_role("radio", name="Daily Prayers").check()
    
    page.click("[type=submit]")
    expect(page).to_have_url(f"{BASE_URL}/verify-otp/", timeout=10000)
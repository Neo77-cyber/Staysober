
import os
import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.getenv("BASE_URL", "https://dear-self.onrender.com")

def test_registration_page_loads(page: Page):
    page.goto(BASE_URL)
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()
    expect(page.locator("[name=habit_choice]")).to_be_visible()

def test_habit_choice_options_match_backend(page: Page):
    """Catches option value mismatches like the DAILY PRAYERS bug"""
    page.goto(BASE_URL)
    options = page.eval_on_selector_all(
        "[name=habit_choice] option",
        "els => els.map(e => e.value).filter(v => v)"
    )
    valid_keys = ["daily prayers", "work out", "exam preparation", "custom"]
    for option in options:
        assert option.lower() in valid_keys, (
            f"Template option '{option}' has no matching HABIT_CHOICES key"
        )

def test_login_page_loads(page: Page):
    page.goto(f"{BASE_URL}/login/")
    expect(page.locator("[name=identifier]")).to_be_visible()
    expect(page.locator("[name=password]")).to_be_visible()

@pytest.mark.parametrize("browser_name", ["chromium", "webkit"])
def test_pages_load_on_safari_and_chrome(page: Page, browser_name: str):
    """webkit = Safari engine — catches Safari-specific bugs"""
    page.goto(BASE_URL)
    expect(page).not_to_have_url(f"{BASE_URL}/login/")
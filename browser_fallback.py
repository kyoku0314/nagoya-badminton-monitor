"""Fallback query using a real Chromium browser, without logging in or booking."""
from playwright.sync_api import sync_playwright

HOME = "https://www.net.city.nagoya.jp/sporec/index.html"
SEARCH = "https://www.net.city.nagoya.jp/cgi-bin/sp/sps04001"

def query_with_browser(day, fields):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo",
                                          user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
            page = context.new_page()
            page.set_default_timeout(12000)
            page.goto(HOME, wait_until="domcontentloaded", timeout=15000)
            link = page.locator('a[href*="sps04001"]')
            if link.count():
                link.first.click(timeout=15000)
            else:
                # Some homepage links may be JavaScript-driven; use the
                # documented search URL after visiting the homepage.
                page.goto(SEARCH, wait_until="domcontentloaded", timeout=15000)
            page.locator('form[name="user"]').wait_for(timeout=12000)
            # Use real select interactions so dependent JavaScript receives
            # input/change events, as it would during a manual search.
            for name in ("syumoku", "month", "day", "joken", "kyoyo1", "kyoyo2", "chiiki"):
                value = fields.get(name)
                if value is None:
                    continue
                control = page.locator(f'form[name="user"] select[name="{name}"]')
                if control.count():
                    control.first.select_option(value=str(value))
                else:
                    radios = page.locator(f'form[name="user"] input[type="radio"][name="{name}"][value="{value}"]')
                    if radios.count():
                        radios.first.check()
                    else:
                        page.locator(f'form[name="user"] [name="{name}"]').first.evaluate(
                            "(el, value) => {el.value = value; el.dispatchEvent(new Event('change', {bubbles: true}));}",
                            str(value))
            submit = page.locator('form[name="user"] input[name="button"]')
            if submit.count():
                submit.first.click(timeout=12000)
            else:
                page.evaluate("""() => document.forms['user'].submit()""")
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(800)
            return page.content()
        finally:
            browser.close()

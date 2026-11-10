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
                link.first.click(wait_until="domcontentloaded", timeout=15000)
            else:
                # Some homepage links may be JavaScript-driven; use the
                # documented search URL after visiting the homepage.
                page.goto(SEARCH, wait_until="domcontentloaded", timeout=15000)
            page.locator('form[name="user"]').wait_for(timeout=12000)
            # Populate existing form controls; dispatch change events so the
            # site's own JavaScript can update dependent selections.
            page.evaluate("""(values) => {
                const form = document.forms['user'];
                for (const [name, value] of Object.entries(values)) {
                    const elements = Array.from(form.elements).filter(e => e.name === name);
                    for (const element of elements) {
                        if (element.type === 'radio' || element.type === 'checkbox') {
                            element.checked = element.value === value;
                        } else if (element.type !== 'submit' && element.type !== 'button') {
                            element.value = value;
                        }
                        element.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }
            }""", fields)
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

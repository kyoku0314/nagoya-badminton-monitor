"""Fallback query using a real Chromium browser, without logging in or booking."""
from playwright.sync_api import sync_playwright

HOME = "https://www.net.city.nagoya.jp/sporec/index.html"
SEARCH = "https://www.net.city.nagoya.jp/cgi-bin/sp/sps04001"

def query_with_browser(day, fields):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = None
        try:
            context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo",
                                          user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
            page = context.new_page()
            page.set_default_timeout(12000)
            page.goto(HOME, wait_until="domcontentloaded", timeout=15000)
            # Prefer the actual menu button visible on the homepage.
            link = page.get_by_role("link", name="利用日ごとの検索・予約")
            if not link.count():
                link = page.locator('a:has(img[alt*="利用日ごと"]), a[href*="sps04001"]')
            if link.count():
                link.first.click(timeout=15000)
            else:
                print("Homepage button not found; opening known search URL", flush=True)
                page.goto(SEARCH, wait_until="domcontentloaded", timeout=15000)
            page.locator('form[name="user"]').wait_for(timeout=12000)
            # Change the sport first; the site's JS may repopulate supply options.
            for name in ("syumoku", "month", "day", "joken", "kyoyo1", "kyoyo2", "chiiki"):
                value = fields.get(name)
                if value is None:
                    continue
                control = page.locator(f'form[name="user"] [name="{name}"]')
                if not control.count():
                    if name in ("kyoyo2",):
                        continue
                    raise RuntimeError(f"Required control missing: {name}")
                element = control.first
                tag = element.evaluate("(el) => el.tagName.toLowerCase()")
                kind = element.get_attribute("type")
                if tag == "select":
                    element.select_option(value=str(value), timeout=5000)
                elif kind in ("radio", "checkbox"):
                    option = page.locator(f'form[name="user"] input[name="{name}"][value="{value}"]')
                    if not option.count():
                        raise RuntimeError(f"Option missing: {name}={value}")
                    option.first.check(timeout=5000)
                else:
                    element.fill(str(value), timeout=5000)
            # Confirm actual chosen values before submitting.
            selected = page.evaluate("""() => {
                const f = document.forms['user'];
                return Object.fromEntries(['syumoku','month','day','kyoyo1','chiiki'].map(n =>
                    [n, f.elements[n]?.value ?? null]));
            }""")
            print(f"Browser form selections: {selected}", flush=True)
            submit = page.locator('form[name="user"] input[name="button"]')
            if submit.count():
                submit.first.click(timeout=12000)
            else:
                page.evaluate("""() => document.forms['user'].submit()""")
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(800)
            return page.content()
        except Exception:
            if page is not None:
                try:
                    page.screenshot(path="browser_failure.png", full_page=True, timeout=5000)
                    from pathlib import Path
                    Path("browser_failure.html").write_text(page.content(), encoding="utf-8")
                except Exception as capture_error:
                    print(f"Could not capture browser failure: {capture_error}", flush=True)
            raise
        finally:
            browser.close()

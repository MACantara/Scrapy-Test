from playwright.sync_api import sync_playwright
import sys

if len(sys.argv) < 2:
    print('Usage: debug_playwright_fetch.py <url> [output.html]')
    sys.exit(1)

url = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else 'rendered.html'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    print('Navigating', url)
    page.goto(url, timeout=30000)
    # wait a bit to allow XHRs to complete
    page.wait_for_timeout(3000)
    content = page.content()
    with open(out, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Saved to', out)
    print('\n--- snippet ---\n')
    print(content[:2000])
    browser.close()

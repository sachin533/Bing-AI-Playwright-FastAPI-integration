
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto("https://www.bing.com/chat", wait_until="domcontentloaded")

    print("Bing AI page opened:", page.title())
    print("URL:", page.url)

    input("If login is required, log in manually. Press Enter when ready...")

    browser.close()

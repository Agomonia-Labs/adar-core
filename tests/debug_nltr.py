"""
Run this LOCALLY to see what NLTR renders:
  python nltr_debug.py

It will save the rendered HTML to /tmp/nltr_debug.html
so you can inspect what Playwright actually sees.
"""
import asyncio

async def debug():
    from playwright.async_api import async_playwright

    url = "https://rabindra-rachanabali.nltr.org/node/6624?r=আ"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page    = await browser.new_page()

        print(f"Fetching: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        html = await page.content()
        print(f"HTML length: {len(html)}")

        # Save for inspection
        with open("/tmp/nltr_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved to /tmp/nltr_debug.html")

        # Show all links
        links = await page.query_selector_all("a[href]")
        print(f"\nTotal <a> tags: {len(links)}")
        print("First 30 hrefs:")
        for i, a in enumerate(links[:30]):
            href  = await a.get_attribute("href")
            text  = (await a.inner_text()).strip()[:40]
            print(f"  [{i}] {text!r:45} → {href}")

        # Show page text preview
        body_text = await page.inner_text("body")
        print(f"\nPage text preview (first 500 chars):\n{body_text[:500]}")

        await browser.close()

asyncio.run(debug())
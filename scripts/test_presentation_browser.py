"""Verify the browser deck's navigation, local media, and 16:9 print layout."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/presentation'
BOUNDS = """slides => slides.map(s => {
  const box=s.getBoundingClientRect();
  const children=Array.from(s.querySelectorAll('*')).map(c=>c.getBoundingClientRect());
  return {height:box.height, scrollHeight:s.scrollHeight,
    contentBottom:Math.max(...children.map(c=>c.bottom))-box.top,
    contentLeft:Math.min(...children.map(c=>c.left))-box.left,
    contentRight:Math.max(...children.map(c=>c.right))-box.left};
})"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'slide_count': 6, 'checks': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto((ROOT / 'docs/presentation.html').as_uri())
        assert page.locator('.slide').count() == 6
        page.wait_for_function('Array.from(document.images).every(i=>i.complete && i.naturalWidth>0)')
        result['checks'].append('All six slides and local screenshot media load')
        result['desktop_bounds'] = page.locator('.slide').evaluate_all(BOUNDS)
        for index, slide in enumerate(page.locator('.slide').all()):
            box = result['desktop_bounds'][index]
            assert box['height'] == 720, box
            assert box['contentBottom'] <= 680, box
            assert box['contentLeft'] >= 0 and box['contentRight'] <= 1280, box
            slide.screenshot(path=str(OUT / ('screen-slide-%02d.png' % (index + 1))))
        result['checks'].append('All desktop slides fit a 1280 by 720 canvas')
        for key, expected in [('Home', 1), ('ArrowRight', 2), ('PageDown', 3),
                              ('ArrowLeft', 2), ('End', 6), ('PageUp', 5), ('Home', 1)]:
            page.keyboard.press(key)
            page.wait_for_timeout(900)
            assert page.locator('#position').inner_text().startswith(str(expected) + ' / 6'), key
        page.locator('#next').click()
        page.wait_for_timeout(900)
        assert page.locator('#position').inner_text().startswith('2 / 6')
        page.locator('#previous').click()
        page.wait_for_timeout(900)
        assert page.locator('#position').inner_text().startswith('1 / 6')
        result['checks'].append('Arrow, Page, Home, End, Previous and Next navigation works')
        page.emulate_media(media='print')
        assert page.locator('footer').is_hidden()
        result['print_bounds'] = page.locator('.slide').evaluate_all(BOUNDS)
        for index, slide in enumerate(page.locator('.slide').all()):
            box = result['print_bounds'][index]
            assert box['height'] == 720 and box['scrollHeight'] == 720, box
            assert box['contentBottom'] <= 680, box
            assert box['contentLeft'] >= 0 and box['contentRight'] <= 1280, box
            assert slide.evaluate("s=>getComputedStyle(s).breakAfter") == 'page'
            slide.screenshot(path=str(OUT / ('print-slide-%02d.png' % (index + 1))))
        result['checks'].append('Print media has six bounded 16:9 slides with explicit page breaks')
        page.emulate_media(media='screen')
        page.set_viewport_size({'width': 430, 'height': 932})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Narrow-screen horizontal overflow'
        page.locator('.slide').nth(2).screenshot(path=str(OUT / 'narrow-control-slide.png'))
        result['checks'].append('430 px narrow view has no horizontal overflow')
        assert not errors, errors
        result['page_errors'] = 0
        result['browser'] = browser.version
        browser.close()
    (OUT / 'validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

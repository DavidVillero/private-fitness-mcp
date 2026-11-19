"""Render the actual MCP resource in Chromium using a synthetic host and data only."""

import importlib.util
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    spec = importlib.util.spec_from_file_location(
        "dashboard_fixture", ROOT / "tests/test_dashboard.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    overlay = fixture.m.Dashboard(fixture.Original())
    output = {"dashboard": overlay.snapshot({"date": "2020-01-01", "days": 7})}
    output["dashboard"]["corrections"] = [
        {
            "title": "<img src=x onerror=window.injected=true>",
            "content": "<script>window.injected=true</script>",
        }
    ]
    html = overlay.handle(fixture.msg("resources/read", {"uri": fixture.m.URI}))[
        "result"
    ]["contents"][0]["text"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width in [390, 1280]:
                for delayed in [False, True]:
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.evaluate(
                        """({output, delayed}) => {
                        window.syntheticOutput = output;
                        window.calls = [];
                        window.openai = {
                            toolOutput: delayed ? null : output,
                            callTool: async (name, args) => {
                                window.calls.push({name, args});
                                return {structuredContent: output};
                            }
                        };
                    }""",
                        {"output": output, "delayed": delayed},
                    )
                    page.set_content(html)
                    page.locator("#status").filter(has_text="Retrieved").wait_for()
                    for view in [
                        "nutrition",
                        "workouts",
                        "corrections",
                        "trends",
                        "today",
                    ]:
                        page.locator(f'[data-view="{view}"]').click()
                        assert page.locator("#view").inner_text().strip()
                    page.locator("#refresh").click()
                    page.locator("#status").filter(has_text="Retrieved").wait_for()
                    assert page.evaluate(
                        "window.calls.every(call => call.name === 'get_fitness_hq_dashboard')"
                    )
                    page.evaluate("""() => window.dispatchEvent(new CustomEvent('openai:set_globals', {
                        detail: {globals: {toolOutput: window.syntheticOutput}}
                    }))""")
                    assert "Unknown" in page.locator("#view").inner_text()
                    assert not page.evaluate("Boolean(window.injected)")
                    assert not errors, errors
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    page.close()
            print(
                "Chromium: all five views, initial/delayed host results, refresh and mobile/desktop layouts passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()

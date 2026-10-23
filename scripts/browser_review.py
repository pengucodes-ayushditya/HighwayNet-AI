"""Local browser review with optional Playwright dependency.

Install a compatible Chromium engine with Playwright first. Visits localhost only.
Captures public study data; no authenticated browser or account is involved.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/screenshots"
OUT.mkdir(exist_ok=True)
report = {"browser": "Chromium headless shell via Playwright", "visits": "localhost only"}
with (ROOT / "results/browser_server.txt").open("w") as server_log:
    server = subprocess.Popen(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "streamlit",
            "run",
            str(ROOT / "app.py"),
            "--server.headless=true",
            "--server.port=8529",
            "--server.address=127.0.0.1",
        ],
        cwd=ROOT,
        stdout=server_log,
        stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8529/_stcore/health", timeout=1
                ) as response:
                    assert response.status == 200
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Local Streamlit health endpoint did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1500, "height": 1400}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console", lambda message: print("BROWSER", message.type, message.text, flush=True)
            )
            page.on(
                "requestfailed",
                lambda request: print("FAILED", request.url, request.failure, flush=True),
            )
            page.goto("http://127.0.0.1:8529", wait_until="domcontentloaded")
            try:
                page.get_by_role("button", name="Ranking CSV", exact=True).wait_for(
                    state="visible", timeout=60000
                )
            except Exception:
                print("BODY", page.locator("body").inner_text(), flush=True)
                page.screenshot(path=str(OUT / "diagnostic.png"), full_page=True)
                raise
            page.get_by_role("tab", name="Intervention lab", exact=True).click()
            page.get_by_role("button", name="Summary CSV", exact=True).wait_for(
                state="visible", timeout=60000
            )
            page.get_by_role("tab", name="Network & routes", exact=True).click()
            page.get_by_text("REAL ROAD SNAPSHOT", exact=False).wait_for(state="visible")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(OUT / "network_desktop.png"), full_page=True)
            report["real_study_loaded"] = True
            page.get_by_role("tab", name="Intervention lab", exact=True).click()
            page.wait_for_timeout(700)
            page.screenshot(path=str(OUT / "intervention_controls.png"), full_page=True)
            page.locator('[data-testid="stMain"]').evaluate("(e)=>e.scrollTop=1100")
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / "intervention_desktop.png"), full_page=True)
            page.get_by_role("tab", name="Network & routes", exact=True).click()
            page.get_by_text("Select a road on the map", exact=True).click()
            page.wait_for_function(
                """() => {
                const g=document.querySelector('[data-testid="stPlotlyChart"] .js-plotly-plot');
                return g && g.data && g.data.some(t=>t.name==='Pick a road segment');
            }""",
                timeout=60000,
            )
            page.locator('[data-testid="stPlotlyChart"]').first.scroll_into_view_if_needed()
            position = page.evaluate("""() => {
                const g=document.querySelector('[data-testid="stPlotlyChart"] .js-plotly-plot');
                const t=g.data.find(t=>t.name==='Pick a road segment');
                const b=g.getBoundingClientRect();
                for (let i=0;i<t.x.length;i++) {
                    const x=b.left+g._fullLayout.xaxis._offset+g._fullLayout.xaxis.l2p(t.x[i]);
                    const y=b.top+g._fullLayout.yaxis._offset+g._fullLayout.yaxis.l2p(t.y[i]);
                    if (x>320 && x<innerWidth-30 && y>100 && y<innerHeight-30) return {x,y};
                }
                throw new Error('No visible road marker');
            }""")
            page.mouse.move(position["x"] - 6, position["y"] - 6)
            page.mouse.down()
            page.mouse.move(position["x"] + 6, position["y"] + 6, steps=10)
            page.mouse.up()
            button = page.get_by_role(
                "button", name="Use selected segment in intervention A", exact=True
            )
            button.wait_for(state="visible", timeout=30000)
            button.click()
            page.get_by_role("tab", name="Intervention lab", exact=True).click()
            page.get_by_text("1 segments ·", exact=False).wait_for(state="visible", timeout=60000)
            report["map_box_selection_succeeded"] = True
            page.get_by_role("tab", name="Network & routes", exact=True).click()
            page.get_by_text("Select a road on the map", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(800)
            collapse = page.locator('[data-testid="stSidebarCollapseButton"] button')
            if collapse.count() and collapse.is_visible():
                collapse.click()
            page.locator('[data-testid="stMain"]').evaluate("(e)=>e.scrollTop=0")
            # Streamlit hides the sidebar at this width. Internal data tables may scroll.
            report["mobile_root_width"] = page.evaluate("document.documentElement.scrollWidth")
            report["mobile_viewport_width"] = 390
            page.screenshot(path=str(OUT / "network_mobile.png"), full_page=True)
            report["page_errors"] = errors
            assert not errors, errors
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
        (ROOT / "results/browser_review.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.salonboard_credentials_service import SalonboardCredentialsService


LOGIN_URL = "https://salonboard.com/login/"
DEVICE_ID = "e7810a4c-8419-42a6-b8fa-2e96a98a9465"
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
USER_DATA_DIR = Path.home() / ".ai_secretary" / "salonboard_prefill_edge_data"
STATUS_PATH = Path("tmp_salonboard_prefill_status.json")


async def main() -> None:
    STATUS_PATH.write_text(
        json.dumps({"status": "starting", "time": datetime.now().isoformat()}),
        encoding="utf-8",
    )
    creds = await SalonboardCredentialsService().get_decrypted_for_posting(DEVICE_ID)
    if not creds:
        STATUS_PATH.write_text(
            json.dumps({"status": "error", "message": "credentials not found"}),
            encoding="utf-8",
        )
        return

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=False,
            executable_path=EDGE_EXE if os.path.exists(EDGE_EXE) else None,
            locale="ja-JP",
            viewport={"width": 1280, "height": 1000},
            args=["--no-first-run", "--new-window"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1500)

        await page.locator('input[type="text"]').first.fill(creds["login_id"])
        await page.locator('input[type="password"]').first.fill(creds["password"])

        STATUS_PATH.write_text(
            json.dumps(
                {
                    "status": "ready",
                    "message": "login fields filled; login button not clicked",
                    "time": datetime.now().isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        while True:
            await page.wait_for_timeout(60_000)


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.salonboard_browser_session import (
    get_or_create_page,
    launch_salonboard_context,
    prefill_login_form,
)
from app.services.salonboard_credentials_service import SalonboardCredentialsService


DEVICE_ID = "e7810a4c-8419-42a6-b8fa-2e96a98a9465"
USER_DATA_DIR = Path.home() / ".ai_secretary" / "salonboard_prefill_chrome_data"
STATUS_PATH = Path("tmp_salonboard_prefill_status.json")

STATUS_MESSAGES = {
    "prefilled": ("ready", "login fields filled; login button not clicked"),
    "already_logged_in": ("ready", "already logged in; nothing filled"),
    "login_form_not_found": ("error", "login form not found"),
}


def write_status(status: str, message: str | None = None) -> None:
    payload = {"status": status, "time": datetime.now().isoformat()}
    if message:
        payload["message"] = message
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


async def main() -> None:
    write_status("starting")
    creds = await SalonboardCredentialsService().get_decrypted_for_posting(DEVICE_ID)
    if not creds:
        write_status("error", "credentials not found")
        return

    async with async_playwright() as p:
        async with launch_salonboard_context(p, user_data_dir=USER_DATA_DIR) as context:
            page = await get_or_create_page(context)
            await page.wait_for_load_state("domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
            result = await prefill_login_form(page, creds)
            write_status(*STATUS_MESSAGES[result])

            while True:
                await page.wait_for_timeout(60_000)


if __name__ == "__main__":
    asyncio.run(main())

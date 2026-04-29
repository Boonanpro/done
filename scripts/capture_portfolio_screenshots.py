"""
Capture screenshots of client portfolio sites and Dan's own frontend.
Uses Playwright sync API + subprocess for dev servers.
"""
import subprocess
import time
import os
import signal
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("D:/dan-workspace/hp-projects/dan/public")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PROJECTS = [
    {
        "name": "yoshikawa",
        "dir": "D:/dan-workspace/hp-projects/yoshikawa-next",
        "port": 3002,
        "output": "portfolio-yoshikawa.png",
    },
    {
        "name": "gojo",
        "dir": "D:/dan-workspace/hp-projects/gojo-next",
        "port": 3003,
        "output": "portfolio-gojo.png",
    },
    {
        "name": "bird-stc",
        "dir": "D:/dan-workspace/hp-projects/bird-stc-next",
        "port": 3004,
        "output": "portfolio-bird-stc.png",
    },
]

VIEWPORT = {"width": 1280, "height": 720}
STARTUP_TIMEOUT = 30  # seconds


def wait_for_server(port: int, timeout: int = STARTUP_TIMEOUT) -> bool:
    """Poll until the dev server responds with 200 or timeout."""
    url = f"http://localhost:{port}"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=3, allow_redirects=True)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def kill_process_tree(proc: subprocess.Popen):
    """Kill the process and its children on Windows."""
    try:
        # Use taskkill /T to kill the tree
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=10,
        )
    except Exception as e:
        print(f"  Warning: taskkill failed: {e}")
    try:
        proc.kill()
    except Exception:
        pass


def take_screenshot(page, url: str, output_path: Path, wait_ms: int = 3000) -> bool:
    """Navigate to URL and take a screenshot."""
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(wait_ms)  # let animations/images settle
        page.screenshot(path=str(output_path), full_page=False)
        print(f"  Saved: {output_path}")
        return True
    except Exception as e:
        print(f"  Screenshot failed: {e}")
        return False


def main():
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()

        # --- Client projects (start dev server, screenshot, stop) ---
        for proj in PROJECTS:
            print(f"\n=== {proj['name']} ===")
            print(f"  Starting dev server on port {proj['port']}...")

            env = os.environ.copy()
            env["PORT"] = str(proj["port"])

            proc = subprocess.Popen(
                f"npm run dev -- -p {proj['port']}",
                shell=True,
                cwd=proj["dir"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            try:
                if wait_for_server(proj["port"]):
                    print(f"  Server ready on port {proj['port']}")
                    output_path = OUTPUT_DIR / proj["output"]
                    ok = take_screenshot(
                        page,
                        f"http://localhost:{proj['port']}",
                        output_path,
                    )
                    results[proj["name"]] = "OK" if ok else "screenshot failed"
                else:
                    print(f"  Server failed to start within {STARTUP_TIMEOUT}s")
                    results[proj["name"]] = "server timeout"
            except Exception as e:
                print(f"  Error: {e}")
                results[proj["name"]] = f"error: {e}"
            finally:
                print(f"  Stopping server (PID {proc.pid})...")
                kill_process_tree(proc)
                # Also kill any leftover node on that port
                subprocess.run(
                    f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{proj["port"]} ^| findstr LISTENING\') do taskkill /F /PID %a',
                    shell=True,
                    capture_output=True,
                    timeout=10,
                )
                time.sleep(1)

        # --- Dan's frontend (localhost:3000) ---
        print("\n=== Dan UI (localhost:3000) ===")
        try:
            r = requests.get("http://localhost:3000", timeout=5, allow_redirects=True)
            if r.status_code < 500:
                ok = take_screenshot(
                    page,
                    "http://localhost:3000",
                    OUTPUT_DIR / "dan-ui.png",
                )
                results["dan-ui"] = "OK" if ok else "screenshot failed"
            else:
                print("  localhost:3000 returned error")
                results["dan-ui"] = f"HTTP {r.status_code}"
        except Exception as e:
            print(f"  localhost:3000 not available: {e}")
            results["dan-ui"] = "not running"

        # --- Dan's chat interface ---
        print("\n=== Dan Chat (localhost:3000/chat) ===")
        try:
            r = requests.get("http://localhost:3000/chat", timeout=5, allow_redirects=True)
            if r.status_code < 500:
                ok = take_screenshot(
                    page,
                    "http://localhost:3000/chat",
                    OUTPUT_DIR / "dan-chat.png",
                )
                results["dan-chat"] = "OK" if ok else "screenshot failed"
            else:
                print(f"  /chat returned HTTP {r.status_code}")
                results["dan-chat"] = f"HTTP {r.status_code}"
        except Exception as e:
            print(f"  /chat not available: {e}")
            results["dan-chat"] = "not available"

        browser.close()

    # --- Summary ---
    print("\n" + "=" * 50)
    print("RESULTS:")
    for name, status in results.items():
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()

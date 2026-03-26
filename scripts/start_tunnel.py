"""
Cloudflare Tunnel auto-start script.
Starts a quick tunnel, extracts the URL, and updates Vercel env + CORS config.

Usage: python scripts/start_tunnel.py
"""
import subprocess
import re
import time
import os
import sys

CLOUDFLARED = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "WinGet", "Packages",
    "Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "cloudflared.exe"
)
BACKEND_PORT = 8000
VERCEL_PROJECT_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
TUNNEL_URL_FILE = os.path.join(os.path.dirname(__file__), "..", ".tunnel_url")
VERCEL_CMD = os.path.join(os.environ.get("APPDATA", ""), "npm", "vercel.cmd")


def kill_existing_tunnels():
    """Kill any existing cloudflared processes."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "cloudflared.exe"],
            capture_output=True, timeout=10
        )
    except Exception:
        pass


def start_tunnel() -> str:
    """Start cloudflared tunnel and return the public URL."""
    print("[tunnel] Starting Cloudflare Tunnel...")
    proc = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", f"http://127.0.0.1:{BACKEND_PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    url = None
    start_time = time.time()
    for line in proc.stdout:
        print(f"  {line.rstrip()}")
        match = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
        if match:
            url = match.group(1)
            break
        if time.time() - start_time > 30:
            break

    if not url:
        print("[tunnel] ERROR: Could not get tunnel URL")
        proc.kill()
        sys.exit(1)

    print(f"[tunnel] Tunnel URL: {url}")

    # Save URL to file for other scripts
    with open(TUNNEL_URL_FILE, "w") as f:
        f.write(url)

    return url


def update_env_file(tunnel_url: str):
    """Update .env file with new tunnel URL for CORS."""
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Update or add ALLOWED_ORIGINS and FRONTEND_URL
    vercel_url = get_vercel_url()
    new_origins = vercel_url if vercel_url else ""

    updated = {"ALLOWED_ORIGINS": False, "FRONTEND_URL": False}
    new_lines = []
    for line in lines:
        if line.startswith("ALLOWED_ORIGINS="):
            new_lines.append(f"ALLOWED_ORIGINS={new_origins}\n")
            updated["ALLOWED_ORIGINS"] = True
        elif line.startswith("FRONTEND_URL="):
            new_lines.append(f"FRONTEND_URL={vercel_url}\n")
            updated["FRONTEND_URL"] = True
        else:
            new_lines.append(line)

    if not updated["ALLOWED_ORIGINS"]:
        new_lines.append(f"ALLOWED_ORIGINS={new_origins}\n")
    if not updated["FRONTEND_URL"] and vercel_url:
        new_lines.append(f"FRONTEND_URL={vercel_url}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"[tunnel] Updated .env: ALLOWED_ORIGINS={new_origins}")


def get_vercel_url() -> str:
    """Get Vercel production URL."""
    try:
        result = subprocess.run(
            [VERCEL_CMD, "project", "ls"],
            capture_output=True, text=True, timeout=15,
            cwd=VERCEL_PROJECT_DIR, encoding="utf-8", errors="replace"
        )
        for line in result.stdout.splitlines():
            if "frontend" in line:
                match = re.search(r"(https://[^\s]+\.vercel\.app)", line)
                if match:
                    return match.group(1)
    except Exception as e:
        print(f"[tunnel] Warning: Could not get Vercel URL: {e}")
    return "https://frontend-liard-rho-29.vercel.app"


def update_vercel_env(tunnel_url: str):
    """Update Vercel env var and trigger redeploy."""
    print(f"[tunnel] Updating Vercel NEXT_PUBLIC_API_URL to {tunnel_url}")

    # Remove old env var (ignore errors)
    subprocess.run(
        [VERCEL_CMD, "env", "rm", "NEXT_PUBLIC_API_URL", "production", "--yes"],
        capture_output=True, timeout=15,
        cwd=VERCEL_PROJECT_DIR, encoding="utf-8", errors="replace"
    )

    # Add new one
    result = subprocess.run(
        [VERCEL_CMD, "env", "add", "NEXT_PUBLIC_API_URL", "production"],
        input=tunnel_url,
        capture_output=True, text=True, timeout=15,
        cwd=VERCEL_PROJECT_DIR, encoding="utf-8", errors="replace"
    )
    if result.returncode == 0:
        print("[tunnel] Vercel env updated")
    else:
        print(f"[tunnel] Warning: Vercel env update failed: {result.stderr}")

    # Trigger redeploy
    print("[tunnel] Triggering Vercel redeploy...")
    result = subprocess.run(
        [VERCEL_CMD, "deploy", "--prod", "--yes"],
        capture_output=True, text=True, timeout=300,
        cwd=VERCEL_PROJECT_DIR, encoding="utf-8", errors="replace"
    )
    if result.returncode == 0:
        print("[tunnel] Vercel redeploy complete")
    else:
        print(f"[tunnel] Warning: Redeploy may have failed: {result.stderr[:200]}")


def main():
    print("=" * 60)
    print("Cloudflare Tunnel Startup")
    print("=" * 60)

    # Check if cloudflared exists
    if not os.path.exists(CLOUDFLARED):
        print(f"[tunnel] ERROR: cloudflared not found at {CLOUDFLARED}")
        sys.exit(1)

    # Check if previous URL is the same (skip redeploy if unchanged)
    old_url = ""
    if os.path.exists(TUNNEL_URL_FILE):
        with open(TUNNEL_URL_FILE) as f:
            old_url = f.read().strip()

    kill_existing_tunnels()
    time.sleep(2)

    tunnel_url = start_tunnel()
    update_env_file(tunnel_url)

    if tunnel_url != old_url:
        print(f"[tunnel] URL changed: {old_url} -> {tunnel_url}")
        update_vercel_env(tunnel_url)
    else:
        print("[tunnel] URL unchanged, skipping Vercel redeploy")

    print("=" * 60)
    print(f"[tunnel] Backend: {tunnel_url}")
    print(f"[tunnel] Frontend: {get_vercel_url()}")
    print("[tunnel] Tunnel is running. Press Ctrl+C to stop.")
    print("=" * 60)

    # Keep running (cloudflared is still alive as a subprocess)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[tunnel] Shutting down...")
        kill_existing_tunnels()


if __name__ == "__main__":
    main()

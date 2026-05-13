"""
Create and configure a Cloudflare named tunnel for Done.

Prerequisites:
  1. Run `cloudflared tunnel login` once on this PC.
  2. Use hostnames on a domain managed by the logged-in Cloudflare account.

Example:
  python scripts/setup_cloudflare_named_tunnel.py ^
    --core-host done-core.example.com ^
    --sandbox-host done-sandbox.example.com ^
    --run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT
CLOUDFLARED = "cloudflared"
VERCEL = os.path.join(os.environ.get("APPDATA", ""), "npm", "vercel.cmd")


def run(cmd: list[str], *, input_text: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=FRONTEND_DIR,
        encoding="utf-8",
        errors="replace",
    )


def require_cloudflare_login() -> None:
    cert = Path.home() / ".cloudflared" / "cert.pem"
    if cert.exists():
        return
    print("[named-tunnel] Cloudflare origin cert is missing.")
    print("[named-tunnel] Run this once, complete browser login, then retry:")
    print("[named-tunnel]   cloudflared tunnel login")
    sys.exit(2)


def find_tunnel_id(name: str) -> str | None:
    result = run([CLOUDFLARED, "tunnel", "list", "--output", "json"], timeout=30)
    if result.returncode != 0:
        return None
    try:
        tunnels = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for tunnel in tunnels:
        if tunnel.get("name") == name:
            return tunnel.get("id")
    return None


def create_tunnel(name: str) -> str:
    existing = find_tunnel_id(name)
    if existing:
        print(f"[named-tunnel] Reusing tunnel {name}: {existing}")
        return existing

    result = run([CLOUDFLARED, "tunnel", "create", name], timeout=60)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit(result.returncode)

    combined = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", combined, re.I)
    if not match:
        raise RuntimeError("Could not parse tunnel id from cloudflared output")
    tunnel_id = match.group(1)
    print(f"[named-tunnel] Created tunnel {name}: {tunnel_id}")
    return tunnel_id


def write_config(tunnel_id: str, core_host: str, sandbox_host: str, config_path: Path) -> None:
    credentials = Path.home() / ".cloudflared" / f"{tunnel_id}.json"
    config = f"""tunnel: {tunnel_id}
credentials-file: {credentials.as_posix()}

ingress:
  - hostname: {core_host}
    service: http://127.0.0.1:9000
  - hostname: {sandbox_host}
    service: http://127.0.0.1:8000
  - service: http_status:404
"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    print(f"[named-tunnel] Wrote config: {config_path}")


def route_dns(name: str, hostname: str) -> None:
    result = run([CLOUDFLARED, "tunnel", "route", "dns", "--overwrite-dns", name, hostname], timeout=60)
    if result.returncode == 0:
        print(f"[named-tunnel] DNS routed: {hostname}")
        return
    print(result.stdout)
    print(result.stderr)
    raise SystemExit(result.returncode)


def set_vercel_env(name: str, value: str) -> None:
    run([VERCEL, "env", "rm", name, "production", "--yes"], timeout=30)
    result = run([VERCEL, "env", "add", name, "production"], input_text=value, timeout=30)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit(result.returncode)
    print(f"[named-tunnel] Vercel env set: {name}")


def deploy_vercel() -> None:
    result = run([VERCEL, "deploy", "--prod", "--yes"], timeout=600)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="done-prod", help="Cloudflare tunnel name")
    parser.add_argument("--core-host", required=True, help="Hostname routed to Dan Core on port 9000")
    parser.add_argument("--sandbox-host", required=True, help="Hostname routed to Sandbox on port 8000")
    parser.add_argument("--config", default=str(Path.home() / ".cloudflared" / "done-prod.yml"))
    parser.add_argument("--run", action="store_true", help="Run the tunnel after setup")
    args = parser.parse_args()

    require_cloudflare_login()
    tunnel_id = create_tunnel(args.name)
    config_path = Path(args.config)
    write_config(tunnel_id, args.core_host, args.sandbox_host, config_path)
    route_dns(args.name, args.core_host)
    route_dns(args.name, args.sandbox_host)

    set_vercel_env("CORE_BACKEND_URL", f"https://{args.core_host}")
    set_vercel_env("BACKEND_URL", f"https://{args.sandbox_host}")
    run([VERCEL, "env", "rm", "NEXT_PUBLIC_API_URL", "production", "--yes"], timeout=30)
    deploy_vercel()

    print("[named-tunnel] Setup complete.")
    print(f"[named-tunnel] Run later with: cloudflared tunnel --config {config_path} run")

    if args.run:
        subprocess.run([CLOUDFLARED, "tunnel", "--config", str(config_path), "run"])


if __name__ == "__main__":
    main()

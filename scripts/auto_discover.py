#!/usr/bin/env python3
import os
import subprocess
import urllib.parse
from pathlib import Path

def discover_gateway_env():
    # Try to find the gateway service
    try:
        res = subprocess.run(["systemctl", "--user", "show", "hive-mind-gateway.service", "-p", "WorkingDirectory"], capture_output=True, text=True)
        if res.returncode == 0 and "WorkingDirectory=" in res.stdout:
            wd = res.stdout.strip().split("=")[1]
            if wd and Path(wd).exists():
                env_path = Path(wd) / ".env"
                if env_path.exists():
                    return env_path
    except Exception:
        pass
    
    # Fallbacks
    home = Path.home()
    fallbacks = [
        home / "claude-labs/projects/shared-memory-GitHub/.env",
        home / "grok-labs/projects/shared-memory-GitHub/.env",
        home / "claude-labs/projects/shared-memory/.env"
    ]
    for fb in fallbacks:
        if fb.exists():
            return fb
    return None

def parse_env(env_path):
    config = {}
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        config[k.strip()] = v.strip()
    except Exception:
        pass
    return config

def main():
    if Path(".env").exists():
        print("==> .env already exists (auto-discovery skipped).")
        return

    print("==> Attempting to auto-discover local gateway prerequisites...")
    env_path = discover_gateway_env()
    if not env_path:
        print("    No local gateway found. Please set up .env manually.")
        return

    print(f"    Found gateway at {env_path.parent}")
    config = parse_env(env_path)
    
    # Extract monitor token
    monitor_token = None
    agent_tokens = config.get("AGENT_TOKENS", "")
    for pair in agent_tokens.split(","):
        if pair.startswith("monitor:"):
            monitor_token = pair.split(":", 1)[1]
            break
            
    if not monitor_token:
        print("    Gateway .env does not contain a monitor token. Please mint one via generate_tokens.py.")
        return

    # Extract coordinator URL
    url = config.get("COORDINATOR_URL", "http://localhost:8888")
    
    print("    Successfully extracted monitor token and coordinator URL.")
    
    with open(".env", "w") as f:
        f.write(f"AGENT_TOKEN={monitor_token}\n")
        f.write(f"COORDINATOR_URL={url}\n")
        f.write(f"SHARED_MEMORY_ROOT={env_path.parent}\n")
        
    os.chmod(".env", 0o600)
    print("==> Auto-generated .env from local gateway.")

if __name__ == "__main__":
    main()

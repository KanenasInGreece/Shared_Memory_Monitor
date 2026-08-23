import sys

with open('scripts/install-systemd-user.sh', 'r') as f:
    content = f.read()

linger_code = """
echo ""
echo "Ensuring user service survives logout (linger)..."
if loginctl enable-linger "$USER" 2>/dev/null; then
  echo "Linger enabled."
elif sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
  echo "Linger enabled (via sudo -n)."
else
  echo "WARNING: Could not enable linger."
  echo "  Without linger, the monitor will die when you log out."
  echo "  Please run this manually: sudo loginctl enable-linger \"$USER\""
fi
"""

content = content.replace("systemctl --user enable shared-memory-monitor.service", "systemctl --user enable shared-memory-monitor.service\n" + linger_code)

with open('scripts/install-systemd-user.sh', 'w') as f:
    f.write(content)

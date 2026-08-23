#!/bin/bash
set -e

# Uninstalls the shared-memory-monitor user service and cleans up.
# Must be run as the user who installed the service.

SERVICE_NAME="shared-memory-monitor.service"

echo "Stopping service if running..."
systemctl --user stop "$SERVICE_NAME" || true

echo "Disabling service..."
systemctl --user disable "$SERVICE_NAME" || true

echo "Removing systemd unit file..."
rm -f "$HOME/.config/systemd/user/$SERVICE_NAME"

echo "Reloading systemd daemon..."
systemctl --user daemon-reload

echo "Attempting to disable user linger..."
if loginctl show-user "$USER" | grep -q "Linger=yes"; then
    echo "Disabling linger. If this prompts for a password or fails, you may need to run:"
    echo "sudo loginctl disable-linger $USER"
    sudo -n loginctl disable-linger "$USER" 2>/dev/null || echo "Note: sudo -n failed. You may need to disable linger manually."
fi

echo "Uninstallation of systemd components complete."
echo "You can now safely remove the shared-memory-monitor directory."

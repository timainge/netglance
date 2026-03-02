# Mac Mini Daemon Deployment

netglance can run continuously on a Mac Mini (or any macOS machine) as a background daemon. This guide walks through installing, configuring, and troubleshooting the launchd service that keeps netglance running 24/7, collecting network health data while you're away.

## Quick Start

Install the daemon with a single command:

```bash
netglance daemon install
```

Then check its status:

```bash
netglance daemon status
```

The daemon will start on next login or reboot. To manually load it immediately:

```bash
launchctl load ~/Library/LaunchAgents/com.netglance.daemon.plist
```

## Understanding launchd

macOS uses **launchd** to manage background services. netglance installs a **LaunchAgent** plist file that tells launchd how to run the daemon.

### The plist file

When you run `netglance daemon install`, it creates:

```
~/Library/LaunchAgents/com.netglance.daemon.plist
```

Here's what the plist contains (binary format, but equivalent to):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.netglance.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/netglance</string>
        <string>daemon</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/username/.config/netglance/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/username/.config/netglance/daemon.log</string>
    <key>WorkingDirectory</key>
    <string>/Users/username</string>
</dict>
</plist>
```

### Key fields explained

- **Label**: Unique identifier for this service (`com.netglance.daemon`)
- **ProgramArguments**: Command to run (first element is the executable, rest are arguments)
- **RunAtLoad**: Start the daemon when launchd loads (on login or reboot)
- **KeepAlive**: If the daemon crashes or exits, launchd restarts it automatically
- **StandardOutPath** / **StandardErrorPath**: Where all daemon output is written
- **WorkingDirectory**: The home directory, where the daemon looks for config files

## Installing the daemon

### Using the CLI

```bash
netglance daemon install
```

Output:
```
Plist installed: /Users/yourname/Library/LaunchAgents/com.netglance.daemon.plist
Load with: launchctl load /Users/yourname/Library/LaunchAgents/com.netglance.daemon.plist
```

The plist is installed but not yet loaded. On next login, launchd will load it automatically. To load it right now:

```bash
launchctl load ~/Library/LaunchAgents/com.netglance.daemon.plist
```

### Custom config file

If you have a custom config at `~/.config/netglance/custom-config.yaml`, install with:

```bash
netglance daemon install --config ~/.config/netglance/custom-config.yaml
```

The path is baked into the plist, so the daemon will always use that config.

## Checking daemon status

View whether the plist is installed and see configured schedules:

```bash
netglance daemon status
```

Output:
```
Plist installed: /Users/yourname/Library/LaunchAgents/com.netglance.daemon.plist

Configured Schedules
Task                Schedule
discover            0 */4 * * *
dns_check           0 */6 * * *
tls_verify          0 0 * * *
baseline_diff       0 2 * * *
report              0 6 * * *
```

This shows all tasks that will run on schedule. The cron expressions tell you when each runs (e.g., `0 */4 * * *` means every 4 hours at the top of the hour).

### Checking if the daemon is running

Use `launchctl` to see live status:

```bash
launchctl list | grep netglance
```

If the daemon is running, you'll see output like:

```
7654    0    com.netglance.daemon
```

The first number is the process ID. If you see a `-` instead, the daemon exited (check the log).

Get full details about the loaded service:

```bash
launchctl print user/$(id -u)/com.netglance.daemon
```

This shows when it was last started, whether it's running, and exit codes.

## Viewing logs

The daemon writes all output to:

```
~/.config/netglance/daemon.log
```

View recent activity:

```bash
tail -f ~/.config/netglance/daemon.log
```

Watch logs as tasks run:

```bash
log show --predicate 'process == "netglance"' --level debug
```

### Common log patterns

**Daemon starts normally:**
```
[INFO] netglance daemon starting
[INFO] Scheduled Tasks
[INFO]   discover: 0 */4 * * *
```

**Task runs successfully:**
```
[DEBUG] Running task: discover
[DEBUG] Found 8 devices
[DEBUG] Task complete: discover
```

**Permission error (usually means daemon needs root):**
```
[ERROR] PermissionError: operation not permitted
```

## Uninstalling the daemon

Clean removal:

```bash
netglance daemon uninstall
```

Output:
```
Plist removed.
Unload with: launchctl unload <path>
```

This removes the plist file. The daemon will stop at next login or reboot. To stop it immediately:

```bash
launchctl unload ~/Library/LaunchAgents/com.netglance.daemon.plist
```

### Manual removal (if CLI is unavailable)

```bash
rm ~/Library/LaunchAgents/com.netglance.daemon.plist
launchctl unload ~/Library/LaunchAgents/com.netglance.daemon.plist 2>/dev/null
```

Verify it's gone:

```bash
netglance daemon status
```

Should show `Plist not installed.`

## Energy saver settings for always-on operation

A Mac Mini used as a home server should never sleep. Use System Settings or `pmset` to ensure it stays awake.

### Via System Settings (GUI)

1. **System Settings** → **Energy Saver**
2. **Prevent computer from sleeping automatically when the display is off**: checked
3. **Start up automatically after a power failure**: checked
4. **Enable Power Nap**: checked (allows background activity during sleep)

### Via command line

```bash
# Disable sleep on AC power
sudo pmset -c sleep 0

# Display can sleep after 5 minutes
sudo pmset -c displaysleep 5

# Restart automatically after power failure
sudo pmset -c autorestart 1

# Enable Power Nap (background tasks, even in sleep)
sudo pmset -c powernap 1
```

View current settings:

```bash
pmset -g
```

## Permissions and raw sockets

Some netglance modules (packet capture, ARP scanning) require raw socket access. On macOS, this typically requires `sudo`.

### Running the daemon with elevated privileges

By default, netglance runs as your user. For modules that need raw sockets, you can install a system-level LaunchDaemon instead:

1. Create the plist in `/Library/LaunchDaemons/` (system-wide, requires sudo)
2. The daemon runs as `root`

To do this manually:

```bash
sudo netglance daemon install
```

This installs the plist to `/Library/LaunchDaemons/com.netglance.daemon.plist` instead and runs as root.

**Warning**: System daemons run with full privileges. Only do this if you trust the netglance code and your config.

### Alternative: grant Terminal full disk access

Some features work without raw sockets. If you just want background monitoring without packet capture:

1. **System Settings** → **Privacy & Security** → **Full Disk Access**
2. Add your Terminal app
3. Run `netglance daemon install` from that Terminal window

The daemon will inherit the Terminal's permissions.

## Troubleshooting

### Daemon won't start

Check the system launchd logs:

```bash
launchctl print user/$(id -u)/com.netglance.daemon
```

Look at the `stderr` path in the output. View that log file:

```bash
cat ~/.config/netglance/daemon.log
```

Common causes:
- **`netglance: command not found`**: The executable path in the plist is stale. Reinstall: `netglance daemon install`
- **`permission denied`**: Daemon needs root or capabilities. Try `sudo netglance daemon install`
- **`database is locked`**: Another netglance process is using the database. Close any manual CLI invocations.

### Daemon exits immediately

If `launchctl list | grep netglance` shows no process (only a `-`), the daemon is crashing on startup.

Check the log:

```bash
tail -20 ~/.config/netglance/daemon.log
```

If the log is empty, the daemon can't even start. The plist path is likely wrong:

```bash
cat ~/Library/LaunchAgents/com.netglance.daemon.plist | grep ProgramArguments -A 5
```

Verify the path exists:

```bash
which netglance
```

If `netglance` is not in PATH (e.g., it's in a virtualenv), reinstall with the full path:

```bash
netglance daemon install --netglance-path $(which netglance)
```

### Database locked errors

If the daemon and CLI both try to access the database simultaneously, you'll see:

```
OperationalError: database is locked
```

Solution: Either run the daemon with `KeepAlive: false` in the plist (so it doesn't restart), or queue CLI commands for when the daemon is idle.

To temporarily stop the daemon:

```bash
launchctl unload ~/Library/LaunchAgents/com.netglance.daemon.plist
```

Run your CLI commands, then reload:

```bash
launchctl load ~/Library/LaunchAgents/com.netglance.daemon.plist
```

### Logs grow too large

The daemon appends to `~/.config/netglance/daemon.log` indefinitely. Set up log rotation using `logrotate` or similar:

```bash
# Check current size
du -h ~/.config/netglance/daemon.log

# Rotate and compress if over 50 MB
if [ $(stat -f%z ~/.config/netglance/daemon.log) -gt 52428800 ]; then
  gzip ~/.config/netglance/daemon.log
  touch ~/.config/netglance/daemon.log
fi
```

Add this as a cron job or launchd timer for automatic rotation.

## Next steps

Once the daemon is running:

- Configure custom schedules in `~/.config/netglance/config.yaml` (see [Getting Started — Configuration](../getting-started.md#configuration))
- Query results with `netglance query` or the REST API
- Export data for analysis with `netglance export`
- Set up alerting via external tools (Prometheus, Grafana, etc.)

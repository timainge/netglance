# Raspberry Pi Deployment

Deploy netglance on a Raspberry Pi to run 24/7 as a dedicated home network monitor. This guide walks through hardware selection, OS setup, installation, and systemd daemon configuration.

## Hardware

### Recommended models

- **Raspberry Pi 4 (4GB or 8GB)** — ideal balance of CPU, RAM, and cost; handles all netglance modules without throttling
- **Raspberry Pi 5** — latest, faster CPU (excellent for traffic capture); overkill for most setups but future-proof
- **Raspberry Pi 3B+** — older but still viable; adequate CPU; may struggle under sustained traffic capture
- **Raspberry Pi Zero 2 W** — minimal form factor; 64-bit ARM; tight on RAM but works for basic monitoring (no traffic module)

Avoid Pi Zero (original) and Pi 3A+ — insufficient RAM for SQLite, Python, and concurrent network operations.

### Connectivity

**Ethernet strongly recommended** for a monitoring node. Your monitor itself should not compete for WiFi bandwidth or be subject to WiFi interference. A wired connection ensures:
- Stable baseline for device discovery and ping tests
- Accurate traffic analysis (not affected by WiFi driver quirks)
- Reliable remote SSH access for troubleshooting

If Ethernet unavailable, Pi 4/5 WiFi is adequate but monitor WiFi health separately using `netglance wifi` module.

### Power supply

Use the official Raspberry Pi power supply (5V/3A for Pi 4, 5V/5A for Pi 5) to avoid brownouts that corrupt the SD card or database. Cheap USB-C chargers often deliver insufficient current under load, causing random reboots.

### Storage

- **32 GB microSD card minimum** — SQLite database grows ~1-2 MB per week at default monitoring frequency
- **A2-rated card** — better random I/O performance for SQLite
- Popular choices: Samsung PRO Endurance, Kingston Industrial, SanDisk Extreme

Plan for ~500 MB reserved per year of data retention on a 32 GB card.

## OS Setup

### Flash SD card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) for macOS/Windows/Linux
2. Insert SD card into your computer
3. Open Imager, select **Raspberry Pi OS Lite (64-bit)**
   - Lite = no desktop, minimal overhead (perfect for a headless monitor)
   - 64-bit = faster Python on modern Pis
4. Click **Next**, then **Edit Settings** to configure:
   - **Hostname**: `netglance-monitor` (or your choice)
   - **Username/Password**: create user `netglance` with a strong password
   - **SSH**: check "Enable SSH" and select "Use password authentication"
   - **WiFi** (optional): if using WiFi, configure SSID + password
5. Click **Save**, then **Yes** to write (this erases the card)
6. When complete, eject and insert the Pi

### First boot

Insert SD card into the Pi, connect Ethernet, power on. Wait 2–3 minutes for first boot.

```bash
# SSH from your laptop (replace hostname if different)
ssh netglance@netglance-monitor.local
# or use IP directly if .local doesn't work:
ssh netglance@192.168.1.XXX
```

Once logged in:

```bash
# Update package lists and installed packages
sudo apt update && sudo apt upgrade -y

# Install build tools needed for Python packages with C extensions
sudo apt install -y build-essential libffi-dev libssl-dev

# (Optional) Set static IP so netglance's baseline and device tracking remain consistent
sudo nano /etc/dhcpcd.conf
```

To set a static IP, edit `/etc/dhcpcd.conf` and add at the end:

```
interface eth0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=1.1.1.1 8.8.8.8
```

Reboot to apply:

```bash
sudo reboot
```

## Installing netglance

### Install Python and uv

Raspberry Pi OS typically ships with Python 3.11+. Verify:

```bash
python3 --version
```

Install `uv` (fast Python package manager):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### Install netglance from source

Clone the netglance repository and install in development mode:

```bash
cd ~
git clone https://github.com/<your-org>/netglance.git
cd netglance
uv pip install -e .
```

Or, if published to PyPI:

```bash
uv pip install netglance
```

Verify installation:

```bash
netglance --help
netglance version
```

## Systemd daemon

Running netglance as a systemd service ensures it starts automatically on boot and restarts on crash.

### Create systemd service file

Some netglance modules (ARP scanning, ICMP ping) require raw socket access, which needs root or elevated capabilities. For simplicity, run the entire service as root. For better security, you can use `CAP_NET_RAW` capability restrictions, but root is more straightforward for a home monitor.

Create `/etc/systemd/system/netglance.service`:

```bash
sudo nano /etc/systemd/system/netglance.service
```

Paste:

```ini
[Unit]
Description=netglance Network Monitor
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root
Environment="PATH=/root/.local/bin:/usr/local/bin:/usr/bin"
ExecStart=/root/.local/bin/netglance daemon start
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Key points:
- `After=network.target` — wait for networking before starting
- `User=root` — needed for raw socket access (ARP, ICMP)
- `WorkingDirectory=/root` — daemon writes to `~/.config/netglance/`
- `Restart=on-failure` — if netglance crashes, systemd restarts it after 10 seconds
- `StandardOutput=journal` — logs go to journalctl (not a file)

### Enable and start

```bash
# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable netglance

# Start the service now
sudo systemctl start netglance

# Check status
sudo systemctl status netglance

# View logs (tail the last 50 lines)
journalctl -u netglance -n 50

# Follow logs in real-time
journalctl -u netglance -f
```

### Verify it's running

After starting, check that the daemon is active:

```bash
sudo systemctl is-active netglance
# should output: active

# Also verify the database is being written to
ls -lh ~/.config/netglance/netglance.db
```

## Crontab alternative

If you prefer not to run a daemon, use cron to schedule periodic scans:

```bash
# Edit the current user's crontab
crontab -e
```

Add:

```
# Every 5 minutes: quick connectivity check
*/5 * * * * /root/.local/bin/netglance ping --all >> /var/log/netglance-ping.log 2>&1

# Every hour: full health check
0 * * * * /root/.local/bin/netglance report --output /home/netglance/reports/$(date +\%Y-\%m-\%d-\%H).txt >> /var/log/netglance-report.log 2>&1

# Daily: device discovery (updates baseline)
0 0 * * * /root/.local/bin/netglance discover --refresh >> /var/log/netglance-discover.log 2>&1
```

Logs will accumulate; consider logrotate for rotation:

```bash
# Create /etc/logrotate.d/netglance
sudo nano /etc/logrotate.d/netglance
```

Paste:

```
/var/log/netglance-*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    missingok
}
```

## Persistent monitoring

### Database and data retention

The SQLite database lives at `~/.config/netglance/netglance.db` (on the Pi at `/root/.config/netglance/netglance.db` if running as root).

- **Typical growth**: 1–2 MB per week at default frequency (ping every 5 min, discovery hourly)
- **32 GB SD card lifespan**: ~2–3 years of retention before running out of space

Periodic backups prevent data loss from SD card failure:

```bash
# Backup to external USB drive (mount at /mnt/backup)
sudo cp /root/.config/netglance/netglance.db /mnt/backup/netglance-$(date +%Y-%m-%d).db

# Or scp to a remote machine
scp root@netglance-monitor.local:/root/.config/netglance/netglance.db ~/backups/
```

Add to crontab for automated daily backups:

```
0 2 * * * /usr/bin/rsync -av /root/.config/netglance/netglance.db /mnt/backup/
```

### Log rotation

systemd automatically manages journal logs with size/age limits. To avoid filling the SD card:

```bash
# Edit journald config
sudo nano /etc/systemd/journald.conf
```

Set reasonable limits:

```ini
SystemMaxUse=200M
MaxFileSec=7day
```

Then restart journald:

```bash
sudo systemctl restart systemd-journald
```

### Disk space monitoring

Check available space regularly:

```bash
# Overall disk usage
df -h /

# netglance data size
du -sh /root/.config/netglance/

# If running low, clean up old database records via the API
# (future feature) or back up and reset the database
```

## Remote access

### SSH management

netglance-monitor is accessible via SSH from any machine on the network:

```bash
# From your laptop
ssh root@netglance-monitor.local
ssh root@192.168.1.100  # if .local doesn't resolve

# Copy database home for analysis
scp root@netglance-monitor.local:/root/.config/netglance/netglance.db ~/analysis/
```

### HTML reports

If installed, the REST API can serve a simple dashboard:

```bash
# On the Pi, start the API server (in background or separate tmux)
sudo /root/.local/bin/netglance api start --host 0.0.0.0 --port 8000 &

# From your laptop, browse to
open http://netglance-monitor.local:8000
# or http://192.168.1.100:8000
```

Check API status:

```bash
sudo /root/.local/bin/netglance api status
```

### Database access

Query the database remotely via scp and local SQLite:

```bash
# Copy to laptop
scp root@netglance-monitor.local:/root/.config/netglance/netglance.db ~/tmp/

# Query locally
sqlite3 ~/tmp/netglance.db "SELECT * FROM devices LIMIT 10;"
```

## Power and reliability

### Unexpected shutdown handling

SQLite is crash-safe (uses WAL — Write-Ahead Logging by default), so unexpected power loss won't corrupt the database. However, SD card filesystems (ext4) can suffer bit rot over time. Mitigation:

- Use official Pi power supply (avoid brownouts)
- Keep regular backups (daily via cron)
- Monitor `journalctl` for filesystem warnings

### Watchdog timer (optional)

Enable the Pi's built-in watchdog to auto-reboot on hang:

```bash
# Install watchdog daemon
sudo apt install -y watchdog

# Edit config
sudo nano /etc/watchdog.conf
```

Uncomment:

```ini
watchdog-device = /dev/watchdog
max-load-1 = 24
```

Start and enable:

```bash
sudo systemctl enable watchdog
sudo systemctl start watchdog
```

### UPS hat (optional)

For critical monitoring, consider a UPS hat (e.g., Geekworm X728):
- Provides battery backup during power loss
- Gracefully shuts down the Pi on low battery
- Pi remains running and responsive during outages

Install per the hat manufacturer's instructions; most provide a daemon that monitors battery and triggers safe shutdown.

### Thermal management

Pi 4 throttles CPU if temp exceeds 80°C (Pi 5 at 85°C). In a warm room or without airflow:

```bash
# Check current temp
/opt/vc/bin/vcgencmd measure_temp

# If running warm, add cooling
# - improve airflow (move fan near intake)
# - apply heatsinks to CPU, RAM, USB controller
# - consider active cooling (small fan mounted to case)
```

Sustained throttling degrades discovery and traffic capture. A simple heatsink + case airflow solves most thermal issues.

## Summary

You now have netglance running 24/7 on a dedicated Pi:

1. ✓ Hardware selected (Pi 4 or 5, Ethernet, 32 GB SD, official PSU)
2. ✓ Raspberry Pi OS Lite 64-bit installed with static IP
3. ✓ netglance installed via uv
4. ✓ systemd service running as root, auto-restart on crash
5. ✓ Logs accessible via journalctl, backups automated
6. ✓ Remote SSH access for management and debugging

The Pi is now your network's always-on sentinel, steadily collecting baseline health data and alerting you to changes.

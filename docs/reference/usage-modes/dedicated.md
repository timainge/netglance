# Dedicated Monitor

> Always-on hardware that watches your network even when everything else is off.

A dedicated monitor is a device — Raspberry Pi, Mac Mini, or Docker container — running netglance 24/7 on your home network. It sees every device connect and disconnect, captures long-term trends, and alerts you to problems in real time. Unlike the background daemon on a laptop, it never sleeps.

## When to use this mode

- You want true 24/7 visibility, not just "when my laptop is open"
- You care about catching events at 3 AM — rogue devices, DNS changes, certificate expirations
- You want a historical record of your network state over weeks and months
- You have a spare Raspberry Pi, Mac Mini, or a NAS/VM that can run Docker
- You want a network monitoring appliance without buying commercial hardware

## Choosing your platform

| Platform | Power draw | Cost | Setup time | Best for |
|----------|:----------:|:----:|:----------:|----------|
| **Raspberry Pi 4/5** | ~5W | ~$50-80 | 30 min | Dedicated low-power appliance |
| **Mac Mini** | ~6-40W | (existing) | 15 min | Already have one sitting around |
| **Docker** | varies | free | 10 min | NAS, VM, cloud, or any Linux host |

### Raspberry Pi

The natural choice for a dedicated monitor. Low power draw means you can leave it plugged in forever. Ethernet gives stable, accurate readings. ARM-compatible Python ecosystem means netglance runs natively.

**What you need**: Pi 4 or 5, Ethernet cable, 32GB microSD (A2-rated), official power supply.

```bash
# After OS setup and SSH access:
pip install netglance
sudo netglance daemon install   # or use systemd — see full guide
```

**[Full Raspberry Pi setup guide &rarr;](../deployment/raspberry-pi.md)** covers hardware selection, OS flashing, Python install, systemd service, log rotation, and GPIO status LED.

### Mac Mini

If you have a Mac Mini that's always on (media server, home automation hub), add netglance as a launchd service. Same daemon setup as the [Background Daemon](daemon.md) mode, but on hardware that doesn't sleep.

```bash
uv tool install netglance
netglance daemon install
```

**[Full macOS daemon setup guide &rarr;](../deployment/mac-mini-daemon.md)** covers launchd configuration, auto-restart, log rotation, and energy saver settings.

### Docker

Run netglance in a container on any Linux host — NAS (Synology, QNAP), VM, cloud instance, or bare metal. Host networking is required for accurate network scanning.

```bash
docker run -d \
  --name netglance \
  --network host \
  --cap-add NET_RAW \
  --cap-add NET_ADMIN \
  -v netglance-data:/root/.config/netglance \
  netglance/netglance:latest \
  daemon start
```

**[Full Docker setup guide &rarr;](../deployment/docker.md)** covers Dockerfile, compose config, host networking, volume mounts, and container health checks.

## What to expect

Once your dedicated monitor is running:

- **Device inventory** updates every 15 minutes — new devices trigger alerts
- **DNS, TLS, and health checks** run on schedule — failures trigger alerts
- **Baseline diffs** capture network changes daily
- **Metrics accumulate** in SQLite — query with `netglance metrics` for long-term trends
- **SSH in** to run ad-hoc CLI commands or check `netglance daemon status`

## Remote access

Your dedicated monitor runs headless. Access it via:

- **SSH**: `ssh pi@netglance.local` (or by IP)
- **netglance REST API**: `netglance api serve --host 0.0.0.0` exposes results over HTTP for dashboards or other tools
- **MCP over HTTP**: `netglance mcp serve --transport http` lets AI assistants query the monitor remotely

## Pairing with other modes

- **Dedicated + MCP**: Run the MCP server on your Pi/Mini so AI assistants can query the always-on monitor from any device on the network.
- **Dedicated + Scheduled Checks**: Use cron for custom check combinations beyond the daemon's built-in schedule.
- **Dedicated + Alerts**: Configure alert rules with notification channels (webhook, email) so you know the moment something changes, even if you're not at home.

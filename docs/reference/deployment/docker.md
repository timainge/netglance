# Docker Deployment

netglance is a network scanning and monitoring tool that can run in Docker, but containerization introduces important constraints—particularly for modules that perform low-level network operations like ARP scanning and ICMP ping. This guide covers how to build, configure, and run netglance in containers.

## Dockerfile

Here's a production-ready Dockerfile for netglance:

```dockerfile
FROM python:3.11-slim

# Install system dependencies for network operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpcap-dev \
    tcpdump \
    nmap \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 netglance

# Set working directory
WORKDIR /app

# Copy application (assumes pyproject.toml and source in current dir)
COPY . .

# Install netglance
RUN pip install --no-cache-dir .

# Switch to non-root user
USER netglance

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD netglance ping -t 1 8.8.8.8 || exit 1

ENTRYPOINT ["netglance"]
```

To build and run:

```bash
docker build -t netglance:latest .
docker run --net=host --cap-add=NET_RAW --cap-add=NET_ADMIN netglance discover
```

## Network Mode and Capabilities

**This is critical**: most netglance modules require `--net=host` and raw socket capabilities.

### Why `--net=host`?

- **ARP scanning** (discover, arp modules) uses raw Ethernet frames—it must see real LAN traffic, not Docker's virtual network
- **DHCP detection** examines broadcast packets on the local network
- **WiFi analysis** requires access to wireless interface management frames
- In bridged or NAT mode, the container sees only Docker's virtual network, not your real LAN

### Capabilities

Raw socket operations require Linux capabilities:

```bash
docker run --net=host \
  --cap-add=NET_RAW \
  --cap-add=NET_ADMIN \
  netglance discover
```

- `NET_RAW`: allows creation of raw sockets (required for ARP, ICMP, packet crafting)
- `NET_ADMIN`: allows network interface configuration and packet sniffing

### Platform limitations

| Platform | Host networking | Raw sockets | Status |
|----------|-----------------|------------|--------|
| Linux    | ✓ Full access   | ✓ Yes      | Fully supported |
| macOS (Docker Desktop) | ✗ Limited | ✗ No | Bridged mode only; ARP/DHCP/WiFi modules won't work |
| Windows (Docker Desktop) | ✗ Limited | ✗ No | Bridged mode only; ARP/DHCP/WiFi modules won't work |

**Recommendation**: For full network scanning capability, use Docker on a Linux host (Raspberry Pi, NAS, server, or Linux VM).

## Docker Compose Setup

For production deployments with persistent storage, environment configuration, and resource limits:

```yaml
version: '3.8'

services:
  netglance:
    build:
      context: .
      dockerfile: Dockerfile
    image: netglance:latest
    container_name: netglance

    # Critical: enables ARP, DHCP, WiFi modules
    network_mode: host

    # Raw socket capabilities
    cap_add:
      - NET_RAW
      - NET_ADMIN

    # Persistent storage for database and config
    volumes:
      - netglance-data:/root/.config/netglance
      - ./config.yaml:/root/.config/netglance/config.yaml:ro
      - ./reports:/reports

    # Resource limits
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M

    # Auto-restart on failure
    restart: unless-stopped

    # Health check
    healthcheck:
      test: ["CMD", "netglance", "ping", "-t", "1", "8.8.8.8"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s

    # Optional: environment variable overrides
    environment:
      - NETGLANCE_DB_PATH=/root/.config/netglance/netglance.db
      - NETGLANCE_CONFIG=/root/.config/netglance/config.yaml

volumes:
  netglance-data:
    driver: local
```

Start the service:

```bash
docker-compose up -d
docker-compose logs -f netglance
```

## Volume Mounts and Persistence

### Database storage

The SQLite database lives at `~/.config/netglance/netglance.db` inside the container. Mount a volume to persist it across container restarts:

```bash
docker run --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  -v netglance-data:/root/.config/netglance \
  netglance discover
```

### Configuration file

Mount your custom `config.yaml` as read-only:

```bash
docker run --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  -v netglance-data:/root/.config/netglance \
  -v $(pwd)/config.yaml:/root/.config/netglance/config.yaml:ro \
  netglance discover
```

### Output reports

Mount a directory for HTML or JSON reports:

```bash
docker run --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  -v netglance-data:/root/.config/netglance \
  -v $(pwd)/reports:/reports \
  netglance report --format html -o /reports/latest.html
```

## Running One-Off Commands

Execute a single netglance command without starting a persistent service:

```bash
# Network discovery
docker run --rm --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  netglance discover

# Port scanning on a specific device
docker run --rm --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  netglance scan 192.168.1.100

# Generate a health report
docker run --rm --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  -v $(pwd)/reports:/reports \
  netglance report --format html -o /reports/report.html

# Simple DNS check (doesn't need raw sockets)
docker run --rm --net=host \
  netglance dns --check-leak
```

For interactive commands in a running container:

```bash
# Start a long-running container
docker run -d --name netglance-daemon --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  netglance sleep infinity

# Execute commands
docker exec netglance-daemon netglance discover
docker exec netglance-daemon netglance baseline save

# Clean up
docker stop netglance-daemon && docker rm netglance-daemon
```

## Scheduling with Cron

For periodic health checks, use the host's cron rather than Docker's built-in scheduler:

```bash
# /etc/cron.d/netglance-check
0 */6 * * * /usr/bin/docker run --rm --net=host \
  --cap-add=NET_RAW --cap-add=NET_ADMIN \
  -v netglance-data:/root/.config/netglance \
  -v /var/log/netglance:/reports \
  netglance report --format json -o /reports/health-$(date +\%Y\%m\%d-\%H\%M\%S).json
```

Or use Docker's health check endpoint to monitor a persistent container and alert on failures.

## Limitations of Containerized Network Scanning

### macOS and Windows

Docker Desktop on macOS and Windows runs Linux in a lightweight VM. The host networking mode does not expose your real LAN to the container—it connects the container to the VM's network instead. **This means**:

- ARP scanning will not detect real network devices
- DHCP detection will fail
- WiFi analysis won't work
- Ping and DNS queries may work depending on routing

**Workaround**: Run netglance on a Linux machine (physical or VM), or use the native Python CLI on your Mac/Windows host.

### WiFi module on Linux

The WiFi module requires access to wireless interface management frames. This may require:

```bash
# Option 1: Run privileged (not recommended for production)
docker run --privileged --net=host netglance wifi

# Option 2: Pass the wireless interface explicitly
docker run --net=host --device=/sys/class/net/wlan0 netglance wifi
```

### Modules that work in bridged mode

Some modules don't require `--net=host`:

- **ping**: Can use the container's own network stack (but won't reach your LAN)
- **dns**: Works fine in any network mode
- **http**: Can scan external hosts in bridged mode
- **tls**: Certificate checks work in any mode

For these, you can omit `--net=host`, but you lose the ability to scan your local network.

## Security Considerations

- `--net=host` and `NET_RAW`/`NET_ADMIN` capabilities are powerful. The container can capture network traffic, spoof packets, and see all traffic on the host's interfaces. Use only with trusted images.
- Keep the image updated with `docker pull` and rebuild regularly to patch dependencies.
- Don't expose netglance's CLI or any REST API ports unnecessarily; if running a daemon, keep it internal to your network.
- Run netglance as a non-root user inside the container (the Dockerfile above does this). The capabilities are granted at the container level, not to a user account.
- Consider using seccomp or AppArmor profiles to further restrict syscalls in production.

## Troubleshooting

**"Permission denied" on raw socket operations**

```
OSError: [Errno 1] Operation not permitted
```

Add capabilities:

```bash
docker run --net=host --cap-add=NET_RAW --cap-add=NET_ADMIN netglance discover
```

**"No such device" or "No suitable device found"**

This usually means `--net=host` is not working (macOS/Windows) or the interface is not visible in the container. Verify you're on Linux with host networking, or run netglance on the host directly.

**Database locked**

If running multiple containers against the same `netglance-data` volume, SQLite may complain about a locked database. Solutions:

1. Use only one container writing to the database at a time
2. Use a Redis-backed store (if available in future versions)
3. Mount separate data volumes for separate containers and synchronize via a higher-level coordinator

**Reports directory permission denied**

Ensure the reports directory is writable by UID 1000 (the netglance user in the container):

```bash
mkdir -p ./reports
chmod 777 ./reports
```

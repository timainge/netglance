# Remediation Playbook

When netglance flags issues on your network, this playbook provides step-by-step fixes grouped by category. Each section addresses a specific problem type with actionable remediation steps.

## DNS Issues

### Changing DNS Resolvers

1. **At the router level** (affects all devices):
   - Open your router's admin panel (usually `192.168.1.1` or `192.168.0.1`)
   - Log in with your admin credentials
   - Navigate to **Settings > DNS** or **Internet > DNS**
   - Replace ISP-provided DNS with preferred resolvers:
     - **Cloudflare**: `1.1.1.1` and `1.0.0.1`
     - **Quad9**: `9.9.9.9` and `149.112.112.112`
     - **Google**: `8.8.8.8` and `8.8.4.4`
   - Save and reboot the router
   - Run `netglance dns check` to confirm resolution works

2. **Per-device on macOS**:
   ```bash
   networksetup -setdnsservers Wi-Fi 1.1.1.1 1.0.0.1
   networksetup -getdnsservers Wi-Fi  # verify
   ```

3. **Per-device on Linux**:
   - Edit `/etc/resolv.conf` or use `systemd-resolved`
   - Add `nameserver 1.1.1.1` and `nameserver 1.0.0.1`

### Enabling DNS-over-HTTPS (DoH)

1. **On macOS**:
   - System Preferences > Network > Wi-Fi > Advanced > DNS
   - Click the **+** button under DNS Servers
   - Add: `1.1.1.1` and `1.0.0.1`
   - Enabled DoH by default for Cloudflare (macOS 14+)

2. **On Linux**:
   - Edit `/etc/systemd/resolved.conf`:
     ```ini
     DNS=1.1.1.1 1.0.0.1
     DNSSECMode=yes
     DNSOverTLS=yes
     ```
   - Restart: `sudo systemctl restart systemd-resolved`

3. **Via browser** (Firefox, Chrome):
   - Settings > Privacy & Security > DNS over HTTPS
   - Select your resolver or custom endpoint

### Fixing DNS Leaks When Using a VPN

1. **Verify the leak**:
   ```bash
   netglance dns check
   ```
   If it reports queries leaking outside your VPN tunnel, proceed.

2. **Force DNS through VPN**:
   - Open your VPN app settings
   - Find **DNS Settings** or **Custom DNS**
   - Enable "Force DNS through VPN tunnel"
   - Set DNS to your VPN provider's servers or Quad9 (`9.9.9.9`)
   - Reconnect to VPN

3. **Disable IPv6 if needed**:
   - If leak persists, your VPN may not fully support IPv6
   - On macOS: System Preferences > Network > Wi-Fi > Advanced > TCP/IP > Configure IPv6 > **Off**
   - On Linux: `echo "net.ipv6.conf.all.disable_ipv6 = 1" | sudo tee -a /etc/sysctl.conf && sudo sysctl -p`

4. **Verify the fix**:
   ```bash
   netglance dns check
   ```

### Enabling DNSSEC Validation

1. **At the router level**:
   - Admin panel > **Settings > DNSSEC**
   - Enable DNSSEC validation
   - Save and reboot

2. **On Linux**:
   - Edit `/etc/systemd/resolved.conf`:
     ```ini
     DNSSEC=yes
     ```
   - Restart: `sudo systemctl restart systemd-resolved`

3. **Verify**:
   ```bash
   netglance dns check
   ```
   Look for "DNSSEC: enabled" in output.

---

## WiFi Issues

### Upgrading to WPA3 (or WPA2/WPA3 Transitional)

1. **Check router capabilities**:
   - Log in to admin panel
   - Navigate to **Wireless > Security** or **WiFi > Authentication**
   - If WPA3 is available, select it; otherwise use **WPA2/WPA3 (Mixed)**

2. **Set a strong passphrase** (25+ characters, mixed case, numbers, symbols):
   - Router admin panel > WiFi settings
   - Update the pre-shared key (PSK)
   - Save and reconnect all devices

3. **Verify**:
   ```bash
   netglance wifi scan
   ```
   Look for "WPA3" or "WPA2-PSK/WPA3-PSK" in the security column.

### Optimizing WiFi Channel

1. **Scan for interference**:
   ```bash
   netglance wifi scan
   ```
   Note neighboring SSIDs and their channels.

2. **Select least-congested channel**:
   - **2.4GHz band**: Use channel **1, 6, or 11** (non-overlapping)
   - **5GHz band**: Try DFS channels (120–144) if available and uncontested
   - Avoid channels close to neighbors' networks

3. **Change channel**:
   - Router admin panel > Wireless > Channel
   - Apply change and reboot
   - Reconnect devices

4. **Verify**:
   ```bash
   netglance wifi scan
   ```

### Disabling WPS (WiFi Protected Setup)

1. **Log in to router admin panel**
2. Navigate to **Wireless > Security** or **WiFi > Advanced**
3. Find **WPS** and set to **Disabled**
4. Save and reboot
5. Verify in netglance output (no WPS vulnerabilities reported)

### Setting Up a Guest Network for IoT Devices

1. **Create guest network**:
   - Router admin panel > Wireless > Guest Network
   - Enable guest network
   - Give it a descriptive name (e.g., `Home-IoT`)
   - Set a strong passphrase

2. **Isolate guest traffic**:
   - Look for **Guest Network Isolation** or **AP Isolation**
   - Enable isolation so guest devices can't access main network

3. **Connect IoT devices** to the guest network (not your primary WiFi)

4. **Verify isolation**:
   ```bash
   netglance discover
   ```
   Devices on guest network should appear separately or with restricted connectivity to primary network.

---

## Port and Service Issues

### Identifying and Disabling Unused Services

1. **Scan for open ports**:
   ```bash
   netglance scan <target-ip>
   ```
   Note which ports/services are exposed.

2. **For each unwanted service**, identify and disable:
   - **SSH** (port 22): Disable remote login or restrict to specific IPs
   - **SMB** (ports 139, 445): Disable file sharing or restrict to LAN only
   - **HTTP** (port 80): Disable web server if not needed

3. **On macOS** (disable SSH):
   ```bash
   sudo systemsetup -setremotelogin off
   ```

4. **On Linux** (disable SSH):
   ```bash
   sudo systemctl disable ssh
   sudo systemctl stop ssh
   ```

### Configuring Host Firewalls

1. **On macOS** (pf firewall):
   - System Preferences > Security & Privacy > Firewall
   - Click **Firewall Options**
   - Check "Block all incoming connections" (or configure rules via `pfctl`)

2. **On Linux** (iptables/firewalld):
   ```bash
   sudo systemctl enable firewalld
   sudo systemctl start firewalld
   sudo firewall-cmd --permanent --add-service=http
   sudo firewall-cmd --reload
   ```

3. **Verify**:
   ```bash
   netglance scan <your-ip>
   ```

### Closing Router Ports

1. **Disable UPnP** (prevents apps from auto-opening ports):
   - Router admin panel > **Advanced > UPnP**
   - Set to **Disabled**
   - Save and reboot

2. **Remove port forwarding rules**:
   - Router admin panel > **Port Forwarding** or **Virtual Server**
   - Delete any rules you don't recognize
   - Save

3. **Disable remote management**:
   - Router admin panel > **Administration** or **Advanced > Remote Management**
   - Set to **Disabled**

4. **Verify**:
   ```bash
   netglance scan <router-ip>
   ```

---

## VPN Issues

### Fixing DNS Leaks with VPN

See **DNS Issues > Fixing DNS Leaks When Using a VPN** above.

### Enabling IPv6 Leak Protection

1. **Check if your VPN supports IPv6**:
   - Consult your VPN provider's documentation

2. **If not supported, disable IPv6 system-wide**:
   - **macOS**: System Preferences > Network > Wi-Fi > Advanced > TCP/IP > Configure IPv6 > **Off**
   - **Linux**: Add to `/etc/sysctl.conf`:
     ```ini
     net.ipv6.conf.all.disable_ipv6 = 1
     net.ipv6.conf.default.disable_ipv6 = 1
     ```
     Then run: `sudo sysctl -p`

3. **Verify VPN app settings**:
   - Look for **IPv6 Leak Protection** toggle and enable it

### Verifying VPN Kill Switch

1. **Test kill switch functionality**:
   - Enable VPN kill switch in your VPN app settings
   - Disconnect from VPN
   - Confirm your ISP DNS is NOT leaking: `netglance dns check`

2. **If kill switch isn't working**:
   - Update your VPN app to the latest version
   - Reinstall and reconfigure from scratch
   - Contact VPN provider support

---

## Device Management

### Identifying and Removing Unknown Devices

1. **List connected devices**:
   ```bash
   netglance discover
   ```

2. **For each unknown device**:
   - Check the MAC address against a vendor lookup (usually shown in netglance output)
   - Ask household members if they recognize it
   - Check your router's admin panel for the device name

3. **Remove unauthorized devices**:
   - Option 1: Change your WiFi passphrase (forces reconnect, unknown devices drop)
   - Option 2: Router admin panel > **Wireless > MAC Filter** > Block the MAC address
   - Option 3: Router admin panel > **Connected Devices** > Disconnect/blacklist

### Network Segmentation with VLANs

1. **Create a separate IoT VLAN**:
   - Router admin panel > **Wireless > Guest Network** or **Advanced > VLAN**
   - Create a new network (e.g., `Home-IoT`)
   - Enable VLAN isolation

2. **Set up firewall rules** (advanced):
   - Prevent IoT devices from accessing your primary LAN
   - Allow IoT devices outbound to internet
   - Example (Linux): `sudo firewall-cmd --permanent --new-zone=iot && sudo firewall-cmd --reload`

3. **Move IoT devices** to the isolated network

4. **Verify isolation**:
   ```bash
   netglance discover
   ```

### Updating Firmware

1. **Check for router firmware updates**:
   - Router admin panel > **Administration > Firmware Update** or **System > Updates**
   - Click "Check for Updates"
   - If available, download and install
   - Router will reboot automatically

2. **Update access points and mesh nodes**:
   - Use the manufacturer's app or web interface
   - Check for updates regularly (monthly)

3. **Update IoT devices**:
   - Check each device's app or web interface for firmware updates

### Setting Up Static DHCP Leases

1. **Identify devices to pin**:
   - Router admin panel > **Connected Devices** or **DHCP Client List**
   - Note the MAC address and current IP

2. **Create static lease**:
   - Router admin panel > **DHCP > Static Leases** or **Advanced > DHCP Reservation**
   - Add: MAC address → desired IP (e.g., `192.168.1.100`)
   - Save and reboot

3. **Verify**:
   ```bash
   netglance discover
   ```

---

## Certificate Issues

### Understanding Self-Signed Certificate Warnings

1. **Determine if the certificate is yours**:
   - Check the certificate subject (CN field)
   - If it's your home server's hostname, it's safe to ignore

2. **Temporarily trust the certificate** (macOS):
   - Open the certificate file in Keychain Access
   - Right-click > Get Info
   - Expand "Trust" section
   - Set "When using this certificate" to **Always Trust**

3. **Or**, create a local CA and sign certificates:
   - Use `mkcert` (easiest): `mkcert -install && mkcert localhost 192.168.1.100`
   - Add the generated `.crt` to your system's trusted root CAs

### Renewing Expiring Certificates

1. **Identify expiring certificates**:
   ```bash
   netglance tls check <server-ip>:<port>
   ```

2. **Renew via Let's Encrypt** (if public domain):
   ```bash
   certbot renew --force-renewal
   ```

3. **Renew self-signed certificates**:
   ```bash
   openssl req -x509 -newkey rsa:4096 -out cert.pem -outform PEM -keyout key.pem -days 365 -nodes
   ```

4. **Update the server** to use the new certificate files

5. **Verify**:
   ```bash
   netglance tls check <server-ip>:<port>
   ```

---

## Getting Help

If a remediation doesn't work or you're unsure about a step:

- Run `netglance --help` to see all available commands
- Run `netglance <module> --help` for module-specific options
- Check the [Documentation](../../reference/index.md) for detailed command syntax

# Is My Internet Actually Slow?

> Netflix is buffering. Your video call keeps freezing. Pages take forever to load. Before you call your ISP and spend 45 minutes on hold, let's figure out what's really going on — and whether the problem is your internet, your WiFi, or something else entirely.

<!-- TODO: Hero image — generate with prompt: "Split illustration showing frustrated person at laptop with buffering icon on screen (left side) vs same person smiling with fast connection (right side), minimal flat style, warm colors" -->

## The three things that matter

When people say "my internet is slow," the problem is usually one of three things:

```mermaid
graph LR
    Device["Your Device"] -->|"WiFi Signal"| Router["Router"]
    Router -->|"Your Connection"| ISP["ISP"]
    ISP -->|"The Internet"| Server["Website/Service"]

    style Device fill:#4a90d9,color:#fff
    style Router fill:#f5a623,color:#fff
    style ISP fill:#7b68ee,color:#fff
    style Server fill:#4caf50,color:#fff
```

1. **Speed** — How much data can flow through per second (like the width of a pipe)
2. **Latency** — How long it takes data to make a round trip (like the length of the pipe)
3. **Stability** — Whether the connection stays consistent or fluctuates (like water pressure)

A connection can be fast but laggy (high speed, high latency — fine for downloads, bad for video calls). Or it can be responsive but slow (low speed, low latency — fine for browsing, bad for streaming). Let's measure all three.

## Step 1: Test your speed

```bash
netglance speed
```

```
Speed Test Results
──────────────────────────────────────────────────
Download:    87.3 Mbps
Upload:      11.2 Mbps
Latency:     14 ms
Server:      Speedtest.net (Sydney)
```

**How to read this:**

| Metric | Good | Acceptable | Poor |
|--------|------|-----------|------|
| Download | 100+ Mbps | 25-100 Mbps | Under 25 Mbps |
| Upload | 20+ Mbps | 5-20 Mbps | Under 5 Mbps |
| Latency | Under 20 ms | 20-50 ms | Over 50 ms |

!!! tip "Compare against your plan"
    If you're paying for 100 Mbps and only getting 50 Mbps, that's a problem. If you're paying for 50 Mbps and getting 47 Mbps, that's normal — you rarely get the full advertised speed.

**What different speeds actually feel like:**

- **5 Mbps** — one person can stream standard-def video
- **25 Mbps** — one person can stream 4K, or a small household can browse comfortably
- **100 Mbps** — a household can stream, game, and video call simultaneously
- **500+ Mbps** — you'll never notice speed as a bottleneck

## Step 2: Check latency and jitter

Speed isn't everything. For video calls and gaming, latency and stability matter more:

```bash
netglance ping 8.8.8.8
```

```
Ping Results — 8.8.8.8 (Google DNS)
──────────────────────────────────────────────────
Packets:     20 sent, 20 received, 0% loss
Latency:     min 12ms, avg 15ms, max 23ms
Jitter:      3.2 ms
```

**What the numbers mean:**

- **Latency (avg)** — the time for a round trip. Under 50ms is good for most things. Under 20ms is great for gaming.
- **Jitter** — how much the latency varies. Under 5ms is stable. Over 20ms means choppy video calls.
- **Packet loss** — data that never arrived. Even 1% loss causes noticeable problems. 0% is what you want.

## Step 3: Test for bufferbloat

Bufferbloat is a sneaky problem: your connection seems fast on a speed test, but feels terrible when multiple people use it at once. It happens when your router's buffers are too large, causing huge latency spikes under load.

```bash
netglance perf --bufferbloat
```

```
Bufferbloat Test
──────────────────────────────────────────────────
Idle latency:        15 ms
Latency under load:  340 ms    ← this is the problem
Bufferbloat grade:   F
```

**What the grades mean:**

- **A** (under 5ms increase) — excellent, no bufferbloat
- **B** (5-30ms increase) — minor, barely noticeable
- **C** (30-60ms increase) — moderate, may notice during heavy use
- **D-F** (60ms+ increase) — severe, video calls drop during downloads

!!! note "Fixing bufferbloat"
    If you score D or F, enable **SQM (Smart Queue Management)** on your router. Many routers support this in their QoS settings. It's the single most impactful change for a busy household.

## Step 4: Trace the route

If things are slow, find out where the bottleneck is:

```bash
netglance route 8.8.8.8
```

```
Traceroute to 8.8.8.8
──────────────────────────────────────────────────
 1  192.168.1.1      1 ms    ← your router
 2  10.0.0.1         8 ms    ← ISP local
 3  172.16.50.1     15 ms    ← ISP regional
 4  72.14.236.1     14 ms    ← Google edge
 5  8.8.8.8         15 ms    ← destination
```

**What to look for:**

- **Big jump at hop 1** — problem is your WiFi or router
- **Big jump at hop 2-3** — problem is your ISP's local infrastructure
- **Big jump mid-path** — congestion somewhere in the internet backbone
- **Steady increase** — normal, distance takes time

```mermaid
graph LR
    You["You<br/>0 ms"] -->|"1 ms"| Router["Router"]
    Router -->|"+7 ms"| ISP["ISP"]
    ISP -->|"+7 ms"| Regional["ISP Regional"]
    Regional -->|"+90 ms !"| Backbone["Backbone"]
    Backbone -->|"+5 ms"| Dest["Destination"]

    style Backbone fill:#ff6b6b,color:#fff
```

In this example, the big jump at the backbone means congestion outside your control — but at least you know it's not your home network.

## Step 5: Check if it's your WiFi

Sometimes the internet is fine but WiFi is the bottleneck. Test from a wired connection vs WiFi:

```bash
# Check WiFi signal and channel congestion
netglance wifi
```

```
WiFi Environment
──────────────────────────────────────────────────
Your network:    MyHomeWiFi
Signal:          -68 dBm (fair)
Channel:         6 (congested — 5 networks)
Frequency:       2.4 GHz
```

**WiFi signal strength guide:**

| Signal | Quality | Typical experience |
|--------|---------|-------------------|
| -30 to -50 dBm | Excellent | Right next to the router |
| -50 to -60 dBm | Good | Same room or one room away |
| -60 to -70 dBm | Fair | Through a wall or two |
| -70 to -80 dBm | Weak | Far from router, streaming will buffer |
| Below -80 dBm | Unusable | Connection drops constantly |

**Common WiFi fixes:**

1. **Switch to 5 GHz** — faster but shorter range. Great if you're in the same room.
2. **Change your channel** — if 5 other networks share your channel, switch to a less crowded one.
3. **Move your router** — central location, elevated, away from microwaves and thick walls.
4. **Get a mesh system** — if your home is large or has thick walls.

## Diagnosing common problems

### "Netflix buffers but speed test says 100 Mbps"
This is almost always **bufferbloat** or **WiFi congestion**. Run `netglance perf --bufferbloat` and check your WiFi signal.

### "Video calls keep freezing"
Check **jitter** with `netglance ping`. Video calls need low, stable latency — they're more sensitive to jitter than raw speed. Also check if someone else is downloading.

### "It's slow at certain times of day"
Run `netglance speed` at different times. If it's consistently slow from 7-10 PM, your ISP is likely congested. This is common with cable internet.

### "One device is slow, others are fine"
The problem is that device's WiFi connection, not your internet. Check `netglance wifi` from that device, or move it closer to the router.

### "Everything was fine until recently"
Run `netglance baseline diff` to see what changed. A new device might be hogging bandwidth, or your ISP may have changed something.

## Quick reference

| What you want to know | Command |
|-----------------------|---------|
| Download/upload speed | `netglance speed` |
| Latency and packet loss | `netglance ping 8.8.8.8` |
| Bufferbloat | `netglance perf --bufferbloat` |
| Where the bottleneck is | `netglance route 8.8.8.8` |
| WiFi signal quality | `netglance wifi` |
| Bandwidth per device | `netglance traffic` |

## Next steps

- [Keep My Network Healthy](keep-my-network-healthy.md) — set up continuous speed and latency monitoring so you can track trends and catch problems early
- [What's on My Network?](whats-on-my-network.md) — find the device that's hogging all the bandwidth

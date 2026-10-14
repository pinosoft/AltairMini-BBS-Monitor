# AltairMini BBS Monitor – Mystic Edition

A lightweight, read-only web dashboard for monitoring a Mystic BBS. Separate packages are provided for **Windows** and **Ubuntu/Linux**. The dashboard summarizes node activity, sessions, countries, inbound network/file activity, BinkP/block events, and detected nodelist files. It includes **Today**, **Yesterday**, historical ranges, a 30-day activity chart, and a blue Live Ticker flash when displayed data changes.

**Author:** AltairMini + Pino Convertino  
**License:** GNU General Public License v3.0 (GPL-3.0)

> This project is community software and is not affiliated with or endorsed by the authors of Mystic BBS.

## Downloads

### Windows

Use the repository's **Code → Download ZIP** option to download the Windows project files, or browse the repository for the Windows launcher and documentation.

- Intended for a Windows PC running Mystic BBS.
- Includes `START_MONITOR.bat`.
- Windows 7 users should use Python 3.8.10, the last official Python release supporting Windows 7. Windows 10/11 users should use a currently supported Python 3 release.

### Ubuntu / Linux

Download the Linux package from the GitHub Release:

**[AltairMini BBS Monitor – Linux Edition (linux-v1.0.0)](https://github.com/pinosoft/AltairMini-BBS-Monitor/releases/tag/linux-v1.0.0)**

The Linux package is an initial adaptation. It has passed a Python syntax check but **has not yet been tested against a live Mystic Linux installation**. Log formats and directory layouts may differ, so please test with your own installation and report issues.

## Features

- Runs on the same computer as Mystic BBS; no separate collector is required.
- Reads Mystic log files without modifying them.
- Dashboard refreshes automatically every 15 seconds.
- Date ranges: Today, Yesterday, Last 7 days, Last 30 days, and All available history.
- 30-day daily activity chart.
- Network summaries for FidoNet, FSXNet, Commodore Net, RetroNet, DiscipleNet, PiNet, and AgoraNet.
- Countries, recent sessions, inbound packet/file summaries, and recent BinkP/block events.
- Nodelist file listing with filename, last-modified timestamp, and size.
- Blue Live Ticker flash for changed values/rows.

## Windows quick start

1. Download the repository ZIP (**Code → Download ZIP**) and extract it on the Mystic PC, for example to `C:\AltairMini_BBS_Monitor`.
2. Open `dashboard.py` in a text editor and confirm `LOG_DIR` points to the Mystic log directory. The default is:
   ```python
   LOG_DIR = Path(r"C:\mystic\logs")
   ```
3. Double-click `START_MONITOR.bat`.
4. On the Mystic PC, open <http://127.0.0.1:8765/>.
5. For access from another device on a trusted LAN/VPN, use `http://MYSTIC-PC-IP:8765/`, replacing `MYSTIC-PC-IP` with the PC's LAN IPv4 address.

Keep the console window open while the monitor is running. Stop it with `Ctrl+C`.

## Ubuntu / Linux quick start

1. Download `AltairMini-BBS-Monitor-Linux.zip` from the [Linux release](https://github.com/pinosoft/AltairMini-BBS-Monitor/releases/tag/linux-v1.0.0).
2. Extract it and enter the extracted directory:
   ```bash
   unzip AltairMini-BBS-Monitor-Linux.zip
   cd AltairMini-BBS-Monitor-Linux
   ```
3. Set the actual path to your Mystic logs and start the monitor:
   ```bash
   export MYSTIC_LOG_DIR=/path/to/mystic/logs
   ./start_linux.sh
   ```
4. On the Linux computer, open <http://127.0.0.1:8765/>.

The Linux package requires Python 3.8 or newer and read permission for the Mystic log directory. No third-party Python packages are required. See `README-LINUX.md` inside the Linux package for environment variables and the optional `systemd` service example.

## Configuration

### Windows

The stable Windows build uses these defaults near the top of `dashboard.py`:

```python
LOG_DIR = Path(r"C:\mystic\logs")
HOST = "0.0.0.0"
PORT = 8765
```

Change `LOG_DIR` if Mystic stores logs elsewhere, or `PORT` if port 8765 is already in use. Use `HOST = "127.0.0.1"` to restrict access to the same computer.

### Ubuntu / Linux

The Linux package uses environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MYSTIC_LOG_DIR` | `/home/mystic/logs` | Directory containing `node*.log`, `poll.log`, and `mis.log` |
| `MONITOR_HOST` | `127.0.0.1` | Interface to bind; use `0.0.0.0` only for a trusted LAN/VPN |
| `MONITOR_PORT` | `8765` | HTTP listen port |

For trusted LAN/VPN access only:

```bash
MONITOR_HOST=0.0.0.0 MYSTIC_LOG_DIR=/path/to/mystic/logs ./start_linux.sh
```

The nodelist scanner's search path depends on the package version and directory layout. If nodelists are not shown, check the relevant platform README and the scan path in the code.

## Network and security

**This dashboard has no login or password and uses plain HTTP.** Anyone who can reach the listening port may be able to view the dashboard.

- Prefer access from the same computer or a trusted private LAN/VPN.
- Restrict firewall access to trusted addresses.
- **Do not configure router port forwarding or expose TCP port 8765 directly to the Internet.**
- For remote access, use a VPN or another properly secured private access method.
- Do not commit real Mystic logs, user names, IP addresses, message contents, or other private BBS data to this public repository.

## Troubleshooting

- **No logs or empty statistics:** verify the log directory and confirm the expected `node*.log`, `poll.log`, and `mis.log` files exist there.
- **Port already in use:** change the configured port or stop the application using it.
- **Cannot connect from another device:** verify the PC's LAN IP, bind address, VPN route, and firewall rules. Do not use router port forwarding.
- **Nodelists not listed:** check the nodelist scan path and the directory layout used by your installation.
- **Browser appears unchanged after an update:** use `Ctrl+F5` to force a refresh.
- **Linux statistics do not match Mystic activity:** the Linux package has not yet been validated against every Mystic Linux log format; please report an issue with sanitized examples, never private logs.

## License

Distributed under the GNU General Public License v3.0. See [`LICENSE`](LICENSE).

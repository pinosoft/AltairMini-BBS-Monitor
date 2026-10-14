# AltairMini BBS Monitor – Mystic Edition

A lightweight, read-only web dashboard for monitoring a Mystic BBS on Windows. It summarizes node activity, sessions, countries, inbound network/file activity, BinkP/block events, and detected nodelist files. The dashboard includes **Today**, **Yesterday**, historical ranges, a 30-day activity chart, and a blue Live Ticker flash when displayed data changes.

**Author:** AltairMini + Pino Convertino  
**License:** GNU General Public License v3.0 (GPL-3.0)

> This project is community software and is not affiliated with or endorsed by the authors of Mystic BBS.

## Features

- Runs on the same Windows PC as Mystic BBS; no second PC or shared-folder collector is required.
- Reads Mystic log files without modifying them.
- Dashboard refreshes automatically every 15 seconds.
- Date ranges: Today, Yesterday, Last 7 days, Last 30 days, and All available history.
- 30-day daily activity chart.
- Network summaries for FidoNet, FSXNet, Commodore Net, RetroNet, DiscipleNet, PiNet, and AgoraNet.
- Countries, recent sessions, inbound packet/file summaries, and recent BinkP/block events.
- Nodelist file listing with filename, last-modified timestamp, and size.
- Blue Live Ticker flash for changed values/rows.
- Python standard library only; no `pip install` step.

## Requirements

- Windows PC running Mystic BBS.
- Python 3.
  - Windows 7: Python 3.8.10 is the last official Python release supporting Windows 7.
  - Windows 10/11: a current supported Python 3 release is recommended.
- Read access to the Mystic log directory.

## Quick start

1. Download the repository ZIP from GitHub (**Code → Download ZIP**) and extract it on the Mystic PC, for example to `C:\AltairMini_BBS_Monitor`.
2. Open `dashboard.py` in a text editor and confirm `LOG_DIR` points to your Mystic log directory. The default is:
   ```python
   LOG_DIR = Path(r"C:\mystic\logs")
   ```
3. Double-click `START_MONITOR.bat`.
4. On the Mystic PC, open <http://127.0.0.1:8765/>.
5. To open it from another computer on the same trusted LAN, use `http://MYSTIC-PC-IP:8765/`, replacing `MYSTIC-PC-IP` with the Mystic PC's LAN IPv4 address.

Keep the console window open while the monitor is running. Stop it with `Ctrl+C`.

## Configuration

The current stable build uses these defaults near the top of `dashboard.py`:

```python
LOG_DIR = Path(r"C:\mystic\logs")
HOST = "0.0.0.0"
PORT = 8765
```

- Change `LOG_DIR` if Mystic stores logs in another directory.
- Change `PORT` if TCP port 8765 is already in use.
- `HOST = "0.0.0.0"` lets other devices on the LAN connect. For access from only the same PC, use `HOST = "127.0.0.1"`.

The nodelist display scans `C:\mystic` and one folder level below it in this build. If your nodelists are stored elsewhere, adjust the scan path in `dashboard.py`.

## Network and security notes

**This dashboard has no login or password.** The web server listens on all network interfaces by default (`0.0.0.0:8765`), so anyone who can reach that port on your network may be able to view the dashboard.

- Prefer access from the same PC or a trusted private LAN.
- Restrict the Windows Firewall inbound rule for TCP 8765 to the Private profile and `LocalSubnet`.
- **Do not configure router port forwarding or expose this port directly to the Internet.**
- Do not commit real Mystic logs, user names, IP addresses, message contents, or other private BBS data to this public repository.
- If you need remote access, use a VPN or another properly secured private access method.

## Performance notes

The node-log cache reads existing logs on first startup and then processes appended data incrementally. The first load may take longer on a large BBS history. Keep the server window open during operation.

## Troubleshooting

- **No logs or empty statistics:** verify `LOG_DIR` and confirm the expected `node*.log`, `poll.log`, and `mis.log` files exist there.
- **Port already in use:** change `PORT` in `dashboard.py` or stop the other application using that port.
- **Cannot connect from another LAN device:** verify the Mystic PC's LAN IP and the Windows Firewall rule. Do not use router port forwarding.
- **Nodelists not listed:** check the scan path described under Configuration.
- **Browser appears unchanged after an update:** use `Ctrl+F5` to force a refresh.

## Repository contents

- `dashboard.py` — dashboard HTML, log parsing, statistics, and nodelist discovery.
- `run_monitor.py` — local HTTP server and statistics cache.
- `START_MONITOR.bat` — Windows launcher.
- `README.md` — this documentation.
- `LICENSE` — GPL-3.0 license.
- `SECURITY.md` — security reporting guidance.
- `CONTRIBUTING.md` — contribution notes.
- `.gitignore` — excludes logs, local configuration, and generated Python files.

## License

Distributed under the GNU General Public License v3.0. See [`LICENSE`](LICENSE).

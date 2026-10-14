ALTAIRMINI BBS MONITOR - MYSTIC PC EDITION
==========================================

This version runs directly on the PC hosting Mystic BBS. It reads logs from:
    C:\mystic\logs

No shared-folder collector or second PC is required.

FEATURES PRESERVED
------------------
- Existing AltairMini BBS Monitor dashboard and layout
- Today selected by default
- Last 7 days, Last 30 days, and All available history options
- Automatic refresh every 15 seconds
- FidoNet, FSXNet, Commodore Net, RetroNet, DiscipleNet, PiNet and AgoraNet
- Node log statistics, country information, inbound file/network statistics
- poll.log historical data and live BINKP events from mis.log
- Nodelist file name, last-modified date/time, and size (scans C:\\mystic and one folder level below)
- Read-only dashboard; does not modify Mystic logs
- Web server listens on all network interfaces, port 8765

INSTALL / RUN
-------------
1. Copy this folder to the Mystic PC, for example:
       C:\AltairMini_BBS_Monitor
2. Confirm Mystic logs are in C:\mystic\logs and include node*.log, poll.log
   and mis.log (where available).
3. Double-click START_MONITOR.bat.
4. On the Mystic PC, open:
       http://127.0.0.1:8765/
5. From another PC on the same LAN, open:
       http://MYSTIC-PC-IP:8765/
   Replace MYSTIC-PC-IP with the local IPv4 address of the Mystic PC.

PYTHON
------
The monitor uses only Python's standard library; no pip packages are needed.
- Windows 10/11: install a current Python 3 release if Python is missing.
- Windows 7: Python 3.8.10 is the last official Python release supporting it.
During installation, enable "Add Python to PATH" if that option is shown.

LAN FIREWALL
------------
If other LAN PCs cannot open the page, create an inbound Windows Firewall rule
for TCP port 8765 restricted to the Private profile / LocalSubnet.
Do not configure port forwarding on the router.

AUTOSTART (OPTIONAL)
--------------------
Use Windows Task Scheduler on the Mystic PC:
- Create Task...
- General: name it AltairMini BBS Monitor; use the same Windows account that
  can read C:\mystic\logs.
- Triggers: At startup (or At log on if the logs/network are not ready at boot).
- Actions: Start a program
  Program/script: C:\Windows\System32\cmd.exe
  Add arguments: /c "C:\AltairMini_BBS_Monitor\START_MONITOR.bat"
  (adjust the folder path if you copied it elsewhere)
- For initial testing, run START_MONITOR.bat manually first.

TROUBLESHOOTING
---------------
- If the page reports no logs, verify the path C:\mystic\logs and filenames.
- If port 8765 is already in use, the server will report an error in its window.
- Keep the console window open while the monitor is running.


PERFORMANCE UPDATE
------------------
This build adds an incremental cache for node*.log files. On first run it reads
existing logs; later requests read only newly appended bytes, while date ranges
are filtered from cached sessions. If a node log is truncated, that file is
rescanned. Keep the server window open while the monitor runs.

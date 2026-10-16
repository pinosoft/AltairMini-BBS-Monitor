
from pathlib import Path
from datetime import datetime, date, timedelta
import re, json, time

LOG_DIR = Path(r"C:\mystic\logs")
HOST = "0.0.0.0"
PORT = 8765

STAMP = re.compile(r"^\s*\+?\s*(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.*)$")
CONNECT = re.compile(r"Connect from\s+([0-9a-fA-F:.]+)(?:\s+\((.*?)\))?", re.I)
COUNTRY = re.compile(r"Country:\s*(.+?)\s*$", re.I)
LOGIN = re.compile(r"(.+?)\s+logged in\s*$", re.I)

def parse_line(line):
    # Faster than strptime for the fixed Mystic timestamp format.
    m = STAMP.match(line)
    if not m: return None, ""
    try:
        y, mo, d = (int(part) for part in m.group(1).split("."))
        hh, mm, ss = (int(part) for part in m.group(2).split(":"))
        return datetime(y, mo, d, hh, mm, ss), m.group(3)
    except (ValueError, TypeError):
        return None, ""

# Mystic mis.log uses a leading "+ DD.MM.YYYY HH:MM:SS" timestamp.
# Accept both that format and the ISO-like format used by some log versions.
_MIS_STAMP = re.compile(
    r"^\s*\+?\s*(\d{2}\.\d{2}\.\d{4}|\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.*)$"
)
def _parse_mis_timestamp(line):
    m = _MIS_STAMP.match(line)
    if not m:
        return None, line.strip()
    try:
        parts = [int(part) for part in m.group(1).split(".")]
        if len(m.group(1).split(".")[0]) == 4:
            year, month, day = parts
        else:
            day, month, year = parts
        hh, mm, ss = (int(part) for part in m.group(2).split(":"))
        return datetime(year, month, day, hh, mm, ss), m.group(3)
    except (ValueError, TypeError):
        return None, m.group(3)


# Incremental cache for mis.log: parse existing lines once, then only appended bytes.
_MIS_CACHE = {
    "offset": 0, "pending": b"", "records": [], "current_remote_network": {},
    "blocked": 0, "binkp": 0, "events": [], "available": False,
    "last_size": 0, "initialized": False,
}
_MIS_CACHE_LOCK = __import__("threading").RLock()

_RX_MIS_RECEIVED = re.compile(
    r"^\s*\+\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}:\d{2}).*?BINKP\s+(\d+)-Received:\s*(.*?)\s*\(([\d,]+)\s+bytes",
    re.I,
)
_RX_REMOTE_ADR = re.compile(r"BINKP\s+(\d+)-R:\s*ADR\s+.*", re.I)
_RX_AUTH = re.compile(r"BINKP\s+(\d+)-Authenticating\s+.*?@([A-Z0-9_-]+)", re.I)
_RX_BOUNDARY = re.compile(r"BINKP\s+(\d+)-(?:Connect on slot|Session ended)", re.I)
_NETWORK_NAMES = {
    "FSXNET": "FSXNet", "FIDONET": "FidoNet", "CNET": "Commodore Net",
    "RETRONET": "RetroNet", "DISCIPLE": "DiscipleNet", "PINET": "PiNet",
    "AGORANET": "AgoraNet",
}

def _parse_mis_line(line):
    """Update the persistent mis.log cache with one complete decoded line.

    Fast-path ordinary log lines before running BINKP-specific regular expressions.
    """
    cache = _MIS_CACHE
    low = line.lower()

    # Security/session event counters are independent of BINKP transfer parsing.
    is_blocked = "blocked connection" in low
    is_binkp_event = "binkp" in low and ("connect on slot" in low or "session ended" in low)
    if is_blocked or is_binkp_event:
        # Parse the actual mis.log date format (DD.MM.YYYY, often prefixed by '+').
        dt, msg = _parse_mis_timestamp(line)
        # Count only dated events so period filtering is accurate.
        if dt and is_blocked:
            cache["blocked"] += 1
            cache["events"].append({"time": dt.isoformat(timespec="seconds"), "type": "Blocked connection", "detail": msg})
        if dt and is_binkp_event:
            cache["binkp"] += 1
            cache["events"].append({"time": dt.isoformat(timespec="seconds"), "type": "BinkP event", "detail": msg})

    # Almost all Mystic log lines do not contain BINKP; skip all slot/transfer
    # regular expressions for those lines.
    if "binkp" not in low:
        return

    if "connect on slot" in low or "session ended" in low:
        boundary = _RX_BOUNDARY.search(line)
        if boundary:
            cache["current_remote_network"].pop(boundary.group(1), None)

    if "-r: adr" in low:
        adr = _RX_REMOTE_ADR.search(line)
        if adr:
            slot = adr.group(1)
            tags = {tag.upper() for tag in re.findall(r"@([A-Z0-9_-]+)", line, re.I)}
            cache["current_remote_network"][slot] = next(iter(tags)) if len(tags) == 1 else None

    if "authenticating" in low:
        auth = _RX_AUTH.search(line)
        if auth:
            cache["current_remote_network"][auth.group(1)] = auth.group(2).upper()

    if "-received:" in low:
        m = _RX_MIS_RECEIVED.search(line)
        if m:
            try:
                day, mo, year = (int(part) for part in m.group(1).split("."))
                hh, mm, ss = (int(part) for part in m.group(2).split(":"))
                stamp = datetime(year, mo, day, hh, mm, ss)
            except ValueError:
                stamp = None
            if stamp:
                try:
                    size = int(m.group(5).replace(",", ""))
                except ValueError:
                    size = 0
                slot = m.group(3)
                filename = m.group(4).strip()
                peer_net = _NETWORK_NAMES.get(cache["current_remote_network"].get(slot))
                cache["records"].append((stamp, filename, size, peer_net))

def _refresh_mis_cache():
    """Read only new bytes from mis.log; reset safely if the log was truncated."""
    path = LOG_DIR / "mis.log"
    cache = _MIS_CACHE
    t0 = time.perf_counter()
    with _MIS_CACHE_LOCK:
        if not path.exists():
            cache["available"] = False
            return time.perf_counter() - t0
        try:
            size = path.stat().st_size
            if (not cache["initialized"]) or (not cache["available"]) or size < cache["offset"]:
                cache.update({"offset": 0, "pending": b"", "records": [], "current_remote_network": {},
                              "blocked": 0, "binkp": 0, "events": [], "initialized": True})
            cache["available"] = True
            if size > cache["offset"]:
                with path.open("rb") as f:
                    f.seek(cache["offset"])
                    chunk = f.read()
                cache["offset"] += len(chunk)
                data = cache["pending"] + chunk
                pieces = data.splitlines(keepends=True)
                cache["pending"] = b""
                for i, raw in enumerate(pieces):
                    complete = raw.endswith(b"\n") or raw.endswith(b"\r")
                    if not complete and i == len(pieces) - 1:
                        cache["pending"] = raw
                        continue
                    _parse_mis_line(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            cache["last_size"] = size
        except OSError:
            cache["available"] = False
    return time.perf_counter() - t0

def read_network_receipts(period_start=None, period_end=None):
    """Count poll.log baseline plus newer cached BINKP Received events from mis.log."""
    counts, latest = {}, {}
    total = bytes_total = 0
    poll_path = LOG_DIR / "poll.log"
    mis_path = LOG_DIR / "mis.log"
    poll_latest = None

    def network_for(filename):
        n = filename.upper()
        if "FIDONET" in n or n.endswith(".PKT"): return "FidoNet"
        if "FSXNET" in n or n.startswith("FSX"): return "FSXNet"
        if "DISCIPLE" in n or n.startswith("DNET"): return "DiscipleNet"
        if "AGORANET" in n or n.startswith("AGORA"): return "AgoraNet"
        if "PINET" in n or n.startswith("PIPK") or n.startswith("PI"): return "PiNet"
        if "RETRONET" in n or n.startswith("RTNPCK") or n.startswith("RTRPK") or n.startswith("RTR"): return "RetroNet"
        if "CNET" in n or n.startswith("CNTPK") or n.startswith("CNET"): return "Commodore Net"
        return "Other / Unidentified"

    def add(stamp, filename, size, network_override=None):
        nonlocal total, bytes_total
        if period_start and stamp < period_start: return
        if period_end and stamp >= period_end: return
        net = network_override or network_for(filename)
        counts[net] = counts.get(net, 0) + 1
        latest[net] = max(latest.get(net, stamp), stamp)
        total += 1
        bytes_total += size

    poll_t0 = time.perf_counter()
    if poll_path.exists():
        rx_poll = re.compile(r"^\s*\+\s+(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2}).*?Received:\s*(.*?)\s*\(([\d,]+)\s+bytes", re.I)
        try:
            with poll_path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = rx_poll.search(line)
                    if not m: continue
                    try:
                        y, mo, d = (int(part) for part in m.group(1).split("."))
                        hh, mm, ss = (int(part) for part in m.group(2).split(":"))
                        stamp = datetime(y, mo, d, hh, mm, ss)
                    except ValueError: continue
                    poll_latest = max(poll_latest, stamp) if poll_latest else stamp
                    try: size = int(m.group(4).replace(",", ""))
                    except ValueError: size = 0
                    add(stamp, m.group(3).strip(), size)
        except OSError: pass
    poll_elapsed = time.perf_counter() - poll_t0

    receipt_mis_elapsed = _refresh_mis_cache()
    with _MIS_CACHE_LOCK:
        records = list(_MIS_CACHE["records"])
        mis_available = _MIS_CACHE["available"]
    for stamp, filename, size, peer_net in records:
        if poll_latest and stamp <= poll_latest: continue
        add(stamp, filename, size, peer_net)
    print("TIMING receipts: poll.log={:.2f}s; mis.log incremental={:.2f}s; cached records={}".format(poll_elapsed, receipt_mis_elapsed, len(records)), flush=True)

    if not poll_path.exists() and not mis_available:
        return {"available": False, "total": 0, "bytes": 0, "networks": [], "latest": {}}
    networks = [{"name": k, "count": v, "percent": round(v * 100 / total, 1) if total else 0,
                 "latest": latest[k].isoformat(timespec="seconds")}
                for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"available": True, "total": total, "bytes": bytes_total, "networks": networks, "latest": latest}

# Incremental cache for node*.log files. Existing sessions are retained in memory;
# subsequent requests process only bytes appended since the previous refresh.
_NODE_CACHE = {}
_NODE_CACHE_LOCK = __import__("threading").RLock()

def _parse_node_line(path, line, state):
    dt, msg = parse_line(line)
    if dt is None:
        return
    m = CONNECT.search(msg)
    if m:
        current = {"node": path.stem, "ip": m.group(1), "host": m.group(2) or "",
                   "country": "", "protocol": "Unknown",
                   "connected_at": dt.isoformat(timespec="seconds"), "login_at": None,
                   "user": "", "ended_at": None,
                   "end_reason": "No end event recorded"}
        state["sessions"].append(current)
        state["current"] = current
        return
    current = state.get("current")
    if current is None:
        return
    c = COUNTRY.search(msg)
    if c:
        current["country"] = c.group(1).strip()
    if "Connection by " in msg:
        current["protocol"] = msg.split("Connection by ", 1)[1].strip()
    l = LOGIN.search(msg)
    if l and l.group(1).strip().lower() != "user":
        current["user"] = l.group(1).strip()
        current["login_at"] = dt.isoformat(timespec="seconds")
    if "User logged off" in msg:
        current["ended_at"] = dt.isoformat(timespec="seconds")
        current["end_reason"] = "Logged off"
    elif "User dropped connection" in msg:
        current["ended_at"] = dt.isoformat(timespec="seconds")
        current["end_reason"] = "Dropped connection"
    elif "Shutting down" in msg and not current["ended_at"]:
        current["ended_at"] = dt.isoformat(timespec="seconds")
        current["end_reason"] = "Shutdown"

def _refresh_node_cache(files):
    """Refresh each node log incrementally and return cached session objects."""
    errors = []
    with _NODE_CACHE_LOCK:
        active = {str(path.resolve()).lower() for path in files}
        # Drop cache entries for logs that no longer exist.
        for key in list(_NODE_CACHE):
            if key not in active:
                del _NODE_CACHE[key]
        for path in files:
            key = str(path.resolve()).lower()
            try:
                size = path.stat().st_size
                state = _NODE_CACHE.get(key)
                if state is None or size < state["offset"]:
                    state = {"offset": 0, "pending": b"", "sessions": [], "current": None}
                    _NODE_CACHE[key] = state
                if size > state["offset"]:
                    with path.open("rb") as f:
                        f.seek(state["offset"])
                        chunk = f.read()
                    state["offset"] += len(chunk)
                    pieces = (state["pending"] + chunk).splitlines(keepends=True)
                    state["pending"] = b""
                    for i, raw in enumerate(pieces):
                        complete = raw.endswith(b"\n") or raw.endswith(b"\r")
                        if not complete and i == len(pieces) - 1:
                            state["pending"] = raw
                            continue
                        _parse_node_line(path, raw.decode("utf-8", errors="replace").rstrip("\r\n"), state)
            except Exception as e:
                errors.append(path.name + ": " + str(e))
        sessions = []
        for path in files:
            state = _NODE_CACHE.get(str(path.resolve()).lower())
            if state:
                sessions.extend(state["sessions"])
        return sessions, errors



def read_nodelist_files():
    """List only likely nodelist data files, excluding scripts, archives and monitor files."""
    root = LOG_DIR.parent
    if not root.exists():
        return []

    network_names = {
        "fidonet": "FidoNet",
        "fsxnet": "FSXNet",
        "agoranet": "AgoraNet",
        "pinet": "PiNet",
        "retronet": "RetroNet",
        "disciple": "DiscipleNet",
        "cnet": "Commodore Net",
        "commodore": "Commodore Net",
    }
    # Common nodelist formats: .NA, .Zxx, numeric point/revision suffixes,
    # plus explicitly named NODELIST.TXT. Avoid listing ZIPs, BATs, PY files, etc.
    valid_suffix = re.compile(r"^(?:\.na|\.z\d{2,3}|\.\d{3})$", re.IGNORECASE)
    found = []
    try:
        candidates = [root]
        candidates.extend(p for p in root.iterdir() if p.is_dir())
        for folder in candidates:
            try:
                for item in folder.iterdir():
                    if not item.is_file():
                        continue
                    name = item.name.lower()
                    suffix = item.suffix.lower()
                    is_explicit_nodelist = name.startswith("nodelist") and suffix in (".txt", ".na")
                    if not is_explicit_nodelist and not valid_suffix.match(suffix):
                        continue

                    # Restrict valid extensions to files whose basename identifies a known
                    # network, or explicitly named nodelists. This filters unrelated .Zxx files.
                    base = item.stem.lower()
                    network = next((label for token, label in network_names.items()
                                    if token in base), "")
                    if not is_explicit_nodelist and not network:
                        continue
                    if is_explicit_nodelist:
                        network = "Nodelist (unclassified)"
                    try:
                        st = item.stat()
                        found.append({
                            "name": item.name,
                            "network": network,
                            "path": str(item),
                            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                            "bytes": st.st_size
                        })
                    except OSError:
                        pass
            except OSError:
                continue
    except OSError:
        return []
    # Show the most recently modified nodelist files first. ISO timestamps sort chronologically.
    found.sort(key=lambda x: x["modified"], reverse=True)
    return found[:100]


# Incremental cache for file-download events found in node*.log.
_DOWNLOAD_LINE = re.compile(
    r"^\s*(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(?:Download|Downloaded):\s*(.+?)\s*$",
    re.I,
)
_DOWNLOAD_CACHE = {"signature": None, "events": []}
_DOWNLOAD_CACHE_LOCK = __import__("threading").RLock()

def _refresh_download_cache(files):
    signature = tuple((str(f), f.stat().st_size, f.stat().st_mtime_ns)
                      for f in files if f.exists())
    with _DOWNLOAD_CACHE_LOCK:
        if signature == _DOWNLOAD_CACHE["signature"]:
            return list(_DOWNLOAD_CACHE["events"])
        events = []
        for path in files:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        match = _DOWNLOAD_LINE.match(line)
                        if not match:
                            continue
                        try:
                            y, mo, d = (int(part) for part in match.group(1).split("."))
                            hh, mm, ss = (int(part) for part in match.group(2).split(":"))
                            when = datetime(y, mo, d, hh, mm, ss)
                        except ValueError:
                            continue
                        filename = match.group(3).strip()
                        if filename:
                            events.append({"time": when.isoformat(timespec="seconds"), "file": filename})
            except OSError:
                continue
        _DOWNLOAD_CACHE["signature"] = signature
        _DOWNLOAD_CACHE["events"] = events
        return list(events)

def build_stats(period="30"):
    _build_t0 = time.perf_counter()
    now = datetime.now()
    today_start = datetime.combine(date.today(), datetime.min.time())
    period_end = None
    if period == "today":
        start = today_start
    elif period == "yesterday":
        start = today_start - timedelta(days=1)
        period_end = today_start
    elif period in ("7", "30"):
        start = now - timedelta(days=int(period))
    else:
        start = None
    files = sorted(LOG_DIR.glob("node*.log")) if LOG_DIR.exists() else []
    _nodes_t0 = time.perf_counter()
    sessions, errors = _refresh_node_cache(files)
    _nodes_elapsed = time.perf_counter() - _nodes_t0
    visible = [s for s in sessions
               if (start is None or datetime.fromisoformat(s["connected_at"]) >= start)
               and (period_end is None or datetime.fromisoformat(s["connected_at"]) < period_end)]
    for s in visible:
        end = datetime.fromisoformat(s["ended_at"]) if s["ended_at"] else None
        begin = datetime.fromisoformat(s["connected_at"])
        s["duration_seconds"] = int((end-begin).total_seconds()) if end else None
        s["login_success"] = bool(s["login_at"])
        s["service"] = "BinkP" if "binkp" in s["protocol"].lower() else "Telnet" if "telnet" in s["protocol"].lower() else s["protocol"]
    visible.sort(key=lambda x:x["connected_at"], reverse=True)
    print("TIMING node logs incremental: {:.2f}s across {} files; cached sessions={}; selected={}".format(
        _nodes_elapsed, len(files), len(sessions), len(visible)), flush=True)
    countries = {}
    daily = {}
    for s in visible:
        country = s["country"] or "Unknown"; countries[country] = countries.get(country,0)+1
        day = s["connected_at"][:10]; daily.setdefault(day,{"date":day,"connections":0,"logins":0})
        daily[day]["connections"] += 1
        if s["login_success"]: daily[day]["logins"] += 1
    durations = [s["duration_seconds"] for s in visible if s["login_success"] and s["duration_seconds"] is not None]
    # Rank authenticated users by number of sessions in the selected period.
    user_session_counts = {}
    for session in visible:
        username = (session.get("user") or "").strip()
        if not session.get("login_success") or not username:
            continue
        key = username.casefold()
        if key not in user_session_counts:
            user_session_counts[key] = {"user": username, "sessions": 0}
        user_session_counts[key]["sessions"] += 1
    top_users = sorted(user_session_counts.values(),
                       key=lambda item: (-item["sessions"], item["user"].casefold()))[:10]
    # Rank downloaded files from Mystic node logs, using the selected period.
    download_events = _refresh_download_cache(files)
    file_download_counts = {}
    for event in download_events:
        try:
            event_time = datetime.fromisoformat(event["time"])
        except (KeyError, ValueError, TypeError):
            continue
        if start is not None and event_time < start:
            continue
        if period_end is not None and event_time >= period_end:
            continue
        filename = (event.get("file") or "").strip()
        if not filename:
            continue
        key = filename.casefold()
        if key not in file_download_counts:
            file_download_counts[key] = {"file": filename, "downloads": 0}
        file_download_counts[key]["downloads"] += 1
    top_files = sorted(file_download_counts.values(),
                       key=lambda item: (-item["downloads"], item["file"].casefold()))[:10]
    _mis_t0 = time.perf_counter()
    mis = LOG_DIR/"mis.log"
    _refresh_mis_cache()
    with _MIS_CACHE_LOCK:
        all_events = list(_MIS_CACHE["events"])
        mis_available = _MIS_CACHE["available"]
    # Apply the same selected-period window used by the dashboard to security events.
    visible_events = []
    for event in all_events:
        try:
            event_time = datetime.fromisoformat(event["time"])
        except (KeyError, ValueError, TypeError):
            continue
        if start is not None and event_time < start:
            continue
        if period_end is not None and event_time >= period_end:
            continue
        visible_events.append(event)
    blocked = sum(1 for event in visible_events if event.get("type") == "Blocked connection")
    binkp = sum(1 for event in visible_events if event.get("type") == "BinkP event")
    events = visible_events
    _mis_elapsed = time.perf_counter() - _mis_t0
    print("TIMING mis.log events/cache refresh: {:.2f}s".format(_mis_elapsed), flush=True)
    _network_t0 = time.perf_counter()
    network_stats = read_network_receipts(start, period_end)
    _network_elapsed = time.perf_counter() - _network_t0
    print("TIMING network receipts total: {:.2f}s".format(_network_elapsed), flush=True)
    print("TIMING build_stats total before response: {:.2f}s".format(time.perf_counter() - _build_t0), flush=True)
    # The activity chart always covers the last 30 calendar days, including
    # days with zero connections, so a single active day does not fill the chart.
    chart_today = now.date()
    chart_days = []
    for offset in range(29, -1, -1):
        day_date = chart_today - timedelta(days=offset)
        day_key = day_date.isoformat()
        chart_days.append(daily.get(day_key, {"date": day_key, "connections": 0, "logins": 0}))
    return {"generated_at":now.isoformat(timespec="seconds"),"log_dir":str(LOG_DIR),"file_count":len(files),
      "files":[{"name":p.name,"modified":datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),"bytes":p.stat().st_size} for p in files],
      "total_connections":len(visible),"successful_logins":sum(s["login_success"] for s in visible),
      "unique_ips":len(set(s["ip"] for s in visible)),"dropped":sum(s["end_reason"]=="Dropped connection" for s in visible),
      "closed":sum(s["end_reason"]=="Logged off" for s in visible),"unresolved":sum(not s["ended_at"] for s in visible),
      "avg_session_seconds":int(sum(durations)/len(durations)) if durations else None,
      "countries":[{"name":k,"count":v,"percent":round(v*100/len(visible),1) if visible else 0} for k,v in sorted(countries.items(),key=lambda kv:(-kv[1],kv[0]))],
      "daily":chart_days,"sessions":visible[:150],"top_users":top_users,"top_files":top_files,"blocked_attempts":blocked,"binkp_events":binkp,
      "mis_log_available":mis_available,"mis_events":sorted(events,key=lambda x:x["time"],reverse=True)[:30],"network_stats":{k:v for k,v in network_stats.items() if k != "latest"},"nodelists":read_nodelist_files(),"errors":errors}

HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AltairMini BBS Monitor — Mystic Edition</title>
<style>
:root{color-scheme:dark;--bg:#0b1116;--panel:#121c24;--line:#263844;--text:#e8f1f5;--muted:#9cb0bc;--green:#5ce0a0;--cyan:#64c7ef;--amber:#ffca70}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Segoe UI",Arial,sans-serif}header{padding:22px 26px;border-bottom:1px solid var(--line);background:#0e171e;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}h1{font-size:22px;margin:0}header p{color:var(--muted);margin:5px 0 0}select,button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 12px}main{max-width:1400px;margin:auto;padding:22px;display:grid;gap:18px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:17px}.klabel{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.8px}.value{font-size:30px;font-weight:700;margin-top:8px}.sub{font-size:12px;color:var(--muted);margin-top:5px}.layout{display:grid;grid-template-columns:1.1fr .9fr;gap:18px}.panel h2{font-size:15px;margin:0 0 14px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 7px;border-bottom:1px solid var(--line);font-size:12px;vertical-align:top}th{color:var(--muted)}.scroll{overflow:auto;max-height:390px}.pill{display:inline-block;border:1px solid var(--line);border-radius:99px;padding:2px 7px;font-size:11px;color:var(--cyan)}.barrow{display:grid;grid-template-columns:100px 1fr 60px;gap:9px;align-items:center;margin:10px 0;font-size:12px}.bar{height:9px;background:#24333e;border-radius:9px;overflow:hidden}.bar>i{display:block;height:100%;background:var(--green)}.chart{width:100%;height:180px;display:block}.note{border-left:3px solid var(--amber);padding:9px 12px;background:#1d2224;color:#d8d3c6;border-radius:4px}footer{color:var(--muted);font-size:12px}@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.layout{grid-template-columns:1fr}}@media(max-width:520px){main{padding:12px}.value{font-size:24px}}

/* Compact full-screen layout: prioritize fitting a standard 1080p display without page scrolling */
html,body{height:100%;overflow:hidden}
header{height:66px;padding:9px 18px;flex-wrap:nowrap}
h1{font-size:19px}header p{font-size:11px;margin-top:2px}
main{min-height:calc(100vh - 66px);height:auto;max-width:none;padding:10px 14px;gap:8px;grid-template-rows:22px 70px 70px 280px 280px auto 14px;overflow:visible}
body{overflow:auto}
.extra-panels{min-height:0;align-items:start}
.extra-panels .panel{min-height:150px;height:190px}
.events-table,.nodelists-table{height:125px;min-height:70px;overflow:auto;flex:1 1 auto}

.cards{gap:8px}
.card{padding:9px 12px;min-height:0}
.klabel{font-size:10px;letter-spacing:.5px}
.value{font-size:24px;margin-top:3px;line-height:1.1}
.sub{font-size:10px;margin-top:2px}
.layout{gap:9px;min-height:0;min-width:0}
.panel{padding:10px 12px;min-height:0;min-width:0;overflow:hidden}
.countries-panel{display:flex;flex-direction:column;min-height:0}.countries-panel h2{flex:none}.countries-list{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;padding-right:4px}.network-panel{display:flex;flex-direction:column;gap:4px}.network-panel h2{flex:none}.network-panel .sub{flex:none}.network-table{flex:0 0 auto;min-height:0;height:auto;overflow:visible}.network-table th,.network-table td{padding:2px 4px;font-size:9px;line-height:1.1}.events-title{margin:3px 0 0!important}.events-table{flex:0 0 66px;height:66px;min-height:66px;overflow:auto}.nodelists-title{margin:5px 0 0!important}.nodelists-table{flex:1 1 auto;min-height:45px;overflow:auto}.nodelists-table th,.nodelists-table td{padding:2px 4px;font-size:9px;line-height:1.1}.network-panel table{width:100%}
.panel h2{font-size:13px;margin-bottom:7px}
.layout:first-of-type .panel{min-height:0}
.chart{height:125px}
.barrow{grid-template-columns:85px 1fr 52px;gap:6px;margin:5px 0;font-size:10px}
.scroll{max-height:none;height:calc(100% - 25px);overflow:auto}
table{table-layout:auto}
th,td{padding:4px 5px;font-size:10px;line-height:1.2}
footer{font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.note{padding:5px 9px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(min-height:800px){
 .layout:nth-of-type(3){min-height:0}
}
@media(max-height:760px){
 header{height:58px;padding:6px 12px}h1{font-size:16px}header p{display:none}
 main{height:calc(100vh - 58px);padding:7px 10px;gap:6px}
 .card{padding:6px 9px}.value{font-size:20px}.sub{font-size:9px}
 .chart{height:85px}.panel{padding:7px 9px}th,td{padding:3px;font-size:9px}
}
@media(max-width:900px){
 html,body{height:auto;overflow:auto}
 main{height:auto;overflow:visible;grid-template-rows:none}
 .layout{grid-template-columns:1fr}
 .scroll{height:260px}
 header{height:auto;flex-wrap:wrap}
}


/* Final compact layout: fit the dashboard in a typical desktop browser viewport */
html,body{height:100%;overflow:hidden}
header{height:54px;padding:5px 12px;gap:10px}
h1{font-size:16px}header p{font-size:10px;margin-top:1px}
main{height:calc(100vh - 54px);min-height:0;max-width:none;padding:6px 10px;gap:6px;overflow:hidden;
grid-template-rows:18px 54px 54px minmax(95px,.75fr) minmax(105px,.75fr) minmax(215px,1.55fr) 12px}
.card{padding:6px 9px;border-radius:9px}
.cards{gap:6px}
.klabel{font-size:9px;letter-spacing:.35px}
.value{font-size:21px;margin-top:2px;line-height:1}
.sub{font-size:9px;margin-top:2px;line-height:1.05}
.layout{gap:7px;min-height:0;min-width:0}
.panel{padding:7px 9px;border-radius:9px;min-height:0;min-width:0;overflow:hidden}
.panel h2{font-size:12px;margin:0 0 5px}
.chart{height:72px}
.note{padding:3px 7px;font-size:9px}
.barrow{margin:3px 0;font-size:9px}
.countries-panel{display:flex;flex-direction:column;min-height:0}
.countries-list{flex:1 1 auto;min-height:0;overflow:auto}
.network-panel{display:flex;flex-direction:column;gap:2px}
.network-panel .sub{font-size:9px;margin:0}
.network-table{flex:1 1 auto;min-height:0;overflow:auto}
.network-table th,.network-table td{padding:2px 4px;font-size:9px;line-height:1.05}
.events-table,.nodelists-table,.top-users-table,.top-files-table{height:130px;min-height:0;overflow:auto;flex:1 1 auto}
.scroll{min-height:0;scrollbar-width:auto;scrollbar-color:#87939b #26333c; scrollbar-gutter:stable}
.scroll::-webkit-scrollbar,.countries-list::-webkit-scrollbar{width:13px;height:13px}
.scroll::-webkit-scrollbar-track,.countries-list::-webkit-scrollbar-track{background:#26333c;border-radius:6px}
.scroll::-webkit-scrollbar-thumb,.countries-list::-webkit-scrollbar-thumb{background:#87939b;border:2px solid #26333c;border-radius:6px}
.scroll::-webkit-scrollbar-thumb:hover,.countries-list::-webkit-scrollbar-thumb:hover{background:#b0bac0}
.events-table th,.events-table td,.nodelists-table th,.nodelists-table td,.top-users-table th,.top-users-table td,.top-files-table th,.top-files-table td{padding:3px 5px;font-size:10px;line-height:1.1}
.extra-panels{min-height:0;align-items:stretch;grid-template-columns:repeat(2,minmax(0,1fr))}
.extra-panels .panel{height:auto;min-height:0}
footer{font-size:9px;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Bright blue stock-ticker flash: only changed values/rows pulse, then return to normal */
@keyframes tickerPulse{0%,12%{color:#ffffff;filter:brightness(1.8);text-shadow:0 0 3px #fff,0 0 12px #00aaff,0 0 22px #008cff;box-shadow:0 0 0 1px rgba(0,170,255,.95),0 0 14px rgba(0,140,255,.9);background-color:rgba(0,125,255,.38)}35%{color:#65d5ff;filter:brightness(1.55);text-shadow:0 0 10px #00aaff,0 0 18px #0077ff;box-shadow:0 0 0 1px rgba(0,170,255,.75),0 0 10px rgba(0,140,255,.65);background-color:rgba(0,125,255,.22)}100%{color:inherit;filter:brightness(1);text-shadow:none;box-shadow:none;background-color:transparent}}
@keyframes tickerRowPulse{0%,12%{background-color:rgba(0,140,255,.48);color:#fff;filter:brightness(1.55);box-shadow:inset 0 0 0 1px rgba(0,190,255,.95)}35%{background-color:rgba(0,115,255,.26);color:#b9edff;filter:brightness(1.3);box-shadow:inset 0 0 0 1px rgba(0,170,255,.6)}100%{background-color:transparent;color:inherit;filter:brightness(1);box-shadow:none}}
.ticker-update{animation:tickerPulse 1.65s ease-out 1 !important;border-radius:2px}
.value.ticker-update{display:inline-block}
td.ticker-update,.barrow.ticker-update{animation:tickerPulse 1.65s ease-out 1 !important}
tr.ticker-update td{animation:tickerRowPulse 1.65s ease-out 1 !important}
@media(prefers-reduced-motion:reduce){.ticker-update,tr.ticker-update td{animation:none !important;color:#8edfff !important;text-shadow:0 0 10px #008cff !important;outline:1px solid rgba(0,170,255,.8)}}
@media(max-height:760px){
 header{height:48px;padding:4px 10px}
 main{height:calc(100vh - 48px);padding:5px 8px;gap:5px;
 grid-template-rows:16px 48px 48px minmax(85px,.7fr) minmax(95px,.7fr) minmax(185px,1.35fr) 10px}
 .value{font-size:19px}.panel{padding:6px 8px}.chart{height:62px}
 .extra-panels .panel{min-height:0}
}
@media(max-width:900px){
 html,body{height:auto;overflow:auto}
 main{height:auto;overflow:visible;grid-template-rows:none}
 .layout,.extra-panels{grid-template-columns:1fr}
 .scroll{height:220px}
 header{height:auto;flex-wrap:wrap}
}

</style></head><body><header><div><h1>ALTAIRMINI BBS MONITOR</h1><p>Mystic Edition · Local browser dashboard · Read-only</p></div><div>Period <select id="period"><option value="today" selected>Today</option><option value="yesterday">Yesterday</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="all">All available history</option></select> <button id="refresh">Refresh</button></div></header>
<main><div id="notice" class="note">Caricamento log…</div>
<section class="cards">
<div class="card"><div class="klabel">Connections</div><div class="value" id="connections">—</div><div class="sub">Sessions found in node logs</div></div>
<div class="card"><div class="klabel">Successful logins</div><div class="value" id="logins">—</div><div class="sub">Authenticated users</div></div>
<div class="card"><div class="klabel">Unique IPs</div><div class="value" id="ips">—</div></div>
<div class="card"><div class="klabel">Dropped sessions</div><div class="value" id="dropped">—</div></div></section>
<section class="cards"><div class="card"><div class="klabel">Normal logoffs</div><div class="value" id="closed">—</div></div><div class="card"><div class="klabel">No recorded end</div><div class="value" id="unresolved">—</div><div class="sub">May still be open sessions</div></div><div class="card"><div class="klabel">Average login duration</div><div class="value" id="duration">—</div></div><div class="card"><div class="klabel">Blocked attempts</div><div class="value" id="blocked">—</div><div class="sub" id="blockedSub"></div></div></section>
<section class="layout"><div class="panel"><h2>Daily activity</h2><svg id="chart" class="chart" viewBox="0 0 700 180" preserveAspectRatio="none"></svg><div class="sub">Bars: connections; line: successful logins. Chart shows the last 30 days.</div></div><div class="panel countries-panel"><h2>Countries</h2><div id="countries" class="countries-list"></div></div></section>
<section class="layout"><div class="panel"><h2>Recent Sessions</h2><div class="scroll"><table><thead><tr><th>Time</th><th>Node</th><th>IP / Country</th><th>User</th><th>Protocol</th><th>Result</th></tr></thead><tbody id="sessions"></tbody></table></div></div>
<div class="panel network-panel"><h2>Inbound Packets &amp; Files by Network</h2><div class="sub" id="networkSummary">Reading inbound transfers from poll.log and newer mis.log events</div><div class="scroll network-table"><table><thead><tr><th>Network</th><th>Received files</th><th>Share</th><th>Last received</th></tr></thead><tbody id="networks"></tbody></table></div></div></section>
<section class="layout extra-panels"><div class="panel"><h2>Recent BinkP / Block Events</h2><div class="scroll events-table"><table><thead><tr><th>Time</th><th>Event</th><th>Details</th></tr></thead><tbody id="events"></tbody></table></div></div><div class="panel"><h2>Nodelist Files</h2><div class="sub">Detected nodelist files, last modification and size</div><div class="scroll nodelists-table"><table><thead><tr><th>Network</th><th>File</th><th>Last modified</th><th>Size</th></tr></thead><tbody id="nodelists"></tbody></table></div></div><div class="panel"><h2>Top 10 Users</h2><div class="sub">Successful sessions in selected period</div><div class="scroll top-users-table"><table><thead><tr><th>#</th><th>User</th><th>Sessions</th></tr></thead><tbody id="topUsers"></tbody></table></div></div><div class="panel"><h2>Top 10 Files Download</h2><div class="sub">Downloads in selected period</div><div class="scroll top-files-table"><table><thead><tr><th>#</th><th>File</th><th>Downloads</th></tr></thead><tbody id="topFiles"></tbody></table></div></div></section>
<footer>Last updated: <span id="updated">—</span> · Auto-refresh every 15 seconds · <span id="logdir"></span></footer></main>
<script>
const $=id=>document.getElementById(id);function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
const previousValues=new Map();
function flash(el){if(!el)return;el.classList.remove('ticker-update');void el.offsetWidth;el.classList.add('ticker-update');window.setTimeout(()=>el.classList.remove('ticker-update'),1500);}
function liveText(id,value){const el=$(id),next=String(value??"");if(previousValues.has(id)&&previousValues.get(id)!==next)flash(el);previousValues.set(id,next);el.textContent=next;}
function liveHTML(id,html){const el=$(id),old=previousValues.get(id);el.innerHTML=html;if(old!==undefined&&old!==html){const rows=Array.from(el.children);const oldRows=old.split(/(?=<tr|<div class=\"barrow\")/i).filter(x=>/^<tr|^<div class=\"barrow\"/i.test(x));rows.forEach((row,i)=>{const current=row.outerHTML;if(oldRows[i]!==current)flash(row);});}previousValues.set(id,html);}
function dur(s){if(s==null)return "—";let h=Math.floor(s/3600),m=Math.floor(s%3600/60),q=s%60;return h?`${h}h ${m}m`:`${m}m ${q}s`;}
async function load(){try{let r=await fetch('/api/stats?period='+$('period').value,{cache:'no-store'});let d=await r.json();if(!r.ok)throw Error(d.error||r.status);$('notice').textContent=d.file_count?`${d.file_count} node logs read · data updated ${new Date(d.generated_at).toLocaleString()}`:'No node*.log files found.';
liveText('connections',d.total_connections);liveText('logins',d.successful_logins);liveText('ips',d.unique_ips);liveText('dropped',d.dropped);liveText('closed',d.closed);liveText('unresolved',d.unresolved);liveText('duration',dur(d.avg_session_seconds));liveText('blocked',d.mis_log_available?d.blocked_attempts:'N/D');$('blockedSub').textContent=d.mis_log_available?'Events found in mis.log':'mis.log is not present in C:\mystic\logs';$('updated').textContent=new Date(d.generated_at).toLocaleString();$('logdir').textContent=d.log_dir;
let max=Math.max(1,...d.countries.map(x=>x.count));liveHTML('countries',d.countries.slice(0,15).map(c=>`<div class="barrow"><span>${esc(c.name)}</span><div class="bar"><i style="width:${Math.max(1,c.count/max*100)}%"></i></div><span>${c.count} (${c.percent}%)</span></div>`).join('')||'No data');
liveHTML('sessions',d.sessions.slice(0,80).map(s=>`<tr><td>${esc(s.connected_at.replace('T',' '))}</td><td>${esc(s.node)}</td><td>${esc(s.ip)}<br><span class="sub">${esc(s.country||'Unknown')}</span></td><td>${esc(s.user||'—')}</td><td><span class="pill">${esc(s.service)}</span></td><td>${esc(s.end_reason)}${s.login_success?' · login':''}</td></tr>`).join('')||'<tr><td colspan="6">No sessions</td></tr>');
const ns=d.network_stats||{};$('networkSummary').textContent=ns.available?`${ns.total.toLocaleString()} received items · ${(ns.bytes/1048576).toFixed(2)} MB total in selected period`:'poll.log and mis.log are not available in C:\mystic\logs';
liveHTML('networks',ns.available?ns.networks.filter(n=>n.name!=='Other / Unidentified').map(n=>`<tr><td>${esc(n.name)}</td><td>${n.count.toLocaleString()}</td><td>${n.percent}%</td><td>${esc(n.latest.replace('T',' '))}</td></tr>`).join('')||'<tr><td colspan="4">No received items in this period</td></tr>':'<tr><td colspan="4">Waiting for poll.log</td></tr>');
liveHTML('events',d.mis_events.map(e=>`<tr><td>${esc(e.time.replace('T',' '))}</td><td>${esc(e.type)}</td><td>${esc(e.detail)}</td></tr>`).join('')||'<tr><td colspan="3">No events detected</td></tr>');liveHTML('nodelists',(d.nodelists||[]).map(n=>`<tr title="${esc(n.path)}"><td>${esc(n.network||'Unknown')}</td><td>${esc(n.name)}</td><td>${esc(n.modified.replace('T',' '))}</td><td>${n.bytes.toLocaleString()} B</td></tr>`).join('')||'<tr><td colspan="4">No nodelist files found under C:\\mystic (top level and one subfolder deep)</td></tr>');liveHTML('topUsers',(d.top_users||[]).map((u,i)=>`<tr><td>${i+1}</td><td>${esc(u.user)}</td><td>${u.sessions}</td></tr>`).join('')||'<tr><td colspan="3">No authenticated users in this period</td></tr>');liveHTML('topFiles',(d.top_files||[]).map((f,i)=>`<tr><td>${i+1}</td><td title="${esc(f.file)}">${esc(f.file)}</td><td>${f.downloads}</td></tr>`).join('')||'<tr><td colspan="3">No downloads recorded in this period</td></tr>');draw(d.daily);if(d.errors.length)$('notice').textContent+=' Warnings: '+d.errors.join('; ');
}catch(e){$('notice').textContent='Error: '+e.message+'. Check the shared folder and restart the application.';}}
function draw(data){let svg=$('chart');svg.innerHTML='';let a=data.slice(-30);if(!a.length){svg.innerHTML='<text x="20" y="80" fill="#9cb0bc">No daily data</text>';return}let ns='http://www.w3.org/2000/svg',W=700,H=180,pL=30,pR=8,pT=12,pB=25,plotH=H-pT-pB,plotW=W-pL-pR,max=Math.max(1,...a.map(x=>x.connections)),maxL=Math.max(1,...a.map(x=>x.logins)),pts=[];[0,.5,1].forEach(v=>{let y=pT+plotH*(1-v),line=document.createElementNS(ns,'line');line.setAttribute('x1',pL);line.setAttribute('x2',W-pR);line.setAttribute('y1',y);line.setAttribute('y2',y);line.setAttribute('stroke','#263844');line.setAttribute('stroke-width','1');svg.appendChild(line);});a.forEach((x,i)=>{let step=plotW/a.length,bw=Math.max(2,step*.62),xx=pL+i*step+(step-bw)/2,hh=plotH*x.connections/max,yy=pT+plotH-hh,r=document.createElementNS(ns,'rect');r.setAttribute('x',xx);r.setAttribute('y',yy);r.setAttribute('width',bw);r.setAttribute('height',Math.max(1,hh));r.setAttribute('rx','1');r.setAttribute('fill','#5ce0a0');r.appendChild(document.createElementNS(ns,'title')).textContent=`${x.date}: ${x.connections} connections, ${x.logins} logins`;svg.appendChild(r);pts.push((xx+bw/2)+','+(pT+plotH-plotH*x.logins/maxL));if(i===0||i===a.length-1||i%Math.ceil(a.length/6)===0){let tx=document.createElementNS(ns,'text');tx.setAttribute('x',xx+bw/2);tx.setAttribute('y',H-7);tx.setAttribute('text-anchor','middle');tx.setAttribute('fill','#9cb0bc');tx.setAttribute('font-size','10');tx.textContent=x.date.slice(5).replace('-','/');svg.appendChild(tx);}});if(pts.length>1){let pl=document.createElementNS(ns,'polyline');pl.setAttribute('points',pts.join(' '));pl.setAttribute('fill','none');pl.setAttribute('stroke','#64c7ef');pl.setAttribute('stroke-width','2');svg.appendChild(pl);}}
$('refresh').onclick=load;$('period').onchange=load;load();setInterval(load,15000);
</script></body></html>'''

"""
generate_trail_map.py
━━━━━━━━━━━━━━━━━━━━━
Unified script that handles MULTIPLE input spreadsheet formats
(both .xlsx and .csv) and generates an ant-trail network visualization HTML.

AUTO-DETECTS which format the input flows file is:

  MODE A - IP Trail  (has Source_IP / Dest_IP columns)
    Shows actual IP addresses at each hop
    Examples: Complete_Paths_IP_Enriched.xlsx
              All_Complete_Flows_Fort_Meade.csv        (Xyler - per-flow detail)

  MODE B - Node Trail  (no IP columns)
    Shows node/circuit names at each hop
    Examples: FlowsOutOfFtMeadeUURWMEA120.xlsx
              Consolidated_Complete_Flows_Fort_Meade.csv  (Xyler - router pairs)
              Latency_Comparison.csv (original)

DIRECTION - controls which traffic flow is visualized (--direction flag):

  outbound (default) - One-to-Many: hub is the SOURCE, customers are
                        destinations (e.g. "One to Many from Fort Meade")
  inbound             - Many-to-One: customers are SOURCES, hub is the
                        destination (return traffic flowing INTO Fort Meade)
  both                - combines both directions; a customer node may show
                        up to two paths in its detail card, one each way,
                        each labeled OUT or IN

Both modes / all directions:
  - Use master_dataframe_long.xlsx for coordinates
  - Use master_dataframe_3.xlsx for router loopback IPs
  - Apply propagation delay calculation for unmeasured OCONUS backbone links
  - Show all unique paths per customer node in the detail panel
  - Color ant-trail lines by latency (blue <3ms, amber 3-7ms, red >7ms)
  - Correctly label OCONUS vs CONUS nodes (not International)
  - Parse Flow_Path strings in either latency-annotation format:
        OLD:  --0.5->     (single dash-arrow)
        NEW:  --0.50-->   (double dash-arrow, used in Xyler's files)

Usage:
    python generate_trail_map.py --flows FlowsOutOfFtMeadeUURWMEA120.xlsx
    python generate_trail_map.py --flows Complete_Paths_IP_Enriched.xlsx
    python generate_trail_map.py --flows All_Complete_Flows_Fort_Meade.csv \\
                                 --direction outbound
    python generate_trail_map.py --flows Consolidated_Complete_Flows_Fort_Meade.csv \\
                                 --direction both --out DAI_AntTrail_Both.html

Requirements:
    pip install pandas openpyxl
"""

import re
import json
import math
import argparse
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("ERROR: pip install pandas openpyxl")
    sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
# PROPAGATION DELAY  -  for OCONUS nodes where backbone is not measured
# Formula per Steve's guidance:
#   Speed of light in fiber = ~200,000 km/s
#   Delay (ms) = distance_km / 200,000 * 1000
# ═════════════════════════════════════════════════════════════════════════════

HUB_LAT = 39.100   # Fort Meade, MD
HUB_LNG = -76.770

# If measured latency < 50% of calculated → backbone not measured → use calculated
BACKBONE_THRESHOLD = 0.50


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km using Haversine formula."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def calc_propagation_ms(lat2, lng2):
    """One-way fiber propagation delay from Fort Meade to destination."""
    dist_km = haversine_km(HUB_LAT, HUB_LNG, lat2, lng2)
    delay_ms = dist_km / 200_000 * 1000
    return round(delay_ms, 2), round(dist_km, 0)


def is_oconus(node_name):
    """
    True if node is outside continental US.
    Handles CA (Canada vs California) and DE (Germany vs Delaware) ambiguity.
    """
    suffix = node_name.split("_")[-1]
    if suffix in {"GB", "CY", "RO"}:
        return True
    if suffix == "DE" and any(k in node_name
                               for k in ["CLAYKSRN", "MIESAUAD", "PATCHBK",
                                         "PANZERBK", "KLBRKSRN"]):
        return True
    if suffix == "CA" and "OTTAWA" in node_name:
        return True
    return False


def resolve_latency(measured_ms, dest_lat, dest_lng, dest_name):
    """
    Returns (display_ms, dist_km, lat_type) where lat_type is one of:
      'measured'   - CONUS or OCONUS with backbone measured
      'calculated' - OCONUS, backbone clearly not measured (<50% of calc)
      'partial'    - OCONUS, backbone partially measured (>=50% of calc)
    """
    if not is_oconus(dest_name):
        return measured_ms, 0, "measured"

    calc_ms, dist_km = calc_propagation_ms(dest_lat, dest_lng)
    if calc_ms == 0:
        return measured_ms, 0, "measured"

    ratio = measured_ms / calc_ms
    if ratio < BACKBONE_THRESHOLD:
        return calc_ms, dist_km, "calculated"
    else:
        return measured_ms, dist_km, "partial"


# ═════════════════════════════════════════════════════════════════════════════
# UNIVERSAL FILE READER  -  supports both .xlsx and .csv input files
# ═════════════════════════════════════════════════════════════════════════════

def read_table(path, nrows=None):
    """
    Reads a data file regardless of whether it's .xlsx, .xls, or .csv.
    Used everywhere a spreadsheet/table needs to be loaded so that
    Xyler's CSV exports work exactly like the existing XLSX files.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=nrows)
    return pd.read_excel(path, nrows=nrows)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 - Auto-detect input file format
# ═════════════════════════════════════════════════════════════════════════════

def detect_mode(flows_path):
    """
    Reads the column headers and returns:
      'ip'   - file has Source_IP and Dest_IP columns  → IP Trail mode
      'node' - file does not have IP columns            → Node Trail mode
    Works for both .xlsx and .csv inputs.
    """
    df = read_table(flows_path, nrows=0)   # headers only, fast
    cols = set(df.columns)
    if "Source_IP" in cols and "Dest_IP" in cols:
        return "ip"
    return "node"


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 - Load router coordinates
# Source: master_dataframe_long.xlsx
# ═════════════════════════════════════════════════════════════════════════════

def load_router_coords(coords_path):
    """Returns { "UURWMEA110": (39.083, -76.733), ... }"""
    print(f"[1/4] Loading router coordinates from: {coords_path}")
    df = read_table(coords_path).drop_duplicates("Router")
    coords = {}
    for _, row in df.iterrows():
        try:
            coords[str(row["Router"]).strip()] = (
                float(row["Latitude"]),
                float(row["Longitude"])
            )
        except (ValueError, TypeError):
            pass
    print(f"    -> {len(coords)} routers with coordinates")
    return coords


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 - Load router loopback IPs
# Source: master_dataframe_3.xlsx
# ═════════════════════════════════════════════════════════════════════════════

def load_router_ips(routers_path):
    """Returns { "UJEWMEA040": "33.63.x.x", ... } from loopback interfaces."""
    print(f"[2/4] Loading router IPs from: {routers_path}")
    df = read_table(routers_path)
    lo = df[df["Interface"].str.contains("lo0", na=False)].copy()
    lo = lo[lo["Destination_IP"] != "RIP-NA"][["Source_Router", "Destination_IP"]]
    lo.columns = ["Router", "IP"]
    lo = lo.drop_duplicates("Router").set_index("Router")["IP"].to_dict()
    print(f"    -> {len(lo)} routers with loopback IPs")
    return lo


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 - Load flows from input file (handles both formats, CSV or XLSX)
# ═════════════════════════════════════════════════════════════════════════════

def load_flows(flows_path, mode):
    """
    Reads the input flows file and returns (flows, node_ip).

    MODE A (ip):
        Reads Source_IP, Dest_IP - builds node->IP lookup from endpoints.
        Matches: Complete_Paths_IP_Enriched.xlsx
                 All_Complete_Flows_Fort_Meade.csv  (Xyler's per-flow file)
    MODE B (node):
        No IP columns - node_ip will be empty, IPs come from router_ips only.
        Matches: FlowsOutOfFtMeadeUURWMEA120.xlsx
                 Consolidated_Complete_Flows_Fort_Meade.csv  (Xyler's pair file)

    Both modes read: Source, Destination, Flow_Path, Total_Latency_ms
    Works for both .xlsx and .csv inputs.
    """
    print(f"[3/4] Loading flows from: {flows_path}  [{mode.upper()} TRAIL mode]")
    df = read_table(flows_path)
    df.columns = [c.strip() for c in df.columns]

    flows   = []
    node_ip = {}

    for _, row in df.iterrows():
        src  = str(row.get("Source", "")).strip()
        dest = str(row.get("Destination", "")).strip()
        if not src or not dest:
            continue

        src_ip  = str(row.get("Source_IP", "")).strip() if mode == "ip" else ""
        dest_ip = str(row.get("Dest_IP",   "")).strip() if mode == "ip" else ""

        flows.append({
            "source":      src,
            "destination": dest,
            "source_ip":   src_ip,
            "dest_ip":     dest_ip,
            "flow_path":   str(row.get("Flow_Path", "")).strip(),
            "latency_ms":  float(row.get("Total_Latency_ms", 0) or 0),
            "occurrences": int(row.get("Occurrence_Count", 1) or 1),
            "multi_path":  str(row.get("Multiple_Paths", "False")).strip(),
        })

        if mode == "ip":
            if src and src_ip and src not in node_ip:
                node_ip[src] = src_ip
            if dest and dest_ip and dest not in node_ip:
                node_ip[dest] = dest_ip

    print(f"    -> {len(flows)} flow rows | "
          f"{len(node_ip)} endpoint IPs | mode={mode}")
    return flows, node_ip


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 - Build map data
# ═════════════════════════════════════════════════════════════════════════════

# Recognised hub node prefixes - used only when no explicit --hub is given
HUB_PREFIXES = ["UURWMEA"]


def is_hub(node_name, explicit_hubs=None):
    """
    A node is a hub if either:
      - it's in the explicit_hubs set passed via --hub, OR
      - it starts with a known hub prefix (UURWMEA)
    """
    if explicit_hubs and node_name in explicit_hubs:
        return True
    return any(node_name.startswith(p) for p in HUB_PREFIXES)


def auto_detect_hub(flows):
    """
    Fallback used ONLY when no --hub is given AND no UURWMEA-prefixed
    node exists in the data (e.g. Xyler's DAI service-endpoint files,
    where the "hub" is a converging service site, not Fort Meade).

    Picks the single node that appears most often as a destination
    (the converging endpoint everything flows TOWARD) - this matches
    the "service utilizes our enterprise" Many-to-One pattern Dr.
    Fransen described, where many different sites all reach one
    service endpoint.

    IMPORTANT: this is a best-effort guess. The script prints a loud
    warning so the person running it knows to verify with --hub if
    the guess looks wrong.
    """
    dest_counts = {}
    for f in flows:
        dest_counts[f["destination"]] = dest_counts.get(f["destination"], 0) + 1

    if not dest_counts:
        return []

    best_dest = max(dest_counts, key=dest_counts.get)
    print(f"    WARNING: No UURWMEA hub found and no --hub specified.")
    print(f"    Auto-detected likely hub/service endpoint: '{best_dest}' "
          f"(appears as destination in {dest_counts[best_dest]} flows)")
    print(f"    If this is wrong, re-run with --hub {best_dest!r} "
          f"or the correct node name.")
    return [best_dest]


def parse_hops_with_latency(path_str):
    """
    Extract hop nodes AND the per-segment (per-link) latency AND CCSD
    circuit identifier between them.

    Handles BOTH path formats:

      OLD format (no CCSD):
        NodeA --0.5-> NodeB --0.50--> NodeC
        Returns ccsd=None for every hop.

      NEW format (with CCSD, Xyler's updated files):
        NodeA  --(CCSD, latency)-->  NodeB  --(CCSD, latency)-->  NodeC
        e.g.  UJEWMEA030 --(2PH0, 0.500ms)--> UJEWMEA040
        Returns ccsd='2PH0', link_ms=0.5 for that hop.
        Multi-CCSD links: --(BDC7,BDG7,BDL6, 2.000ms)-->
        Returns ccsd='BDC7,BDG7,BDL6'.

    UJP_MESH blocks carry no CCSD and are replaced with a [MESH]
    placeholder so they do not break node/link pairing.

    Returns a list of dicts, one per hop node:
        [
          {"node": "UURWMEA110", "link_ms": None,  "ccsd": None},
          {"node": "UJEWMEA040", "link_ms": 0.50,  "ccsd": "268D"},
          {"node": "UJEWMEA030", "link_ms": 0.50,  "ccsd": "2PH0"},
          {"node": "DK_BALTIMOR_MD", "link_ms": None, "ccsd": "7XYZ"},
        ]
    """
    path_str = path_str.strip()

    # ── NEW FORMAT: --(CCSD, latency)--> ─────────────────────────────────────
    # Detect by presence of the --(  )-->  pattern
    if re.search(r'--\([^)]+\)-->', path_str):
        # Replace UJP_MESH block with a placeholder so it doesn't break pairing
        cleaned = re.sub(
            r'\s*->\s*\[UJP_MESH\s*--[\d.]+ms-->\s*\]\s*->\s*',
            '  --([MESH], N/A)-->  ',
            path_str
        )
        parts     = re.split(r'\s+--\([^)]+\)-->\s+', cleaned)
        links_raw = re.findall(r'--\(([^)]+)\)-->', cleaned)

        hops = [{"node": parts[0].strip(), "link_ms": None, "ccsd": None}]
        for i, raw in enumerate(links_raw):
            tokens  = [t.strip() for t in raw.split(",")]
            lat_str = tokens[-1]
            ccsd    = ",".join(tokens[:-1]) if len(tokens) > 1 else None
            # Ignore the [MESH] placeholder ccsd
            if ccsd == "[MESH]":
                ccsd = None

            ms = None
            m = re.match(r"([\d.]+)ms", lat_str)
            if m:
                ms = float(m.group(1))

            node = parts[i + 1].strip() if i + 1 < len(parts) else "?"
            hops.append({"node": node, "link_ms": ms, "ccsd": ccsd})

        return hops

    # ── OLD FORMAT: --0.5->  or  --0.50-->  ──────────────────────────────────
    tokens = re.split(r"(-+[\d.]*-+>|->)", path_str)
    tokens = [t.strip() for t in tokens if t.strip()]

    hops = []
    pending_ms = None
    for tok in tokens:
        arrow_match = re.match(r"^-+([\d.]*)-+>$|^->$", tok)
        if arrow_match:
            ms_str = arrow_match.group(1) if arrow_match.groups() else None
            pending_ms = float(ms_str) if ms_str else None
            continue
        if "UJP_MESH" in tok or "[" in tok:
            pending_ms = None
            continue
        hops.append({"node": tok, "link_ms": pending_ms, "ccsd": None})
        pending_ms = None

    return hops


def parse_hops(path_str):
    """
    Extract clean hop list (node names only, no latency) from a flow
    path string. Kept for callers that only need the node sequence.
    """
    return [h["node"] for h in parse_hops_with_latency(path_str)]


def build_trail_str(hops_with_latency, node_ip, router_ips, mode):
    """
    Builds the human-readable hop string shown in the detail panel.
    Annotated with per-link latency AND CCSD circuit identifier.

    When CCSD is present (Xyler's new files), the separator between hops
    renders as  --CCSD->  per Xyler's request, e.g.:

      MODE ip:
        214.x.x.x(UURWMEA110) --268D-> 33.x.x.x(UJEWMEA040)[0.50ms] --2PH0-> 131.x.x.x(DEST)

      MODE node:
        UURWMEA110 --268D-> UJEWMEA040[0.50ms] --2PH0-> DK_DALLAS_TX

    When no CCSD (old files), falls back to the plain  ->  separator.

    The [Nms] latency suffix on each hop badge still shows the link latency.
    The CCSD is encoded into the trail string as  |CCSD|  so the JS badge
    renderer can extract it separately and display it on the arrow.
    Format per hop segment in the trail string:
        node_label[link_ms]|ccsd|
    The JS renderer splits on ' -> ' and reads the |ccsd| suffix.
    """
    parts = []
    for h in hops_with_latency:
        node = h["node"]
        if mode == "ip":
            ip = node_ip.get(node) or router_ips.get(node)
            label = f"{ip}({node})" if ip else node
        else:
            label = node
        if h["link_ms"] is not None:
            label += f"[{h['link_ms']:.2f}ms]"
        # Append CCSD as a pipe-delimited suffix so JS can read it
        if h.get("ccsd"):
            label += f"|{h['ccsd']}|"
        parts.append(label)
    return " -> ".join(parts)


def build_map_data(flows, node_ip, router_ips, router_coords, mode,
                   direction="outbound", explicit_hubs=None):
    """
    Merges all data into the map data structure.
    Detects hub nodes from the data (or uses --hub override).
    Preserves ALL unique (source, dest, path) combos for the detail panel.
    Uses one ant-trail line per customer node (lowest latency) for clarity.

    direction:
        "outbound" - One-to-Many: hub is the SOURCE, customers are destinations
                     (e.g. Xyler's "One to Many from Fort Meade")
        "inbound"  - Many-to-One: customers are SOURCES, hub is the destination
                     (e.g. Xyler's DAI service-endpoint files, where many
                     different sites converge on one service node)
        "both"     - combines both directions into a single visualization

    explicit_hubs:
        Optional set of node names to treat as the hub, passed via --hub.
        Required when the data has no UURWMEA-prefixed node (e.g. the DAI
        service files where the "hub" is DK_SANJOSE_CA / DK_SAN_JOSE_CA,
        not a network router). If not given, falls back to UURWMEA
        detection, then to auto_detect_hub() as a last resort with a
        loud warning rather than silently treating every node as a hub.
    """
    explicit_hubs = set(explicit_hubs) if explicit_hubs else None

    all_nodes = set(f["source"] for f in flows) | set(f["destination"] for f in flows)
    hubs = sorted([s for s in all_nodes if is_hub(s, explicit_hubs)])

    if not hubs:
        # NEVER fall back to "treat every node as a hub" - that silently
        # produces an empty map (every flow gets excluded by the XOR/AND
        # filters below). Instead, guess the single most likely hub and
        # warn loudly so the person running it knows to verify.
        hubs = auto_detect_hub(flows)

    print(f"    Hub nodes detected: {hubs}")
    print(f"    Direction mode: {direction}")

    # Select flows based on direction
    if direction == "outbound":
        # One-to-Many: hub -> customer (hub is source)
        selected = [f for f in flows if f["source"] in hubs and f["destination"] not in hubs]
    elif direction == "inbound":
        # Many-to-One: customer -> hub (hub is destination)
        # Normalise so "from"/"to" always reads hub -> customer for map drawing,
        # while preserving the TRUE traffic direction in a separate field
        selected = [f for f in flows if f["destination"] in hubs and f["source"] not in hubs]
    else:  # "both"
        selected = [f for f in flows
                    if (f["source"] in hubs) != (f["destination"] in hubs)]  # XOR: exactly one side is a hub

    if not selected:
        print(f"    WARNING: 0 flows matched direction='{direction}' with "
              f"hub(s)={hubs}. Try --direction inbound/outbound/both or "
              f"specify the correct --hub.")

    selected.sort(key=lambda x: x["latency_ms"])

    seen_paths = {}
    for f in selected:
        key = (f["source"], f["destination"], f["flow_path"])
        if key not in seen_paths:
            seen_paths[key] = f
    unique_flows = list(seen_paths.values())

    # For the map line, group by the CUSTOMER node (whichever side isn't the hub)
    # so outbound and inbound paths to/from the same customer share one line slot
    def customer_node(f):
        return f["destination"] if f["source"] in hubs else f["source"]

    def hub_node(f):
        return f["source"] if f["source"] in hubs else f["destination"]

    def traffic_direction(f):
        return "outbound" if f["source"] in hubs else "inbound"

    best_per_customer = {}
    for f in unique_flows:
        c = customer_node(f)
        if c not in best_per_customer or f["latency_ms"] < best_per_customer[c]["latency_ms"]:
            best_per_customer[c] = f

    map_routes  = []
    nodes       = {}
    node_routes = {}
    skipped     = 0

    # ── Build node_routes - ALL paths, keyed by CUSTOMER node ─────────────────
    # (so a customer's card shows both its outbound and inbound paths
    #  to/from any hub, regardless of which side was the netflow "source")
    for f in unique_flows:
        src, dest = f["source"], f["destination"]
        src_c  = router_coords.get(src)
        dest_c = router_coords.get(dest)
        if not src_c or not dest_c:
            continue

        cust   = customer_node(f)
        hub    = hub_node(f)
        tdir   = traffic_direction(f)
        # Always resolve latency using the CUSTOMER's coordinates
        # (the non-hub endpoint), since OCONUS detection depends on
        # the customer site, not on the hub
        cust_c = dest_c if cust == dest else src_c

        hops      = parse_hops_with_latency(f["flow_path"])
        trail_str = build_trail_str(hops, node_ip, router_ips, mode)
        slowest    = max(hops, key=lambda h: h["link_ms"] or 0, default=None)
        slowest_link = (
            {"node": slowest["node"], "ms": slowest["link_ms"]}
            if slowest and slowest["link_ms"] else None
        )

        display_ms, dist_km, lat_type = resolve_latency(
            f["latency_ms"], cust_c[0], cust_c[1], cust
        )

        if cust not in node_routes:
            node_routes[cust] = []
        node_routes[cust].append({
            "hub":          hub,
            "direction":    tdir,                 # "outbound" or "inbound"
            "from":         src,
            "to":           dest,
            "ms":           round(display_ms, 3),
            "ms_raw":       round(f["latency_ms"], 3),
            "lat_type":     lat_type,
            "dist_km":      dist_km,
            "path":         f["flow_path"],
            "trail":        trail_str,
            "slowest_link": slowest_link,   # per-link diagnostic, per Xyler's data
            "src_ip":       f["source_ip"],
            "dest_ip":      f["dest_ip"],
            "occ":          f["occurrences"],
        })

    # ── Build map_routes - one ant-trail line per customer node ───────────────
    for cust, f in best_per_customer.items():
        src, dest = f["source"], f["destination"]
        src_c  = router_coords.get(src)
        dest_c = router_coords.get(dest)
        if not src_c or not dest_c:
            skipped += 1
            continue

        hub  = hub_node(f)
        tdir = traffic_direction(f)
        cust_c = dest_c if cust == dest else src_c
        hub_c  = src_c  if cust == dest else dest_c

        hops      = parse_hops_with_latency(f["flow_path"])
        trail_str = build_trail_str(hops, node_ip, router_ips, mode)

        display_ms, dist_km, lat_type = resolve_latency(
            f["latency_ms"], cust_c[0], cust_c[1], cust
        )

        # Ant-trail line always drawn hub -> customer visually,
        # regardless of which direction the actual traffic flowed
        map_routes.append({
            "from":        hub,
            "to":          cust,
            "direction":   tdir,
            "src_ip":      f["source_ip"],
            "dest_ip":     f["dest_ip"],
            "lat1":        hub_c[0],  "lng1": hub_c[1],
            "lat2":        cust_c[0], "lng2": cust_c[1],
            "ms":          round(display_ms, 3),
            "ms_raw":      round(f["latency_ms"], 3),
            "lat_type":    lat_type,
            "dist_km":     dist_km,
            "trail":       trail_str,
            "total_paths": len(node_routes.get(cust, [])),
            "multi":       f["multi_path"],
        })

        for name, coords in [(hub, hub_c), (cust, cust_c)]:
            if name not in nodes:
                nodes[name] = {
                    "lat": coords[0], "lng": coords[1],
                    "ip":  node_ip.get(name) or router_ips.get(name) or "N/A",
                    "out": 0, "in": 0,
                    "is_hub": is_hub(name, explicit_hubs),
                }
        if tdir == "outbound":
            nodes[hub]["out"]  += 1
            nodes[cust]["in"]  += 1
        else:
            nodes[cust]["out"] += 1
            nodes[hub]["in"]   += 1

    print(f"    -> {len(map_routes)} customer nodes | "
          f"{len(unique_flows)} total paths | "
          f"{len(nodes)} nodes | {skipped} skipped (no coords)")

    return {
        "routes":      map_routes,
        "nodes":       nodes,
        "node_routes": node_routes,
        "hubs":        hubs,
        "mode":        mode,
        "direction":   direction,
    }


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 - Write HTML
# ═════════════════════════════════════════════════════════════════════════════

def write_html(map_data, output_path, title="DISA Fort Meade Routes"):
    print(f"[5/5] Writing HTML -> {output_path}")

    mode      = map_data["mode"]
    direction = map_data.get("direction", "outbound")
    data_json = json.dumps(map_data, separators=(",", ":"))

    trail_label = "IP Trail" if mode == "ip" else "Node Trail"
    direction_label = {
        "outbound": "One-to-Many",
        "inbound":  "Many-to-One",
        "both":     "Bidirectional",
    }.get(direction, "")
    subtitle = (f"{trail_label} &middot; {direction_label} &middot; "
                f"All Customers &middot; Hop-by-Hop Latency")

    parts = []
    a = parts.append

    a(f'<!DOCTYPE html>\n<html>\n<head>\n'
      f'<meta charset="UTF-8"/>\n'
      f'<meta name="viewport" content="width=device-width,initial-scale=1.0"/>\n'
      f'<title>{title}</title>\n'
      f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>\n'
      f'<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css"/>\n'
      f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css"/>\n'
      f'<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"></script>\n'
      f'<script src="https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js"></script>\n'
      f'<script src="https://cdn.jsdelivr.net/npm/leaflet-ant-path@1.1.2/dist/leaflet-ant-path.min.js"></script>\n')

    a('''<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#0a0e1a;color:#c8d8ff;overflow:hidden}
#header{position:fixed;top:0;left:0;right:0;z-index:2000;
  background:linear-gradient(90deg,#0d1b3e,#091225 60%,#0a0e1a);
  border-bottom:1px solid #1e3a6e;padding:8px 16px;
  display:flex;align-items:center;gap:16px}
#header h1{font-size:14px;font-weight:700;color:#4fc3f7;letter-spacing:2px;text-transform:uppercase}
.subtitle{font-size:11px;color:#5a7fa0;letter-spacing:1px}
.badge{background:#1a3a5c;border:1px solid #2a5a8c;border-radius:3px;padding:2px 8px;font-size:10px;color:#7ec8f8}
.mode-badge{background:#1a3a2c;border:1px solid #2a6a4c;border-radius:3px;padding:2px 8px;font-size:10px;color:#4fc3a7}
.dir-badge{background:#2c1a3a;border:1px solid #5a2a6e;border-radius:3px;padding:2px 8px;font-size:10px;color:#c87ef7}
#stats-bar{display:flex;gap:16px;align-items:center}
.stat-item .val{font-size:13px;color:#4fc3f7;font-weight:700}
.stat-item .lbl{font-size:9px;color:#5a7fa0}
#map{position:fixed;top:42px;left:0;right:360px;bottom:0}
#sidebar{position:fixed;top:42px;right:0;width:360px;bottom:0;
  background:#0a0e1a;border-left:1px solid #1e3a6e;
  display:flex;flex-direction:column;overflow:hidden}
#sidebar-header{padding:12px 14px 8px;border-bottom:1px solid #1a2e4a;flex-shrink:0}
#sidebar-title{font-size:12px;color:#7ec8f8;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:6px}
#search-box{width:100%;background:#0d1b2e;border:1px solid #1e3a6e;
  color:#c8d8ff;padding:5px 8px;font-size:11px;border-radius:3px;font-family:inherit}
#search-box:focus{outline:none;border-color:#4fc3f7}
#filter-bar{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap}
.filter-btn{font-size:10px;padding:2px 8px;border-radius:2px;border:1px solid #1e3a6e;
  background:#0d1b2e;color:#7ec8f8;cursor:pointer;letter-spacing:1px}
.filter-btn.active{background:#1a3a5c;border-color:#4fc3f7;color:#4fc3f7}
#node-list{flex:1;overflow-y:auto}
#node-list::-webkit-scrollbar{width:4px}
#node-list::-webkit-scrollbar-thumb{background:#1e3a6e;border-radius:2px}
.node-item{padding:8px 14px;border-bottom:1px solid #0f1e30;cursor:pointer;
  transition:background .15s;display:flex;align-items:center;gap:8px}
.node-item:hover{background:#0d1b2e}
.node-item.selected{background:#0f2040;border-left:2px solid #4fc3f7}
.node-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.node-dot.hub{background:#ff6b35}
.node-dot.customer{background:#4fc3f7}
.node-dot.oconus{background:#ab47bc}
.node-name{font-size:10px;color:#c8d8ff;flex:1}
.node-sub{font-size:9px;color:#4fc3f7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.node-latency{font-size:10px;color:#5a9a6a;text-align:right;white-space:nowrap;min-width:44px}
.node-latency.high{color:#e57373}.node-latency.med{color:#ffb74d}
#detail-panel{border-top:1px solid #1a2e4a;flex-shrink:0;max-height:320px;overflow-y:auto;display:none}
#detail-panel::-webkit-scrollbar{width:4px}
#detail-panel::-webkit-scrollbar-thumb{background:#1e3a6e}
#detail-panel.visible{display:block}
.detail-header{background:#0d1b2e;padding:8px 14px;border-bottom:1px solid #1a2e4a;
  display:flex;align-items:center;justify-content:space-between}
.detail-node-name{font-size:12px;color:#4fc3f7;font-weight:700}
.detail-close{cursor:pointer;color:#5a7fa0;font-size:14px}
.detail-close:hover{color:#c8d8ff}
.detail-section{padding:8px 14px}
.detail-label{font-size:9px;color:#5a7fa0;letter-spacing:1.5px;text-transform:uppercase;margin:6px 0 3px}
.detail-value{font-size:11px;color:#c8d8ff}
.detail-ip{font-size:13px;color:#4fc3f7;font-weight:700}
.detail-stat-row{display:flex;gap:12px;margin-bottom:6px}
.detail-stat{text-align:center}
.detail-stat .val{font-size:15px;color:#4fc3f7;font-weight:700}
.detail-stat .lbl{font-size:9px;color:#5a7fa0;letter-spacing:1px}
.route-item{padding:5px 0;border-bottom:1px solid #0f1e30}
.route-item:last-child{border-bottom:none}
.ip-badge{display:inline-block;background:#0d2a3e;border:1px solid #1e5a6e;
  border-radius:3px;padding:1px 5px;font-size:9px;color:#4fc3f7;
  white-space:nowrap;margin:1px 0}
.node-badge{display:inline-block;background:#0d1a2e;border:1px solid #1e3a5e;
  border-radius:3px;padding:1px 5px;font-size:9px;color:#c8d8ff;
  white-space:nowrap;margin:1px 0}
.hop-arrow{color:#5a7fa0;font-size:10px;margin:0 1px;white-space:nowrap}
.calc-note{font-size:9px;color:#ffb74d}
#legend{position:fixed;bottom:16px;left:16px;z-index:1500;
  background:rgba(10,14,26,.92);border:1px solid #1e3a6e;
  border-radius:4px;padding:10px 14px;font-size:10px}
.legend-row{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.legend-line{width:24px;height:2px}
.legend-dot-sm{width:8px;height:8px;border-radius:50%}
</style>
</head>
<body>
''')

    a(f'<div id="header">\n'
      f'  <h1>{title}</h1>\n'
      f'  <span class="subtitle">{subtitle}</span>\n'
      f'  <div id="stats-bar" style="margin-left:auto">\n'
      f'    <div class="stat-item"><div class="val" id="s-routes">-</div><div class="lbl">ROUTES</div></div>\n'
      f'    <div class="stat-item"><div class="val" id="s-nodes">-</div><div class="lbl">NODES</div></div>\n'
      f'    <div class="stat-item"><div class="val" id="s-avg">-</div><div class="lbl">AVG MS</div></div>\n'
      f'    <div class="badge">UURWMEA HUB</div>\n'
      f'    <div class="mode-badge">{"IP TRAIL" if mode == "ip" else "NODE TRAIL"}</div>\n'
      f'    <div class="dir-badge">{direction_label.upper()}</div>\n'
      f'  </div>\n'
      f'</div>\n')

    a('''<div id="map"></div>
<div id="sidebar">
  <div id="sidebar-header">
    <div id="sidebar-title">Customer Nodes</div>
    <input id="search-box" type="text"
           placeholder="Search node name or IP..." oninput="filterNodes()"/>
    <div id="filter-bar">
      <button class="filter-btn active" onclick="setFilter('all',this)">ALL</button>
      <button class="filter-btn" onclick="setFilter('low',this)">LOW (&lt;3ms)</button>
      <button class="filter-btn" onclick="setFilter('med',this)">MED (3-7ms)</button>
      <button class="filter-btn" onclick="setFilter('high',this)">HIGH (&gt;7ms)</button>
    </div>
  </div>
  <div id="node-list"></div>
  <div id="detail-panel">
    <div class="detail-header">
      <span class="detail-node-name" id="d-name">-</span>
      <span class="detail-close" onclick="closeDetail()">&#x2715;</span>
    </div>
    <div class="detail-section" id="d-body"></div>
  </div>
</div>
<div id="legend">
  <div style="font-size:9px;color:#5a7fa0;letter-spacing:1.5px;margin-bottom:6px">LEGEND</div>
  <div class="legend-row"><div class="legend-dot-sm" style="background:#ff6b35"></div>Hub (UURWMEA)</div>
  <div class="legend-row"><div class="legend-dot-sm" style="background:#4fc3f7"></div>Customer Node</div>
  <div class="legend-row"><div class="legend-dot-sm" style="background:#ab47bc"></div>OCONUS</div>
  <div class="legend-row">
    <div class="legend-line" style="background:linear-gradient(90deg,#4fc3f7,transparent)"></div>
    Ant Trail Route
  </div>
  <div class="legend-row"><div class="legend-line" style="background:#e57373"></div>High Latency (&gt;7ms)</div>
  <div class="legend-row"><div class="legend-line" style="background:#ffb74d;opacity:.6;border-top:1px dashed #ffb74d"></div>Calculated (OCONUS)</div>
</div>
''')

    # JavaScript - single block, no f-string to avoid brace escaping
    a('<script>\n')
    a('const D = ' + data_json + ';\n')
    a('const MODE = "' + mode + '";\n\n')

    a(r'''
const map = L.map('map',{center:[38.5,-95],zoom:4,preferCanvas:true});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{
  attribution:'&copy; OpenStreetMap contributors &copy; CARTO',
  subdomains:'abcd',maxZoom:20
}).addTo(map);

function lcolor(ms){return ms<3?'#4fc3f7':ms<7?'#ffb74d':'#e57373';}
function lclass(ms){return ms<3?'':'node-latency '+(ms<7?'med':'high');}
function isOconus(n){
  var s=n.split('_').pop();
  if(['GB','CY','RO'].indexOf(s)>=0) return true;
  if(s==='DE'&&/CLAYKSRN|MIESAUAD|PATCHBK|PANZERBK|KLBRKSRN/.test(n)) return true;
  if(s==='CA'&&n.indexOf('OTTAWA')>=0) return true;
  return false;
}

// Route summary per destination - built from node_routes (all paths)
var summary={};
Object.keys(D.node_routes).forEach(function(dest){
  var paths=D.node_routes[dest];
  summary[dest]={count:paths.length, paths:paths};
});

// ANT-PATH LINES
var antPaths=[], activeFilter='all', activeSearch='';
function drawRoutes(filter){
  antPaths.forEach(function(p){map.removeLayer(p);}); antPaths=[];
  var drawn={};
  D.routes.forEach(function(r){
    if(drawn[r.to]) return;
    if(filter==='low'&&r.ms>=3) return;
    if(filter==='med'&&(r.ms<3||r.ms>=7)) return;
    if(filter==='high'&&r.ms<7) return;
    drawn[r.to]=1;
    var clr = r.lat_type==='calculated'?'#ffb74d':lcolor(r.ms);
    try{
      var p=L.polyline.antPath([[r.lat1,r.lng1],[r.lat2,r.lng2]],{
        color:clr,
        weight:r.ms>10?2.5:r.ms>5?1.8:1.2,
        opacity: r.lat_type==='calculated'?0.5:0.75,
        delay:1200+Math.floor(Math.random()*800),
        dashArray:r.lat_type==='calculated'?[5,15]:[10,20],
        pulseColor:'#ffffff'
      });
      p.addTo(map); antPaths.push(p);
    }catch(e){}
  });
}

// renderTrail — converts a raw trail string into readable --CCSD / ms-> arrows.
// Used by buildPopup (Leaflet popup) so the popup matches the detail panel display.
function renderTrail(trail){
  if(!trail) return '';
  var hops=trail.split(' -> ');
  return hops.map(function(h,i){
    var ccsdMatch=h.match(/\|([^|]+)\|$/);
    var ccsd=ccsdMatch?ccsdMatch[1]:null;
    var hNoCcsd=ccsd?h.slice(0,h.lastIndexOf('|'+ccsd+'|')):h;
    var linkMatch=hNoCcsd.match(/\[([\d.]+)ms\]$/);
    var linkMs=linkMatch?parseFloat(linkMatch[1]):null;
    var hClean=hNoCcsd.replace(/\[[\d.]+ms\]$/,'');
    var arrow='';
    if(i>0){
      if(ccsd&&linkMs!==null)
        arrow='<span style="color:#ffb74d">--'+ccsd+' / '+linkMs.toFixed(2)+'ms-&gt;</span> ';
      else if(ccsd)
        arrow='<span style="color:#ffb74d">--'+ccsd+'-&gt;</span> ';
      else if(linkMs!==null)
        arrow='<span style="color:#5a9a6a">--'+linkMs.toFixed(2)+'ms-&gt;</span> ';
      else
        arrow='<span style="color:#5a7fa0">-&gt;</span> ';
    }
    return arrow+'<span style="color:#4fc3f7">'+hClean+'</span>';
  }).join('');
}

// MARKERS
var markers={};
function buildPopup(name,n,s,isHub){
  var ip=n.ip&&n.ip!=='N/A'?'<br/>IP: <b style="color:#4fc3f7">'+n.ip+'</b>':'';
  if(isHub){
    return '<div style="font-family:monospace;font-size:12px;min-width:200px">'
      +'<b style="color:#e65100">'+name+'</b><br/>'
      +'<span style="color:#888">Hub Node &mdash; Fort Meade MD</span>'
      +ip+'<br/>Outbound: '+(n.out||0)+'</div>';
  }
  var s2=summary[name]||{};
  var popup='<div style="font-family:monospace;font-size:11px;min-width:240px">'
    +'<b style="font-size:13px;color:#1565c0">'+name+'</b><br/>'
    +(isOconus(name)?'&#127757; OCONUS':'&#127482;&#127480; US DoD Site')
    +'<hr style="margin:4px 0"/>'
    +ip+(ip?'<br/>':'')
    +'<b>Paths:</b> '+(s2.count||1)+'<br/>'
    +'<b>Coords:</b> '+n.lat.toFixed(3)+', '+n.lng.toFixed(3);
  if(s2.paths&&s2.paths.length){
    popup+='<hr style="margin:4px 0"/>';
    s2.paths.slice(0,3).forEach(function(p){
      var latLabel=p.lat_type==='calculated'
        ?'<span style="color:#ffb74d">'+p.ms.toFixed(3)+' ms (calc)</span>'
        :'<span style="color:'+lcolor(p.ms)+'">'+p.ms.toFixed(3)+' ms</span>';
      popup+='<b>&larr; '+p.from+'</b> '+latLabel+'<br/>'
        +'<div style="font-size:9px;word-break:break-all;margin:2px 0 4px">'+renderTrail(p.trail)+'</div>';
    });
  }
  popup+='</div>';
  return popup;
}

function drawMarkers(){
  D.hubs.forEach(function(h){
    var n=D.nodes[h]; if(!n) return;
    var m=L.circleMarker([n.lat,n.lng],{
      radius:12,color:'#ff6b35',fillColor:'#ff6b35',fillOpacity:.9,weight:2
    }).addTo(map);
    m.bindPopup(buildPopup(h,n,{},true),{maxWidth:280});
    m.on('click',function(){selectNode(h);}); markers[h]=m;
  });
  var drawn={}; D.hubs.forEach(function(h){drawn[h]=1;});
  D.routes.forEach(function(r){
    var nm=r.to; if(drawn[nm]) return; drawn[nm]=1;
    var n=D.nodes[nm]; if(!n) return;
    var oconus=isOconus(nm);
    var c=oconus?'#ab47bc':lcolor(r.ms);
    var m=L.circleMarker([n.lat,n.lng],{
      radius:5,color:c,fillColor:c,fillOpacity:.85,weight:1.5
    }).addTo(map);
    m.bindPopup(buildPopup(nm,n,summary[nm]||{},false),{maxWidth:360});
    m.on('click',function(){selectNode(nm);}); markers[nm]=m;
  });
}

// SIDEBAR LIST
var selectedNode=null;
function buildList(){
  var q=activeSearch.toLowerCase(), f=activeFilter;
  var items=D.routes.filter(function(r){
    var n=D.nodes[r.to]||{};
    var ip=(n.ip||'').toLowerCase();
    if(r.to.toLowerCase().indexOf(q)<0&&ip.indexOf(q)<0) return false;
    if(f==='low'&&r.ms>=3) return false;
    if(f==='med'&&(r.ms<3||r.ms>=7)) return false;
    if(f==='high'&&r.ms<7) return false;
    return true;
  });
  var best={};
  items.forEach(function(r){if(!best[r.to]||r.ms<best[r.to].ms) best[r.to]=r;});
  items=Object.values(best).sort(function(a,b){return a.ms-b.ms;});

  document.getElementById('node-list').innerHTML=items.map(function(r){
    var n=D.nodes[r.to]||{};
    var oconus=isOconus(r.to);
    var dotCls=oconus?'oconus':'customer';
    var sub=MODE==='ip'&&n.ip&&n.ip!=='N/A'?n.ip:r.trail||'';
    var calcFlag=r.lat_type==='calculated'?' &#9650;':'';
    return '<div class="node-item'+(selectedNode===r.to?' selected':'')+
      '" onclick="selectNode(\''+r.to+'\')">'
      +'<div class="node-dot '+dotCls+'"></div>'
      +'<div style="flex:1;min-width:0">'
      +  '<div class="node-name">'+r.to+'</div>'
      +  (sub?'<div class="node-sub">'+sub+'</div>':'')
      +'</div>'
      +'<span class="node-latency '+(r.ms<3?'':r.ms<7?'med':'high')+'">'
      +r.ms.toFixed(2)+'ms'+calcFlag+'</span>'
      +'</div>';
  }).join('');

  var tot=items.reduce(function(s,r){return s+r.ms;},0);
  document.getElementById('s-routes').textContent=items.length;
  document.getElementById('s-nodes').textContent=Object.keys(D.nodes).length;
  document.getElementById('s-avg').textContent=items.length?(tot/items.length).toFixed(1)+'ms':'-';
}

function filterNodes(){activeSearch=document.getElementById('search-box').value;buildList();}
function setFilter(f,btn){
  activeFilter=f;
  document.querySelectorAll('.filter-btn').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active'); buildList(); drawRoutes(f);
}

// NODE SELECTION
function selectNode(name){
  selectedNode=name; buildList();
  var n=D.nodes[name];
  if(n) map.flyTo([n.lat,n.lng],7,{duration:1.2});
  if(markers[name]) markers[name].openPopup();
  showDetail(name);
  document.querySelectorAll('.node-item').forEach(function(el){
    if(el.querySelector('.node-name').textContent===name)
      el.scrollIntoView({behavior:'smooth',block:'nearest'});
  });
}

// DETAIL PANEL
function showDetail(name){
  document.getElementById('d-name').textContent=name;
  var node=D.nodes[name]||{};
  var nr=(D.node_routes[name]||[]).slice();
  nr.sort(function(a,b){return a.hub.localeCompare(b.hub)||a.ms-b.ms;});

  var html='<div class="detail-stat-row">'
    +'<div class="detail-stat"><div class="val">'+nr.length+'</div><div class="lbl">PATHS</div></div>'
    +'<div class="detail-stat"><div class="val">'+(node.out||0)+'</div><div class="lbl">OUT</div></div>'
    +'<div class="detail-stat"><div class="val">'+(node.in||0)+'</div><div class="lbl">IN</div></div>'
    +'</div>';

  if(MODE==='ip'&&node.ip&&node.ip!=='N/A'){
    html+='<div class="detail-label">IP Address</div>'
         +'<div class="detail-ip">'+node.ip+'</div>';
  }
  html+='<div class="detail-label">Coordinates</div>'
       +'<div class="detail-value">'+(node.lat||0).toFixed(4)+', '+(node.lng||0).toFixed(4)+'</div>';

  if(nr.length){
    html+='<div class="detail-label">Path Latency (fiber propagation delay)</div>';
    nr.forEach(function(r){
      // Latency label
      var latLabel;
      if(r.lat_type==='calculated'){
        latLabel='<span style="color:#ffb74d;font-weight:bold">'+r.ms.toFixed(3)+' ms</span>'
          +' <span class="calc-note">&#9650; calculated ('+r.dist_km+' km)</span>'
          +'<br/><span style="font-size:9px;color:#5a7fa0">Access only: '+r.ms_raw.toFixed(3)+' ms measured</span>';
      } else if(r.lat_type==='partial'){
        latLabel='<span style="color:#4fc3f7;font-weight:bold">'+r.ms.toFixed(3)+' ms</span>'
          +' <span style="font-size:9px;color:#5a7fa0">(partial backbone, '+r.dist_km+' km)</span>';
      } else {
        latLabel='<span style="color:'+lcolor(r.ms)+';font-weight:bold">'+r.ms.toFixed(3)+' ms</span>';
      }

      // Trail badges - each hop carries an optional [N.NNms] latency suffix
      // and an optional |CCSD| circuit identifier suffix (Xyler's new files).
      // Arrows between hops render as  --CCSD->  when a CCSD is present,
      // or plain  →  when not (old files).
      var hops=r.trail?r.trail.split(' -> '):[];
      var badges=hops.map(function(h,i){
        // Extract CCSD: |CCSD| suffix (may be absent for old-format files)
        var ccsdMatch=h.match(/\|([^|]+)\|$/);
        var ccsd=ccsdMatch?ccsdMatch[1]:null;
        var hNoCcsd=ccsd?h.slice(0,h.lastIndexOf('|'+ccsd+'|')):h;

        // Extract link latency: [N.NNms] suffix
        var linkMatch=hNoCcsd.match(/\[([\d.]+)ms\]$/);
        var linkMs=linkMatch?parseFloat(linkMatch[1]):null;
        var hClean=hNoCcsd.replace(/\[[\d.]+ms\]$/,'');

        var isIP=/^\d+\.\d+/.test(hClean);
        var label=isIP?hClean.split('(')[0]:hClean;
        var title=isIP&&hClean.indexOf('(')>0?hClean.match(/\(([^)]+)\)/)[1]:hClean;
        var cls=isIP?'ip-badge':'node-badge';

        // Highlight the badge if this hop's link is the slowest in the path
        var isSlowest=r.slowest_link&&linkMs!==null&&Math.abs(linkMs-r.slowest_link.ms)<0.001;
        var badgeStyle=isSlowest?' style="border-color:#e57373;color:#e57373"':'';
        // linkTag removed — latency is now shown on the arrow (--CCSD / Nms->)
        // so the node badge stays clean: just the router/site name.

        // Arrow between hops: --CCSD / latency-> reading left-to-right (Xyler's request).
        // The CCSD is the circuit ID for the link arriving at this node.
        // The latency (if measured) also lives on the arrow, not inside the node badge,
        // so the full read is: SourceNode --CCSD / 0.50ms-> DestNode
        var arrowHtml='';
        if(i>0){
          var arrowLabel = ccsd ? '--'+ccsd : '--';
          if(linkMs!==null) arrowLabel += ' / '+linkMs.toFixed(2)+'ms';
          arrowLabel += '-&gt;';
          arrowHtml = ccsd
            ? '<span class="hop-arrow" style="color:#ffb74d;font-size:9px" title="Circuit: '+ccsd+(linkMs!==null?' | '+linkMs.toFixed(3)+'ms':'')+'">'+arrowLabel+'</span>'
            : linkMs!==null
              ? '<span class="hop-arrow" style="color:#5a9a6a;font-size:9px">--'+linkMs.toFixed(2)+'ms-&gt;</span>'
              : '<span class="hop-arrow">&#8594;</span>';
        }
        return arrowHtml
          +'<span class="'+cls+'"'+badgeStyle+' title="'+title+'">'+label+'</span>';
      }).join('');

      // Direction indicator: outbound = hub sending TO this node
      //                       inbound  = this node sending TO the hub
      var dirArrow = r.direction==='outbound'
        ? '<span style="color:#4fc3f7" title="Outbound: hub &rarr; node">&#8594; OUT</span>'
        : '<span style="color:#ffb74d" title="Inbound: node &rarr; hub">&#8592; IN</span>';

      html+='<div class="route-item">'
        +'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:3px">'
        +'<span style="font-size:10px;color:#7ec8f8;font-weight:bold">'+r.hub+'</span>'
        +'<span style="font-size:9px">'+dirArrow+'</span>'
        +latLabel
        +'</div>';

      if(r.slowest_link){
        html+='<div style="font-size:9px;color:#e57373;margin-bottom:3px">'
          +'&#9888; Slowest link: <b>'+r.slowest_link.node+'</b> ('+r.slowest_link.ms.toFixed(2)+' ms)'
          +'</div>';
      }

      if(MODE==='ip'&&(r.src_ip||r.dest_ip)){
        html+='<div style="font-size:9px;color:#5a7fa0;margin-bottom:3px">'
          +'Src: <span style="color:#4fc3f7">'+r.src_ip+'</span>'
          +' &nbsp; Dst: <span style="color:#4fc3f7">'+r.dest_ip+'</span>'
          +(r.occ>1?' &nbsp; x'+r.occ:'')
          +'</div>';
      } else if(r.occ>1){
        html+='<div style="font-size:9px;color:#5a7fa0;margin-bottom:3px">Occurrences: '+r.occ+'</div>';
      }

      html+='<div style="display:flex;flex-wrap:wrap;gap:2px;align-items:center">'+badges+'</div>'
           +'</div>';
    });
  } else {
    html+='<div class="detail-value" style="color:#5a7fa0">No route data</div>';
  }

  document.getElementById('d-body').innerHTML=html;
  document.getElementById('detail-panel').classList.add('visible');
}

function closeDetail(){
  document.getElementById('detail-panel').classList.remove('visible');
  selectedNode=null; buildList();
}

// RESET BUTTON
var rc=L.control({position:'topright'});
rc.onAdd=function(){
  var d=L.DomUtil.create('div');
  d.innerHTML='<button onclick="map.setView([38.5,-95],4)" '
    +'style="background:#0d1b2e;color:#4fc3f7;border:1px solid #1e3a6e;'
    +'padding:6px 10px;cursor:pointer;font-family:monospace;font-size:11px;border-radius:3px">'
    +'&#8962; RESET</button>';
  return d;
};
rc.addTo(map);

drawRoutes('all'); drawMarkers(); buildList();
''')
    a('</script>\n</body>\n</html>\n')

    html_str = ''.join(parts)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_str)

    size_kb = Path(output_path).stat().st_size / 1024
    print(f"\n  Done!  ->  {output_path}  ({size_kb:.0f} KB)")
    print(f"  Mode: {'IP Trail' if mode == 'ip' else 'Node Trail'}")
    print("  Open in Edge - no server needed.")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Generate ant-trail network map from flows file (XLSX or CSV)"
    )
    parser.add_argument(
        "--flows",
        required=True,
        help="Input flows file (.xlsx or .csv) - any of: "
             "Complete_Paths_IP_Enriched.xlsx, "
             "FlowsOutOfFtMeadeUURWMEA120.xlsx, "
             "All_Complete_Flows_Fort_Meade.csv, "
             "Consolidated_Complete_Flows_Fort_Meade.csv"
    )
    parser.add_argument(
        "--coords",
        default="master_dataframe_long.xlsx",
        help="Router coordinates (default: master_dataframe_long.xlsx)"
    )
    parser.add_argument(
        "--routers",
        default="master_dataframe_3.xlsx",
        help="Router loopback IPs (default: master_dataframe_3.xlsx)"
    )
    parser.add_argument(
        "--out",
        default="DISA_Meade_AntTrail.html",
        help="Output HTML filename (default: DISA_Meade_AntTrail.html)"
    )
    parser.add_argument(
        "--title",
        default="DISA Ft. Meade Routes",
        help="Map title (default: DISA Ft. Meade Routes)"
    )
    parser.add_argument(
        "--direction",
        choices=["outbound", "inbound", "both"],
        default="outbound",
        help="outbound = One-to-Many (hub is source, default); "
             "inbound = Many-to-One (hub is destination); "
             "both = combine both directions"
    )
    parser.add_argument(
        "--hub",
        action="append",
        default=None,
        help="Explicit hub/service-endpoint node name(s). Required when "
             "the data has no UURWMEA-prefixed router (e.g. Xyler's DAI "
             "service files, where many sites converge on a service "
             "endpoint like DK_SANJOSE_CA rather than a Fort Meade hub). "
             "Repeat the flag for multiple hubs: --hub DK_SANJOSE_CA "
             "--hub DK_SAN_JOSE_CA"
    )
    args = parser.parse_args()

    for f in [args.flows, args.coords, args.routers]:
        if not Path(f).exists():
            print(f"ERROR: File not found: {f}")
            sys.exit(1)

    print("=" * 60)
    print("  DAI Trail Map Generator  (unified)")
    print("=" * 60)

    # Auto-detect format
    mode = detect_mode(args.flows)
    print(f"  Input format detected: "
          f"{'IP Trail (Source_IP/Dest_IP present)' if mode == 'ip' else 'Node Trail (no IP columns)'}")
    print()

    router_coords = load_router_coords(args.coords)
    router_ips    = load_router_ips(args.routers)
    flows, node_ip = load_flows(args.flows, mode)
    map_data       = build_map_data(flows, node_ip, router_ips,
                                    router_coords, mode, args.direction,
                                    explicit_hubs=args.hub)
    write_html(map_data, args.out, args.title)


if __name__ == "__main__":
    main()

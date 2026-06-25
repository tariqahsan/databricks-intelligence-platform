"""
generate_hop_tree.py
━━━━━━━━━━━━━━━━━━━━
PROTOTYPE — built in response to Dr. Fransen's request:

  "It shows the logical hops from a Ft. Meade router out through the
   enterprise. The x axis is based on number of hops. The y axis is
   auto-generated and needs to be developed so that it automatically
   generates the best vertical spacing. Each originating router can
   generate a logical tree."

This is a DIFFERENT visualization paradigm from generate_trail_map.py:

    generate_trail_map.py (existing)     generate_hop_tree.py (this script)
    ─────────────────────────────────    ────────────────────────────────────
    Geographic map (Leaflet)              Logical tree (D3.js)
    X/Y = longitude/latitude              X = hop number, Y = auto-spaced
    Answers: "where do packets go"        Answers: "how does the path branch"
    One ant-trail line per destination    One tree edge per network hop

Both views read the SAME underlying flow data (Flow_Path, Total_Latency_ms,
per-segment latency). This script does not replace the map — it's a second
lens on the same data, per-segment latency parsing reused as-is from
generate_trail_map.py.

WHAT THIS PROTOTYPE DEMONSTRATES (for the team discussion, not final):
  1. Building a literal tree structure rooted at the hub, where paths
     that share a common prefix (e.g. two destinations both routing
     through UJEWMEA040 -> UJPWMEC010) are merged into shared trunk
     edges instead of being drawn as separate parallel lines.
  2. X axis = hop depth from the root (0, 1, 2, 3...) as Dr. Fransen
     specified.
  3. Y axis = automatically computed using a standard tree-layout
     algorithm (D3's cluster/tree layout, conceptually similar to
     Reingold-Tilford) so leaves never overlap regardless of how many
     there are or how unbalanced the branching is.
  4. Edges colored/labeled with per-link latency (already extracted by
     parse_hops_with_latency() in generate_trail_map.py).
  5. Architecture note for the NetScout/endpoint performance comment:
     each edge in the JSON has a single "metrics" object. Today it's
     populated from Flow_Path parsing. Later it can be populated from
     live NetScout/endpoint data WITHOUT changing the tree structure
     or the rendering code — only the data source for "metrics" swaps.

NOT YET DECIDED (for Tuesday's conversation):
  - Should multiple hubs (UURWMEA110, 120, 100, 440) render as separate
    trees side by side, or as tabs/toggle?
  - Should the "calculated propagation" OCONUS logic from the map view
    also color/flag edges here?
  - Is hop-count the right x-axis, or should it be cumulative latency
    (so slow paths visually stretch further right)? Dr. Fransen said
    hop count specifically, but cumulative latency is worth raising
    as an alternative for discussion.

Usage:
    python generate_hop_tree.py --flows All_Complete_Flows_Fort_Meade.csv --hub UURWMEA110
    python generate_hop_tree.py --flows Complete_Paths_IP_Enriched.xlsx --hub UURWMEA110 --out tree.html

Requirements:
    pip install pandas openpyxl
"""

import re
import json
import argparse
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("ERROR: pip install pandas openpyxl")
    sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
# Reused from generate_trail_map.py — same hop/latency parsing, unchanged
# ═════════════════════════════════════════════════════════════════════════════

def read_table(path, nrows=None):
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=nrows)
    return pd.read_excel(path, nrows=nrows)


def parse_hops_with_latency(path_str):
    """Wrapper kept for compatibility — delegates to parse_hops_with_ccsd."""
    return parse_hops_with_ccsd(path_str)


def parse_hops_with_ccsd(path_str):
    """
    Parses the Flow_Path format that includes CCSD circuit identifiers:

        NodeA  --(CCSD, latency)-->  NodeB  --(CCSD, latency)-->  NodeC

    The CCSD is the circuit/link identifier provisioned between two routers,
    e.g. UJEWMEA030 --(2PH0, 0.500ms)--> UJEWMEA040 means circuit 2PH0
    connects those two Fort Meade JPEs with 0.500ms measured latency.

    Multiple CCSDs on one link are comma-separated before the latency value:
        --(BDC7,BDG7,BDL6, 2.000ms)-->

    UJP_MESH blocks are replaced with a [MESH] placeholder so they do not
    break the node/link pairing -- they carry no CCSD in the source data.

    N/A latency appears only on first/last-mile endpoint links (customer
    site -> edge router). Transatlantic/OCONUS links have explicit ms values
    in Xyler's files (e.g. MQD3 = 22.500ms for the Atlantic DTM->AKI hop),
    so Haversine propagation-delay estimation is NOT needed here.

    Returns list of dicts:
        node     -- router or site name
        link_ms  -- latency of the link arriving at this node (float or None)
        ccsd     -- circuit identifier(s) for that link (str or None)
    """
    # Replace UJP_MESH block with a clean placeholder arrow
    cleaned = re.sub(
        r'\s*->\s*\[UJP_MESH\s*--[\d.]+ms-->\s*\]\s*->\s*',
        '  --([MESH], N/A)-->  ',
        path_str
    )

    parts     = re.split(r'\s+--\([^)]+\)-->\s+', cleaned)
    links_raw = re.findall(r'--\(([^)]+)\)-->', cleaned)

    # First node has no incoming link
    hops = [{"node": parts[0].strip(), "link_ms": None, "ccsd": None}]

    for i, raw in enumerate(links_raw):
        # Format: "CCSD [,CCSD2,...], latency_str"
        # Last comma-delimited token is always the latency
        tokens  = [t.strip() for t in raw.split(",")]
        lat_str = tokens[-1]
        ccsd    = ",".join(tokens[:-1]) if len(tokens) > 1 else None

        ms = None
        m = re.match(r"([\d.]+)ms", lat_str)
        if m:
            ms = float(m.group(1))

        node = parts[i + 1].strip() if i + 1 < len(parts) else "?"
        hops.append({"node": node, "link_ms": ms, "ccsd": ccsd})

    return hops


# ═════════════════════════════════════════════════════════════════════════════
# NEW — build the literal tree structure (this is the core of the prototype)
# ═════════════════════════════════════════════════════════════════════════════

def build_hop_tree(df, hub, mode, direction="outbound"):
    """
    Builds a nested tree rooted at `hub`.

    The key idea: multiple flows that share a path PREFIX are merged.
    e.g. if both DK_DALLAS_TX and DK_AUSTIN_TX route through
    UJEWMEA040 -> UJPWMEC010 before diverging, that shared trunk is
    ONE set of tree nodes with two children at the point where the
    paths actually split. This is what makes it a tree (Dr. Fransen's
    term) rather than 189 independent parallel lines.

    direction:
        "outbound" — One-to-Many: hub is the SOURCE in the raw flow data,
                     tree shows the hub fanning OUT to many destinations.
                     (the original/only mode this script supported)
        "inbound"  — Many-to-One: hub is the DESTINATION in the raw flow
                     data, tree shows many ORIGINATING sites converging
                     IN toward the hub. The hub is still drawn as the
                     root on the left (X=0); the path is walked in
                     reverse so hop distance still increases left-to-right
                     away from the hub, same as the outbound view.

    Each tree node carries:
      name          router/site name at this hop
      depth         hop number from the hub (Dr. Fransen's x-axis)
      link_ms       latency of the link arriving at this node (or None
                    if unmeasured in the source data)
      is_leaf       True if this node is an actual destination/origin
      dest_count    how many final destinations route through this node
                    (useful for line-weight: thicker = busier trunk)
      children      list of child tree nodes
    """
    if direction == "outbound":
        matched = df[df["Source"] == hub].drop_duplicates(
            ["Source", "Destination", "Flow_Path"]
        )
    else:  # inbound
        matched = df[df["Destination"] == hub].drop_duplicates(
            ["Source", "Destination", "Flow_Path"]
        )

    root = {
        "name": hub, "children": {}, "link_ms": None, "ccsd": None,
        "is_leaf": False, "total_latency": None, "dest_count": 0,
        "depth": 0,
    }

    skipped = 0
    for _, row in matched.iterrows():
        hops = parse_hops_with_latency(row["Flow_Path"])

        if direction == "inbound":
            # Walk the path backward so the hub (now the destination in
            # the raw data) becomes the root, and hop distance still
            # increases away from it. When reversing, each link's
            # latency must shift by one position: the latency that was
            # "arriving at node[i]" when walking forward becomes the
            # latency "arriving at node[i-1]" when walking backward,
            # since it's the same physical link described from the
            # opposite direction.
            names = [h["node"]    for h in hops]
            links = [h["link_ms"] for h in hops]
            ccsds = [h["ccsd"]    for h in hops]
            names = names[::-1]
            links = [None] + links[::-1][:-1]
            ccsds = [None] + ccsds[::-1][:-1]
            hops  = [{"node": n, "link_ms": l, "ccsd": c}
                     for n, l, c in zip(names, links, ccsds)]

        if not hops or hops[0]["node"] != hub:
            skipped += 1
            continue

        cursor = root
        cursor["dest_count"] += 1
        for depth, h in enumerate(hops[1:], start=1):
            key = h["node"]
            if key not in cursor["children"]:
                cursor["children"][key] = {
                    "name": key, "children": {}, "link_ms": h["link_ms"],
                    "ccsd": h["ccsd"],
                    "is_leaf": False, "total_latency": None,
                    "dest_count": 0, "depth": depth,
                }
            cursor = cursor["children"][key]
            cursor["dest_count"] += 1

        cursor["is_leaf"] = True
        cursor["total_latency"] = round(float(row["Total_Latency_ms"]), 3)
        if direction == "outbound":
            cursor["destination_ip"] = str(row.get("Dest_IP", "")) if mode == "ip" else None
        else:
            cursor["destination_ip"] = str(row.get("Source_IP", "")) if mode == "ip" else None

    def finalize(node):
        node["children"] = sorted(
            [finalize(c) for c in node["children"].values()],
            key=lambda c: -c["dest_count"]   # busiest branches first
        )
        return node

    tree = finalize(root)
    if skipped:
        print(f"    NOTE: {skipped} flow rows skipped (didn't start at hub)")
    return tree


def tree_stats(node, _depth=0):
    """Quick stats for the console — leaves, max depth, total tree size."""
    leaves = 1 if not node["children"] else sum(tree_stats(c, _depth+1)[0] for c in node["children"])
    depth  = _depth if not node["children"] else max(tree_stats(c, _depth+1)[1] for c in node["children"])
    size   = 1 + sum(tree_stats(c, _depth+1)[2] for c in node["children"])
    return leaves, depth, size


# ═════════════════════════════════════════════════════════════════════════════
# Load flows (same auto-detect approach as generate_trail_map.py)
# ═════════════════════════════════════════════════════════════════════════════

def detect_mode(flows_path):
    df = read_table(flows_path, nrows=0)
    cols = set(df.columns)
    return "ip" if ("Source_IP" in cols and "Dest_IP" in cols) else "node"


def load_flows(flows_path):
    df = read_table(flows_path)
    df.columns = [c.strip() for c in df.columns]
    return df


# ═════════════════════════════════════════════════════════════════════════════
# Write HTML — D3.js tree layout handles the auto vertical spacing
# ═════════════════════════════════════════════════════════════════════════════

def write_html(tree, output_path, hub, title, direction="outbound"):
    print(f"Writing HTML -> {output_path}")

    tree_json = json.dumps(tree, separators=(",", ":"))

    leaf_word     = "destinations" if direction == "outbound" else "origins"
    leaf_word_cap = "Destinations" if direction == "outbound" else "Origins"
    direction_phrase = ("fanning OUT to many destinations (read left&rarr;right)" if direction == "outbound"
                        else "many origins converging IN toward hub (read left&rarr;right)")
    dir_badge = "ONE-TO-MANY" if direction == "outbound" else "MANY-TO-ONE"
    dir_badge_color = "#c87ef7" if direction == "inbound" else "#4fc3a7"

    html = (
        '<!DOCTYPE html>\n<html>\n<head>\n'
        '<meta charset="UTF-8"/>\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0"/>\n'
        f'<title>{title}</title>\n'
        '<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>\n'
        '<style>\n'
        '*{box-sizing:border-box;margin:0;padding:0}\n'
        'body{font-family:\'Courier New\',monospace;background:#0a0e1a;color:#c8d8ff;overflow:hidden}\n'
        '#header{position:fixed;top:0;left:0;right:0;z-index:2000;\n'
        '  background:linear-gradient(90deg,#0d1b3e,#091225 60%,#0a0e1a);\n'
        '  border-bottom:1px solid #1e3a6e;padding:8px 16px;\n'
        '  display:flex;align-items:center;gap:16px}\n'
        '#header h1{font-size:14px;font-weight:700;color:#4fc3f7;letter-spacing:2px;text-transform:uppercase}\n'
        '.subtitle{font-size:11px;color:#5a7fa0}\n'
        '.badge{background:#1a3a5c;border:1px solid #2a5a8c;border-radius:3px;padding:2px 8px;font-size:10px;color:#7ec8f8}\n'
        '.dir-badge{border-radius:3px;padding:2px 8px;font-size:10px;font-weight:700;border:1px solid currentColor}\n'
        '#stats-bar{display:flex;gap:16px;align-items:center;margin-left:auto}\n'
        '.stat-item .val{font-size:13px;color:#4fc3f7;font-weight:700}\n'
        '.stat-item .lbl{font-size:9px;color:#5a7fa0}\n'
        '#chart{position:fixed;top:42px;left:0;right:0;bottom:0;overflow:auto;cursor:grab}\n'
        '#chart.dragging{cursor:grabbing}\n'
        '.node circle{stroke-width:1.5px}\n'
        '.node text{font-size:10px;fill:#c8d8ff;font-family:\'Courier New\',monospace}\n'
        '.link{fill:none;stroke-width:1.4px}\n'
        '.link-label{font-size:8px;fill:#5a9a6a}\n'
        '#legend{position:fixed;bottom:16px;left:16px;z-index:1500;\n'
        '  background:rgba(10,14,26,.92);border:1px solid #1e3a6e;\n'
        '  border-radius:4px;padding:10px 14px;font-size:10px}\n'
        '.legend-row{display:flex;align-items:center;gap:8px;margin-bottom:4px}\n'
        '.legend-dot{width:8px;height:8px;border-radius:50%}\n'
        '#tooltip{position:fixed;display:none;z-index:3000;\n'
        '  background:#0d1b2e;border:1px solid #1e3a6e;border-radius:4px;\n'
        '  padding:8px 12px;font-size:11px;color:#c8d8ff;pointer-events:none;max-width:300px}\n'
        '#x-axis-label{position:fixed;bottom:16px;right:16px;font-size:10px;color:#5a7fa0;letter-spacing:1px}\n'
        '</style>\n</head>\n<body>\n'
        '<div id="header">\n'
        f'  <h1>Logical Hop Tree</h1>\n'
        f'  <span class="subtitle">Rooted at {hub} &middot; {direction_phrase} &middot; '
        f'X = hop distance, Y = auto-spaced</span>\n'
        '  <div id="stats-bar">\n'
        f'    <div class="stat-item"><div class="val" id="s-leaves">-</div><div class="lbl">{leaf_word_cap.upper()}</div></div>\n'
        '    <div class="stat-item"><div class="val" id="s-depth">-</div><div class="lbl">MAX HOPS</div></div>\n'
        '    <div class="stat-item"><div class="val" id="s-nodes">-</div><div class="lbl">TREE NODES</div></div>\n'
        f'    <div class="dir-badge" style="color:{dir_badge_color}">{dir_badge}</div>\n'
        f'    <div class="badge">PROTOTYPE</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div id="chart"></div>\n'
        '<div id="tooltip"></div>\n'
        '<div id="x-axis-label">PROTOTYPE — for team discussion, not final</div>\n'
        '<div id="legend">\n'
        '  <div style="font-size:9px;color:#5a7fa0;letter-spacing:1.5px;margin-bottom:6px">LEGEND</div>\n'
        '  <div class="legend-row"><div class="legend-dot" style="background:#ff6b35"></div>Hub (root)</div>\n'
        '  <div class="legend-row"><div class="legend-dot" style="background:#7ec8f8"></div>Intermediate router</div>\n'
        f'  <div class="legend-row"><div class="legend-dot" style="background:#4fc3f7"></div>{leaf_word_cap[:-1]} (leaf)</div>\n'
        f'  <div class="legend-row">Edge thickness = how many {leaf_word} share this trunk</div>\n'
        '  <div class="legend-row">Edge label = per-link latency (ms), where measured</div>\n'
        '  <div class="legend-row" style="color:#ffb74d">Hover edge = CCSD circuit ID + latency</div>\n'
        '  <div class="legend-row" style="color:#5a9a6a">&#x25A0; blue &lt;1ms &nbsp; &#x25A0; amber 1&#8211;5ms &nbsp; &#x25A0; red &gt;5ms</div>\n'
        '</div>\n'
        '<script>\n'
        f'const TREE = {tree_json};\n'
        f'const DIRECTION = "{direction}";\n'
    )

    html += r'''
// ═══════════════════════════════════════════════════════════════════════════
// D3 TREE LAYOUT — this is what answers Dr. Fransen's "auto-generated Y axis"
// request. d3.tree() implements a layout algorithm (in the family of
// Reingold-Tilford) that automatically spaces siblings so they never
// overlap, regardless of how unbalanced the branching is.
// ═══════════════════════════════════════════════════════════════════════════

const root = d3.hierarchy(TREE, d => d.children);

// Count leaves to size the canvas — more destinations need more vertical room
const leafCount = root.leaves().length;
const maxDepth  = root.height;

// X axis = hop distance (Dr. Fransen's spec): fixed spacing per hop
const HOP_WIDTH = 160;
// Y axis = auto-spaced: give each leaf a fixed slot, d3 distributes the rest
const LEAF_HEIGHT = 22;

const width  = (maxDepth + 1) * HOP_WIDTH + 300;
const height = Math.max(leafCount * LEAF_HEIGHT, 600);

// d3.tree() with nodeSize swaps x/y conceptually: we want hops on the
// horizontal axis, so we lay out the tree vertically then swap coordinates
const treeLayout = d3.tree()
  .nodeSize([LEAF_HEIGHT, HOP_WIDTH])
  .separation((a, b) => a.parent === b.parent ? 1 : 1.3);

treeLayout(root);

// Swap so depth (d.y from d3) becomes our X, and the auto-spaced
// sibling position (d.x from d3) becomes our Y
root.each(d => { const t = d.x; d.x = d.y; d.y = t; });

// For INBOUND trees (many customer origins converging toward the hub),
// mirror the X axis so the hub sits on the RIGHT and origins sit on the
// LEFT. Read left-to-right, this now correctly tells the story "many
// customers -> converging on the hub" instead of reading like the hub
// is sending traffic out. Hop distance still increases away from the
// hub in both modes — only the screen direction of "away" flips.
if (DIRECTION === 'inbound') {
  const maxX = d3.max(root.descendants(), d => d.x);
  root.each(d => { d.x = maxX - d.x; });
}

const svg = d3.select('#chart')
  .append('svg')
  .attr('width', width + 100)
  .attr('height', height + 100)
  .append('g')
  .attr('transform', `translate(80,${height/2 + 50})`);

// ── Links ─────────────────────────────────────────────────────────────────
const linkGen = d3.linkHorizontal().x(d => d.x).y(d => d.y);

const links = svg.selectAll('.link')
  .data(root.links())
  .enter().append('path')
  .attr('class', 'link')
  .attr('d', linkGen)
  .attr('stroke', d => {
    const ms = d.target.data.link_ms;
    if (ms === null || ms === undefined) return '#2a3a5e';
    if (ms < 1) return '#4fc3f7';
    if (ms < 5) return '#ffb74d';
    return '#e57373';
  })
  .attr('stroke-width', d => Math.min(1 + Math.log2(d.target.data.dest_count + 1), 8))
  .attr('opacity', 0.75)
  .style('cursor', 'pointer')
  .on('mouseenter', function(event, d) { showLinkTooltip(event, d); })
  .on('mousemove',  function(event)    { positionTooltip(event); })
  .on('mouseleave', function()         { d3.select('#tooltip').style('display', 'none'); });

// Edge latency labels (only where measured)
svg.selectAll('.link-label')
  .data(root.links().filter(d => d.target.data.link_ms))
  .enter().append('text')
  .attr('class', 'link-label')
  .attr('x', d => (d.source.x + d.target.x) / 2)
  .attr('y', d => (d.source.y + d.target.y) / 2 - 4)
  .attr('text-anchor', 'middle')
  .text(d => d.target.data.link_ms.toFixed(2) + 'ms');

// ── Nodes ─────────────────────────────────────────────────────────────────
const node = svg.selectAll('.node')
  .data(root.descendants())
  .enter().append('g')
  .attr('class', 'node')
  .attr('transform', d => `translate(${d.x},${d.y})`)
  .on('mouseenter', function(event, d) { showTooltip(event, d); })
  .on('mousemove', function(event, d) { positionTooltip(event); })
  .on('mouseleave', function() { d3.select('#tooltip').style('display', 'none'); });

node.append('circle')
  .attr('r', d => d.depth === 0 ? 7 : d.data.is_leaf ? 4 : Math.min(3 + Math.log2(d.data.dest_count + 1), 7))
  .attr('fill', d => d.depth === 0 ? '#ff6b35' : d.data.is_leaf ? '#4fc3f7' : '#7ec8f8')
  .attr('stroke', '#0a0e1a');

node.append('text')
  .attr('dy', '-0.6em')
  .attr('x', d => {
    // Outbound: hub (root) and parent nodes sit LEFT of their children,
    // so their label goes left (Q2). Leaf nodes are rightmost, label goes right (Q1).
    // Inbound: tree is mirrored — hub sits RIGHT, origins sit LEFT.
    // Labels still go into the upper quadrant away from the connecting edge.
    const parentSideIsLeft = DIRECTION !== 'inbound';
    const labelGoesLeft = d.children ? parentSideIsLeft : !parentSideIsLeft;
    return labelGoesLeft ? -6 : 6;
  })
  .attr('text-anchor', d => {
    const parentSideIsLeft = DIRECTION !== 'inbound';
    const labelGoesLeft = d.children ? parentSideIsLeft : !parentSideIsLeft;
    return labelGoesLeft ? 'end' : 'start';
  })
  .text(d => d.data.name)
  .attr('opacity', d => d.data.is_leaf || d.depth === 0 ? 1 : 0.7);

// ── Tooltips ──────────────────────────────────────────────────────────────
const LEAF_WORD = DIRECTION === 'outbound' ? 'Destinations' : 'Origins';
const IP_LABEL  = DIRECTION === 'outbound' ? 'Destination IP' : 'Origin IP';

// Edge (circuit) pop-up — shows CCSD identifier and per-link latency
function showLinkTooltip(event, d) {
  const t   = d.target.data;
  const tt  = d3.select('#tooltip');
  // In outbound mode: traffic flows source → target (left → right in tree).
  // In inbound mode:  the tree is mirrored so source is hub-side and target
  //                   is origin-side, but actual traffic flows the other way:
  //                   target → source (origin toward hub). Swap display so
  //                   the arrow always shows the real traffic direction.
  const trafficFrom = DIRECTION === 'inbound' ? t.name              : d.source.data.name;
  const trafficTo   = DIRECTION === 'inbound' ? d.source.data.name  : t.name;
  let html  = `<b style="color:#5a9a6a">CIRCUIT / LINK</b><br/>`;
  html += `<span style="color:#c8d8ff">${trafficFrom}</span>`;
  html += ` <span style="color:#5a7fa0">&rarr;</span> `;
  html += `<span style="color:#c8d8ff">${trafficTo}</span><br/>`;
  if (t.ccsd) {
    html += `CCSD: <b style="color:#ffb74d">${t.ccsd}</b><br/>`;
  }
  if (t.link_ms !== null && t.link_ms !== undefined) {
    html += `Latency: <span style="color:#4fc3f7">${t.link_ms.toFixed(3)} ms</span><br/>`;
  } else {
    html += `Latency: <span style="color:#5a7fa0">not measured</span><br/>`;
  }
  const shared = DIRECTION === 'outbound' ? 'Destinations sharing this link' : 'Origins sharing this link';
  html += `${shared}: <span style="color:#7ec8f8">${t.dest_count}</span>`;
  tt.html(html).style('display', 'block');
  positionTooltip(event);
}

// Node (router/site) pop-up
function showTooltip(event, d) {
  const t = d3.select('#tooltip');
  let html = `<b style="color:${d.depth===0?'#ff6b35':d.data.is_leaf?'#4fc3f7':'#7ec8f8'}">${d.data.name}</b><br/>`;
  html += `Hop distance: ${d.depth}<br/>`;
  html += `${LEAF_WORD} through here: ${d.data.dest_count}<br/>`;
  if (d.data.link_ms !== null && d.data.link_ms !== undefined) {
    html += `Incoming link latency: <span style="color:#ffb74d">${d.data.link_ms.toFixed(2)} ms</span><br/>`;
  }
  if (d.data.is_leaf) {
    html += `Total path latency: <span style="color:#4fc3f7">${d.data.total_latency} ms</span><br/>`;
    if (d.data.destination_ip) html += `${IP_LABEL}: ${d.data.destination_ip}<br/>`;
  }
  t.html(html).style('display', 'block');
  positionTooltip(event);
}
function positionTooltip(event) {
  d3.select('#tooltip')
    .style('left', (event.clientX + 16) + 'px')
    .style('top', (event.clientY + 8) + 'px');
}

// ── Drag to pan (tree is often wider/taller than the viewport) ─────────────
const chartEl = document.getElementById('chart');
let isDown = false, startX, startY, scrollLeft, scrollTop;
chartEl.addEventListener('mousedown', e => {
  isDown = true; chartEl.classList.add('dragging');
  startX = e.pageX; startY = e.pageY;
  scrollLeft = chartEl.scrollLeft; scrollTop = chartEl.scrollTop;
});
window.addEventListener('mouseup', () => { isDown = false; chartEl.classList.remove('dragging'); });
window.addEventListener('mousemove', e => {
  if (!isDown) return;
  chartEl.scrollLeft = scrollLeft - (e.pageX - startX);
  chartEl.scrollTop  = scrollTop  - (e.pageY - startY);
});

// ── Stats ─────────────────────────────────────────────────────────────────
document.getElementById('s-leaves').textContent = leafCount;
document.getElementById('s-depth').textContent  = maxDepth;
document.getElementById('s-nodes').textContent  = root.descendants().length;
'''

    html += '\n</script>\n</body>\n</html>\n'

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = Path(output_path).stat().st_size / 1024
    print(f"\nDone! -> {output_path} ({size_kb:.0f} KB)")
    print("Open in Edge — no server needed (D3 loads from CDN).")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PROTOTYPE: render flow data as a logical hop-distance tree"
    )
    parser.add_argument("--flows", required=True, help="Flows file (.xlsx or .csv)")
    parser.add_argument("--hub", required=True, help="Root hub/router name, e.g. UURWMEA110")
    parser.add_argument("--out", default="hop_tree.html", help="Output HTML file")
    parser.add_argument("--title", default="Logical Hop Tree (Prototype)")
    parser.add_argument(
        "--direction",
        choices=["outbound", "inbound"],
        default="outbound",
        help="outbound = One-to-Many (hub is the Source in the flow data, "
             "tree fans OUT from the hub, default); "
             "inbound = Many-to-One (hub is the Destination in the flow "
             "data, tree shows many origins converging IN toward the hub)"
    )
    args = parser.parse_args()

    if not Path(args.flows).exists():
        print(f"ERROR: File not found: {args.flows}")
        sys.exit(1)

    print("=" * 60)
    print("  Logical Hop Tree Generator — PROTOTYPE")
    print("=" * 60)

    mode = detect_mode(args.flows)
    print(f"Input format: {'IP' if mode == 'ip' else 'Node'} mode")
    print(f"Direction: {args.direction}")

    df = load_flows(args.flows)
    print(f"Loaded {len(df)} flow rows")

    tree = build_hop_tree(df, args.hub, mode, args.direction)
    leaves, depth, size = tree_stats(tree)
    print(f"Tree built: {leaves} {'destinations' if args.direction == 'outbound' else 'origins'}, "
          f"{depth} max hop depth, {size} total tree nodes")

    write_html(tree, args.out, args.hub, args.title, args.direction)


if __name__ == "__main__":
    main()

// hop-tree.component.ts
import {
  Component, OnInit, OnDestroy, AfterViewInit,
  ElementRef, ViewChild, inject,
  Input, SimpleChanges, OnChanges
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import * as d3 from 'd3';
import { forkJoin, Subject, takeUntil } from 'rxjs';
import { NetworkFlowService } from '../../services/network-flow.service';
import {
  NetworkHubStat, NetworkLinkLatency, NetworkFlowSummaryRow,
  HopTreeNode, Dataset, Direction
} from '../../models/network-flow.models';

@Component({
  selector: 'app-hop-tree',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './hop-tree.component.html',
  styles: [`
    :host { display: flex; flex-direction: column; height: 100%; }

    .controls {
      display: flex; gap: 10px; align-items: center;
      padding: 10px 14px; background: #0d1b2e;
      border-bottom: 1px solid #1e3a6e; flex-wrap: wrap;
    }
    .ctrl-label { font-size: 10px; color: #5a7fa0; letter-spacing: 1px; }
    select, .btn-group button {
      background: #091225; color: #c8d8ff;
      border: 1px solid #1e3a6e; border-radius: 3px;
      font-family: 'Courier New', monospace; font-size: 11px;
      padding: 4px 10px; cursor: pointer;
    }
    select:focus { outline: none; border-color: #4fc3f7; }
    .btn-group { display: flex; }
    .btn-group button.active { background: #1a3a5c; border-color: #4fc3f7; color: #4fc3f7; }
    .badge {
      background: #1a3a5c; border: 1px solid #2a5a8c;
      border-radius: 3px; padding: 2px 8px;
      font-size: 10px; color: #7ec8f8; font-family: 'Courier New', monospace;
    }

    .tree-layout { flex: 1; display: flex; overflow: hidden; }

    .tree-container { flex: 1; position: relative; overflow: hidden; background: #070c18; }
    svg { width: 100%; height: 100%; }
    .link { fill: none; opacity: 0.7; }

    /* Side panel */
    .side-panel {
      width: 280px; background: #0a0e1a; border-left: 1px solid #1e3a6e;
      display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0;
    }
    .side-panel-header {
      padding: 10px 14px; border-bottom: 1px solid #1a2e4a;
      display: flex; align-items: center; justify-content: space-between;
    }
    .side-panel-title { font-size: 11px; color: #7ec8f8; letter-spacing: 1.5px; font-family: 'Courier New', monospace; }
    .side-panel-close { cursor: pointer; color: #5a7fa0; font-size: 14px; }
    .side-panel-close:hover { color: #c8d8ff; }
    .side-panel-body { flex: 1; overflow-y: auto; padding: 10px 14px; font-family: 'Courier New', monospace; }
    .side-panel-body::-webkit-scrollbar { width: 4px; }
    .side-panel-body::-webkit-scrollbar-thumb { background: #1e3a6e; }

    .node-name-badge { font-size: 13px; font-weight: 700; color: #4fc3f7; margin-bottom: 6px; }
    .node-type-tag {
      display: inline-block; border-radius: 3px; padding: 1px 6px;
      font-size: 9px; letter-spacing: 1px; margin-bottom: 10px;
    }
    .stat-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
    .stat-lbl { font-size: 10px; color: #5a7fa0; }
    .stat-val { font-size: 10px; color: #c8d8ff; }
    .section-title {
      font-size: 9px; color: #5a7fa0; letter-spacing: 1.5px; text-transform: uppercase;
      margin: 12px 0 6px; border-bottom: 1px solid #1a2e4a; padding-bottom: 4px;
    }
    .customer-item {
      display: flex; justify-content: space-between; align-items: center;
      padding: 4px 0; border-bottom: 1px solid #0f1e30;
    }
    .customer-name { font-size: 9px; color: #c8d8ff; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .customer-lat  { font-size: 9px; white-space: nowrap; margin-left: 6px; }
    .empty-panel {
      display: flex; align-items: center; justify-content: center;
      height: 80%; color: #2a4a6a; font-size: 11px;
      font-family: 'Courier New', monospace; text-align: center; padding: 20px; line-height: 1.6;
    }

    .tooltip {
      position: absolute; background: rgba(10,14,26,.95);
      border: 1px solid #1e3a6e; border-radius: 4px;
      padding: 8px 12px; font-family: 'Courier New', monospace;
      font-size: 11px; color: #c8d8ff; pointer-events: none;
      z-index: 100; white-space: nowrap;
    }
    .legend {
      position: absolute; bottom: 12px; left: 12px;
      background: rgba(10,14,26,.9); border: 1px solid #1e3a6e;
      border-radius: 4px; padding: 8px 12px; font-size: 10px; color: #c8d8ff;
    }
    .legend-row { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
    .legend-dot  { width: 8px; height: 8px; border-radius: 50%; }
    .legend-line { width: 20px; height: 2px; }
    .loading-overlay {
      position: absolute; inset: 0;
      display: flex; align-items: center; justify-content: center;
      background: rgba(7,12,24,.8); color: #4fc3f7;
      font-family: monospace; font-size: 13px; z-index: 50;
    }
  `]
})
export class HopTreeComponent implements OnInit, AfterViewInit, OnChanges, OnDestroy {

  @ViewChild('svgEl')   svgEl!:     ElementRef<SVGSVGElement>;
  @ViewChild('tooltip') tooltipEl!: ElementRef<HTMLDivElement>;

  @Input() dataset: Dataset = 'MEADE';

  private readonly svc      = inject(NetworkFlowService);
  private readonly destroy$ = new Subject<void>();

  // Template state
  hubs: string[]       = [];
  selectedHub          = 'UURWMEA110';
  direction: Direction = 'inbound';
  loading              = true;
  nodeCount            = 0;
  maxHops              = 0;
  originCount          = 0;

  // Side panel state
  selectedNode: HopTreeNode | null = null;
  selectedCustomers: { name: string; latencyMs: number; status: string }[] = [];

  // Data
  private hubStats:  NetworkHubStat[]       = [];
  private links:     NetworkLinkLatency[]   = [];
  private flowPairs: NetworkFlowSummaryRow[] = [];
  private treeData:  HopTreeNode | null     = null;
  private customersByNode = new Map<string, NetworkFlowSummaryRow[]>();

  // D3
  private svg!:  d3.Selection<SVGSVGElement, unknown, null, undefined>;
  private g!:    d3.Selection<SVGGElement,   unknown, null, undefined>;
  private zoom!: d3.ZoomBehavior<SVGSVGElement, unknown>;

  // ── Colours ────────────────────────────────────────────────────────────

  private linkColor(ms: number | undefined): string {
    if (ms == null || ms === 0) return '#4fc3f7';
    if (ms < 1)  return '#4fc3f7';
    if (ms < 5)  return '#ffb74d';
    return '#e57373';
  }

  latencyStyle(ms: number): string { return `color:${this.linkColor(ms)}`; }

  private nodeColor(type: string): string {
    const m: Record<string, string> = {
      CORE_HUB: '#ff6b35', MESH_NODE: '#ce93d8',
      EDGE_NODE: '#4db6ac', CUSTOMER_SITE: '#4fc3f7', TRANSIT: '#78909c',
    };
    return m[type] ?? '#78909c';
  }

  nodeTagStyle(type: string): string {
    const c = this.nodeColor(type);
    return `background:${c}22;border:1px solid ${c};color:${c}`;
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────

  ngOnInit(): void        { this.loadData(); }
  ngAfterViewInit(): void { this.initSvg(); }
  ngOnChanges(c: SimpleChanges): void {
    if (c['dataset'] && !c['dataset'].firstChange) this.loadData();
  }
  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  // ── Data loading ───────────────────────────────────────────────────────

  loadData(): void {
    this.loading = true;
    this.selectedNode = null;
    forkJoin({
      hubs:      this.svc.getAvailableHubs(this.dataset),
      hubStats:  this.svc.getHubStats('ALL'),
      links:     this.svc.getLinkLatency('ALL'),
      flowPairs: this.svc.getFlowSummary(this.dataset),
    })
    .pipe(takeUntil(this.destroy$))
    .subscribe({
      next: ({ hubs, hubStats, links, flowPairs }) => {
        this.hubs      = hubs.length ? hubs : [this.selectedHub];
        this.hubStats  = hubStats;
        this.links     = links;
        this.flowPairs = flowPairs;
        if (!this.hubs.includes(this.selectedHub)) this.selectedHub = this.hubs[0];
        this.originCount = flowPairs.filter(p => /^D[A-Z]_/.test(p.sourceNode)).length;
        this.loading = false;
        this.buildAndRender();
      },
      error: () => { this.loading = false; }
    });
  }

  onHubChange():       void { this.selectedNode = null; this.buildAndRender(); }
  onDirectionChange(): void { this.selectedNode = null; this.buildAndRender(); }

  // ── Tree construction ─────────────────────────────────────────────────

  private buildTree(): HopTreeNode {
    // Adjacency list from measured link_latency
    const adj = new Map<string, { node: string; latency: number; circuitId: string }[]>();
    const addEdge = (from: string, to: string, lat: number, cid: string) => {
      if (!adj.has(from)) adj.set(from, []);
      adj.get(from)!.push({ node: to, latency: lat, circuitId: cid });
    };
    for (const lnk of this.links) {
      addEdge(lnk.fromNode, lnk.toNode, lnk.avgLatencyMs, lnk.circuitId);
      addEdge(lnk.toNode, lnk.fromNode, lnk.avgLatencyMs, lnk.circuitId);
    }

    // Type + flow lookup
    const typeMap = new Map<string, string>();
    const flowMap = new Map<string, number>();
    for (const h of this.hubStats) {
      typeMap.set(h.hubNode, h.hubType);
      flowMap.set(h.hubNode, h.flowsThrough);
    }

    // Synthetic hub → edge-node connections
    // UURWMEA110 absent from link_latency (N/A last-mile filtered)
    if (!adj.has(this.selectedHub) || !adj.get(this.selectedHub)!.length) {
      const inGraph = new Set(adj.keys());
      const nearEdge = this.hubStats
        .filter(h => h.hubType === 'EDGE_NODE' && inGraph.has(h.hubNode))
        .sort((a, b) => b.flowsThrough - a.flowsThrough)
        .slice(0, 6);
      if (!adj.has(this.selectedHub)) adj.set(this.selectedHub, []);
      for (const en of nearEdge) {
        addEdge(this.selectedHub, en.hubNode, 0, 'N/A');
        addEdge(en.hubNode, this.selectedHub, 0, 'N/A');
      }
    }

    // BFS — ROUTER NODES ONLY (customer sites shown in side panel, not SVG)
    // This keeps the tree readable regardless of customer site count.
    const visited = new Set<string>([this.selectedHub]);
    const root: HopTreeNode = {
      name: this.selectedHub, nodeType: 'CORE_HUB',
      flowsThrough: flowMap.get(this.selectedHub) ?? 0, children: []
    };

    interface Q { node: HopTreeNode; depth: number }
    const queue: Q[] = [{ node: root, depth: 0 }];
    let maxDepth = 0;

    while (queue.length) {
      const { node, depth } = queue.shift()!;
      if (depth >= 12) continue;
      const neighbors = (adj.get(node.name) ?? []).slice()
        .sort((a, b) => b.latency - a.latency);

      for (const nb of neighbors) {
        if (visited.has(nb.node)) continue;
        // Skip customer site prefixes — routers only in tree
        if (/^D[A-Z]_/.test(nb.node)) continue;
        visited.add(nb.node);
        const child: HopTreeNode = {
          name:         nb.node,
          nodeType:     typeMap.get(nb.node) ?? 'TRANSIT',
          latency:      nb.latency === 0 ? undefined : nb.latency,
          circuitId:    nb.circuitId === 'N/A' ? undefined : nb.circuitId,
          flowsThrough: flowMap.get(nb.node) ?? 0,
          children:     []
        };
        node.children.push(child);
        maxDepth = Math.max(maxDepth, depth + 1);
        queue.push({ node: child, depth: depth + 1 });
      }
    }

    // Build side-panel customer lookup
    // Hub shows ALL customer pairs; leaf nodes share them round-robin
    this.customersByNode.clear();
    const leafArr: string[] = [];
    const findLeaves = (n: HopTreeNode) => {
      if (!n.children.length) leafArr.push(n.name);
      n.children.forEach(findLeaves);
    };
    findLeaves(root);

    const custPairs = this.flowPairs.filter(p => /^D[A-Z]_/.test(p.sourceNode));

    // Hub gets all customers
    this.customersByNode.set(this.selectedHub, [...custPairs]);

    // Distribute across leaf nodes
    custPairs.forEach((pair, i) => {
      const leaf = leafArr[i % (leafArr.length || 1)];
      if (leaf) {
        const list = this.customersByNode.get(leaf) ?? [];
        list.push(pair);
        this.customersByNode.set(leaf, list);
      }
    });

    this.maxHops   = maxDepth;
    this.nodeCount = visited.size;
    return root;
  }

  // ── Node click ─────────────────────────────────────────────────────────

  selectTreeNode(node: HopTreeNode): void {
    this.selectedNode = node;
    const pairs = this.customersByNode.get(node.name) ?? [];
    this.selectedCustomers = pairs
      .map(p => ({
        name:      p.sourceNode,
        latencyMs: typeof p.avgLatencyMs === 'number'
                     ? p.avgLatencyMs
                     : parseFloat(String(p.avgLatencyMs)),
        status:    p.healthStatus,
      }))
      .sort((a, b) => a.latencyMs - b.latencyMs);
  }

  closePanel(): void { this.selectedNode = null; }

  // ── D3 rendering ────────────────────────────────────────────────────────

  private initSvg(): void {
    if (!this.svgEl) return;
    this.svg  = d3.select(this.svgEl.nativeElement);
    this.g    = this.svg.append('g');
    this.zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.05, 4])
      .on('zoom', (e) => this.g.attr('transform', e.transform));
    this.svg.call(this.zoom);
    if (this.treeData) this.render();
  }

  buildAndRender(): void {
    this.treeData = this.buildTree();
    if (this.g) this.render();
  }

  private render(): void {
    if (!this.treeData || !this.g || !this.svgEl) return;
    this.g.selectAll('*').remove();

    const el     = this.svgEl.nativeElement;
    const W      = el.clientWidth  || 900;
    const H      = el.clientHeight || 600;
    const margin = { top: 20, right: 200, bottom: 20, left: 200 };
    const iW     = W - margin.left - margin.right;
    const iH     = H - margin.top  - margin.bottom;

    const tree = d3.tree<HopTreeNode>().size([iH, iW]);
    const root = d3.hierarchy<HopTreeNode>(this.treeData);
    tree(root);

    if (this.direction === 'inbound') {
      root.each((d: any) => { d.y = iW - d.y; });
    }

    const gInner = this.g.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Glow
    const defs = this.svg.select<SVGDefsElement>('defs').empty()
      ? this.svg.append<SVGDefsElement>('defs')
      : this.svg.select<SVGDefsElement>('defs');
    const flt = defs.append('filter').attr('id', 'glow');
    flt.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const fm = flt.append('feMerge');
    fm.append('feMergeNode').attr('in', 'coloredBlur');
    fm.append('feMergeNode').attr('in', 'SourceGraphic');

    // Links
    gInner.selectAll<SVGPathElement, d3.HierarchyLink<HopTreeNode>>('.link')
      .data(root.links())
      .join('path')
      .attr('class', 'link')
      .attr('fill', 'none')
      .attr('stroke', (d: any) => this.linkColor(d.target.data.latency))
      .attr('stroke-width', (d: any) => {
        const f: number = d.target.data.flowsThrough ?? 0;
        return f > 1000 ? 2.5 : f > 300 ? 1.8 : 1.2;
      })
      .attr('opacity', 0.7)
      .attr('d', d3.linkHorizontal<d3.HierarchyLink<HopTreeNode>, d3.HierarchyPointNode<HopTreeNode>>()
        .x((n: any) => n.y).y((n: any) => n.x) as any);

    // Latency labels
    gInner.selectAll<SVGTextElement, d3.HierarchyLink<HopTreeNode>>('.link-label')
      .data(root.links().filter((d: any) => d.target.data.latency != null && d.target.data.latency > 0))
      .join('text')
      .attr('class', 'link-label')
      .attr('x', (d: any) => (d.source.y + d.target.y) / 2)
      .attr('y', (d: any) => (d.source.x + d.target.x) / 2 - 4)
      .attr('text-anchor', 'middle')
      .attr('font-size', '8px')
      .attr('fill', (d: any) => this.linkColor(d.target.data.latency))
      .attr('font-family', 'Courier New')
      .text((d: any) => `${(d.target.data.latency as number).toFixed(2)}ms`);

    // Nodes
    const self = this;
    const node = gInner.selectAll<SVGGElement, unknown>('.node')
      .data(root.descendants())
      .join('g')
      .attr('class', 'node')
      .attr('transform', (d: any) => `translate(${d.y},${d.x})`)
      .style('cursor', 'pointer')
      .on('mouseover', (event: MouseEvent, d: any) => this.showTooltip(event, d.data))
      .on('mouseout',  () => this.hideTooltip())
      .on('click',     (_: MouseEvent, d: any) => this.selectTreeNode(d.data));

    node.append('circle')
      .attr('r',            (d: any) => d.depth === 0 ? 10 : 6)
      .attr('fill',         (d: any) => self.nodeColor(d.data.nodeType))
      .attr('stroke',       (d: any) => d3.color(self.nodeColor(d.data.nodeType))?.brighter(0.5)?.toString() ?? '#fff')
      .attr('stroke-width', 1.5)
      .attr('filter',       (d: any) => d.depth === 0 ? 'url(#glow)' : null);

    node.append('text')
      .attr('dy', '0.31em')
      .attr('x', (d: any) => {
        const hc = d.children?.length;
        return this.direction === 'inbound' ? (hc ? 12 : -10) : (hc ? -10 : 12);
      })
      .attr('text-anchor', (d: any) => {
        const hc = d.children?.length;
        return this.direction === 'inbound' ? (hc ? 'start' : 'end') : (hc ? 'end' : 'start');
      })
      .text((d: any) => {
        const n: string = d.data.name;
        return n.length > 18 ? n.substring(0, 16) + '..' : n;
      })
      .attr('font-size',   (d: any) => d.depth === 0 ? '11px' : '9px')
      .attr('font-weight', (d: any) => d.depth === 0 ? '700' : '400')
      .attr('fill',        (d: any) => d.depth === 0 ? '#ff6b35' : '#c8d8ff')
      .attr('font-family', 'Courier New');

    // Auto-fit
    try {
      const bounds = (gInner.node() as SVGGElement).getBBox();
      if (bounds.width > 0 && bounds.height > 0) {
        const scale = Math.min(0.88 * W / bounds.width, 0.88 * H / bounds.height, 1);
        const tx    = (W - scale * bounds.width)  / 2 - scale * bounds.x;
        const ty    = (H - scale * bounds.height) / 2 - scale * bounds.y;
        this.svg.call(this.zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      }
    } catch { /**/ }
  }

  resetZoom(): void {
    this.svg?.call(this.zoom.transform, d3.zoomIdentity);
    this.buildAndRender();
  }

  // ── Tooltip ─────────────────────────────────────────────────────────────

  private showTooltip(event: MouseEvent, node: HopTreeNode): void {
    if (!this.tooltipEl) return;
    const cust = this.customersByNode.get(node.name)?.length ?? 0;
    const el = this.tooltipEl.nativeElement;
    el.style.display = 'block';
    el.style.left    = `${event.offsetX + 14}px`;
    el.style.top     = `${event.offsetY - 20}px`;
    el.innerHTML = `
      <div style="color:#4fc3f7;font-weight:700;margin-bottom:4px">${node.name}</div>
      <div style="color:#7ec8f8">Type: ${node.nodeType}</div>
      ${node.flowsThrough ? `<div>Flows through: <b style="color:#4fc3f7">${node.flowsThrough.toLocaleString()}</b></div>` : ''}
      ${node.latency != null ? `<div>Latency: <b style="color:${this.linkColor(node.latency)}">${node.latency.toFixed(3)} ms</b></div>` : ''}
      ${node.circuitId ? `<div style="color:#5a7fa0">Circuit: ${node.circuitId}</div>` : ''}
      ${cust ? `<div style="color:#4db6ac;margin-top:3px">&#9432; Click to see ${cust} customer sites</div>` : ''}
    `;
  }

  private hideTooltip(): void {
    if (this.tooltipEl) this.tooltipEl.nativeElement.style.display = 'none';
  }
}
// trail-map.component.ts
import {
  Component, OnInit, OnDestroy, AfterViewInit,
  ElementRef, ViewChild, inject, Input, OnChanges, SimpleChanges
} from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import * as L from 'leaflet';
import 'leaflet-ant-path';
import { forkJoin, Subject, takeUntil } from 'rxjs';
import { NetworkFlowService } from '../../services/network-flow.service';
import {
  NetworkFlowSummaryRow, RouterCoordinates,
  MapRoute, Dataset
} from '../../models/network-flow.models';

const FORT_MEADE_LAT = 39.083333;
const FORT_MEADE_LNG = -76.733333;
const FORT_MEADE: L.LatLngExpression = [FORT_MEADE_LAT, FORT_MEADE_LNG];

function routeColor(ms: number): string {
  if (ms <  3) return '#4fc3f7';
  if (ms < 10) return '#ffb74d';
  return '#e57373';
}

@Component({
  selector: 'app-trail-map',
  standalone: true,
  imports: [CommonModule, FormsModule, DecimalPipe],
  templateUrl: './trail-map.component.html',
  styles: [`
    :host { display: flex; flex-direction: column; height: 100%; }

    .controls {
      display: flex; gap: 10px; align-items: center;
      padding: 10px 14px; background: #0d1b2e;
      border-bottom: 1px solid #1e3a6e; flex-wrap: wrap;
    }
    .ctrl-label { font-size: 10px; color: #5a7fa0; letter-spacing: 1px; }
    .btn-group { display: flex; }
    .btn-group button {
      background: #091225; color: #c8d8ff;
      border: 1px solid #1e3a6e; font-family: 'Courier New',monospace;
      font-size: 11px; padding: 4px 10px; cursor: pointer;
    }
    .btn-group button.active { background: #1a3a5c; border-color: #4fc3f7; color: #4fc3f7; }
    .badge {
      background: #1a3a5c; border: 1px solid #2a5a8c;
      border-radius: 3px; padding: 2px 8px;
      font-size: 10px; color: #7ec8f8; font-family: 'Courier New',monospace;
    }
    input[type=text] {
      background: #091225; color: #c8d8ff; border: 1px solid #1e3a6e;
      border-radius: 3px; font-family: 'Courier New',monospace;
      font-size: 11px; padding: 4px 8px; width: 180px;
    }
    input[type=text]:focus { outline: none; border-color: #4fc3f7; }

    .map-layout { flex: 1; display: flex; overflow: hidden; min-height: 0; }

    /* CRITICAL: Leaflet container MUST have explicit height */
    .map-wrap { flex: 1; position: relative; }
    #trail-leaflet-map { position: absolute; inset: 0; }

    .sidebar {
      width: 300px; background: #0a0e1a;
      border-left: 1px solid #1e3a6e;
      display: flex; flex-direction: column; overflow: hidden;
    }
    .sidebar-header {
      padding: 10px 12px; border-bottom: 1px solid #1a2e4a;
      font-size: 11px; color: #7ec8f8; letter-spacing: 1.5px;
      font-family: 'Courier New', monospace;
    }
    .node-list { flex: 1; overflow-y: auto; }
    .node-list::-webkit-scrollbar { width: 4px; }
    .node-list::-webkit-scrollbar-thumb { background: #1e3a6e; }
    .node-item {
      padding: 7px 12px; border-bottom: 1px solid #0f1e30;
      cursor: pointer; display: flex; align-items: center; gap: 8px;
      transition: background .15s; font-family: 'Courier New', monospace;
    }
    .node-item:hover  { background: #0d1b2e; }
    .node-item.active { background: #0f2040; border-left: 2px solid #4fc3f7; }
    .node-dot  { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .node-name { font-size: 10px; color: #c8d8ff; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .node-lat  { font-size: 10px; text-align: right; white-space: nowrap; min-width: 52px; }

    .detail-panel {
      border-top: 1px solid #1a2e4a; padding: 10px 12px;
      font-size: 11px; max-height: 220px; overflow-y: auto;
      font-family: 'Courier New', monospace;
    }
    .d-name     { color: #4fc3f7; font-weight: 700; margin-bottom: 6px; font-size: 12px; }
    .detail-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
    .detail-lbl { color: #5a7fa0; font-size: 10px; }
    .detail-val { color: #c8d8ff; font-size: 10px; }

    .loading-msg {
      flex: 1; display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      color: #4fc3f7; font-family: monospace; font-size: 13px; gap: 8px;
    }
    .warn-bar {
      padding: 6px 12px; background: #1a2000; border-bottom: 1px solid #4a4a00;
      font-size: 10px; color: #ffb74d; font-family: monospace;
    }
    .debug-bar {
      padding: 4px 12px; background: #001020; border-bottom: 1px solid #002040;
      font-size: 9px; color: #3a6a9a; font-family: monospace;
    }
  `]
})
export class TrailMapComponent implements OnInit, AfterViewInit, OnChanges, OnDestroy {

  @ViewChild('mapEl') mapEl!: ElementRef<HTMLDivElement>;
  @Input() dataset: Dataset = 'MEADE';

  private readonly svc      = inject(NetworkFlowService);
  private readonly destroy$  = new Subject<void>();

  loading             = true;
  coordsMissingCount  = 0;
  searchTerm          = '';
  latencyFilter       = 'all';
  selectedNode: MapRoute | null = null;
  visibleRoutes: MapRoute[] = [];
  routeCount          = 0;

  // Debug stats shown in UI
  debugCoordsLoaded   = 0;
  debugPairsReceived  = 0;
  debugRoutesBuilt    = 0;

  private allRoutes:  MapRoute[]         = [];
  private coords:     RouterCoordinates  = {};

  private map!:        L.Map;
  private antPaths:    any[]             = [];
  private markers:     L.CircleMarker[]  = [];
  private mapReady     = false;

  // ── Lifecycle ─────────────────────────────────────────────────────────

  ngOnInit(): void        { this.loadData(); }
  ngAfterViewInit(): void { this.tryInitMap(); }

  ngOnChanges(c: SimpleChanges): void {
    if (c['dataset'] && !c['dataset'].firstChange) {
      this.mapReady = false;
      this.map?.remove();
      this.map = undefined as any;
      this.antPaths = []; this.markers = [];
      this.loadData();
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next(); this.destroy$.complete();
    this.map?.remove();
  }

  // ── Data loading ───────────────────────────────────────────────────────

  loadData(): void {
    this.loading = true;
    forkJoin({
      flowSummary: this.svc.getFlowSummary(this.dataset),
      coords:      this.svc.getRouterCoordinates(),
    })
    .pipe(takeUntil(this.destroy$))
    .subscribe({
      next: ({ flowSummary, coords }) => {
        this.coords            = coords;
        this.debugCoordsLoaded = Object.keys(coords).length;
        this.debugPairsReceived = flowSummary.length;
        this.buildRoutes(flowSummary);
        this.loading = false;
        // Small delay to ensure *ngIf has rendered the map div
        setTimeout(() => this.tryInitMap(), 100);
      },
      error: (err) => {
        console.error('Trail map load error:', err);
        this.loading = false;
        setTimeout(() => this.tryInitMap(), 100);
      }
    });
  }

  // ── Route building ─────────────────────────────────────────────────────

  private buildRoutes(pairs: NetworkFlowSummaryRow[]): void {
    const routes: MapRoute[] = [];
    let missing = 0;
    let skippedSameCoords = 0;

    for (const pair of pairs) {
      const custCoord = this.coords[pair.sourceNode];
      const hubCoord  = this.coords[pair.destNode]
                     ?? { lat: FORT_MEADE_LAT, lng: FORT_MEADE_LNG };

      if (!custCoord) {
        missing++;
        continue;
      }

      // Skip hub-to-hub flows (same coordinates)
      if (Math.abs(custCoord.lat - hubCoord.lat) < 0.01 &&
          Math.abs(custCoord.lng - hubCoord.lng) < 0.01) {
        skippedSameCoords++;
        continue;
      }

      const latMs = typeof pair.avgLatencyMs === 'number'
        ? pair.avgLatencyMs
        : parseFloat(String(pair.avgLatencyMs));

      routes.push({
        customerNode: pair.sourceNode,
        hubNode:      pair.destNode,
        latencyMs:    latMs,
        linkHealth:   pair.healthStatus,
        flowsThrough: pair.flowCount,
        hubLat:       hubCoord.lat,
        hubLng:       hubCoord.lng,
        customerLat:  custCoord.lat,
        customerLng:  custCoord.lng,
      });
    }

    this.coordsMissingCount = missing;
    this.allRoutes          = routes.sort((a, b) => b.flowsThrough - a.flowsThrough);
    this.debugRoutesBuilt   = routes.length;
    console.log(`Trail map: ${pairs.length} pairs, ${routes.length} routes, ${missing} missing coords, ${skippedSameCoords} same-coords skipped`);
    this.applyFilters();
  }

  // ── Map initialization (always runs — does not depend on route count) ──

  private tryInitMap(): void {
    if (this.mapReady || !this.mapEl?.nativeElement) return;
    this.mapReady = true;

    this.map = L.map(this.mapEl.nativeElement, {
      center:       FORT_MEADE,
      zoom:         4,
      preferCanvas: true,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      subdomains:  'abcd',
      maxZoom:     20,
    }).addTo(this.map);

    // Hub marker — always visible even with 0 routes
    L.circleMarker(FORT_MEADE, {
      radius: 12, color: '#ff6b35', fillColor: '#ff6b35',
      fillOpacity: 0.9, weight: 2,
    })
    .bindPopup('<b style="color:#ff6b35;font-family:monospace">Fort Meade Hub</b><br/>UURWMEA110 / UURWMEA120')
    .addTo(this.map);

    // Draw routes if already available
    if (this.visibleRoutes.length) this.drawRoutes();
  }

  // ── Route drawing ──────────────────────────────────────────────────────

  private clearLayers(): void {
    this.antPaths.forEach(p => this.map?.removeLayer(p));
    this.markers.forEach(m  => this.map?.removeLayer(m));
    this.antPaths = []; this.markers = [];
  }

  private drawRoutes(): void {
    if (!this.map) return;
    this.clearLayers();

    for (const r of this.visibleRoutes) {
      const clr = routeColor(r.latencyMs);

      try {
        const path = (L.polyline as any).antPath(
          [[r.hubLat, r.hubLng], [r.customerLat, r.customerLng]],
          {
            color:      clr,
            weight:     r.flowsThrough > 10 ? 2.0 : 1.2,
            opacity:    0.7,
            delay:      800 + Math.floor(Math.random() * 600),
            dashArray:  [10, 20],
            pulseColor: '#ffffff',
          }
        );
        path.addTo(this.map);
        path.on('click', () => this.selectNode(r));
        this.antPaths.push(path);
      } catch { /* ant-path not loaded */ }

      const marker = L.circleMarker([r.customerLat, r.customerLng], {
        radius: r.flowsThrough > 10 ? 6 : 4,
        color: clr, fillColor: clr, fillOpacity: 0.85, weight: 1.5,
      })
      .bindPopup(this.buildPopup(r))
      .addTo(this.map);

      marker.on('click', () => this.selectNode(r));
      this.markers.push(marker);
    }

    this.routeCount = this.visibleRoutes.length;
  }

  private buildPopup(r: MapRoute): string {
    return `
      <div style="font-family:'Courier New',monospace;font-size:11px;min-width:200px">
        <b style="color:#4fc3f7;font-size:12px">${r.customerNode}</b><br/>
        <hr style="border-color:#1e3a6e;margin:4px 0"/>
        Latency: <b style="color:${routeColor(r.latencyMs)}">${r.latencyMs.toFixed(3)} ms</b><br/>
        Flows:   <b>${r.flowsThrough.toLocaleString()}</b><br/>
        Status:  <span style="color:${routeColor(r.latencyMs)}">${r.linkHealth}</span><br/>
        Hub:     ${r.hubNode}<br/>
        Coords:  ${r.customerLat.toFixed(4)}, ${r.customerLng.toFixed(4)}
      </div>`;
  }

  // ── Filters ────────────────────────────────────────────────────────────

  applyFilters(): void {
    const q = this.searchTerm.toLowerCase();
    this.visibleRoutes = this.allRoutes.filter(r => {
      if (q && !r.customerNode.toLowerCase().includes(q)) return false;
      if (this.latencyFilter === 'low'  && r.latencyMs >= 3)  return false;
      if (this.latencyFilter === 'med'  && (r.latencyMs < 3 || r.latencyMs >= 10)) return false;
      if (this.latencyFilter === 'high' && r.latencyMs < 10)  return false;
      return true;
    });
    if (this.mapReady) this.drawRoutes();
  }

  setFilter(f: string): void { this.latencyFilter = f; this.applyFilters(); }

  selectNode(r: MapRoute): void {
    this.selectedNode = r;
    this.map?.flyTo([r.customerLat, r.customerLng], 7, { duration: 1.2 });
  }

  closeDetail(): void { this.selectedNode = null; }

  latencyColor(ms: number): string { return routeColor(ms); }
  latencyStyle(ms: number): string { return `color:${routeColor(ms)}`; }
}
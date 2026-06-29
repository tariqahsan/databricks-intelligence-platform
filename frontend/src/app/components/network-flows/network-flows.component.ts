// network-flows.component.ts
import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FlowKpisComponent }  from '../flow-kpis/flow-kpis.component';
import { HopTreeComponent }   from '../hop-tree/hop-tree.component';
import { TrailMapComponent }  from '../trail-map/trail-map.component';
import { Dataset } from '../../models/network-flow.models';

type ActiveTab = 'hop-tree' | 'trail-map';

@Component({
  selector: 'app-network-flows',
  standalone: true,
  imports: [CommonModule, FlowKpisComponent, HopTreeComponent, TrailMapComponent],
  templateUrl: './network-flows.component.html',
  styles: [`
    :host {
      display: flex; flex-direction: column;
      height: 100%; background: #070c18; color: #c8d8ff;
      font-family: 'Courier New', monospace;
    }

    .page-header {
      display: flex; align-items: center; gap: 16px;
      padding: 10px 16px;
      background: linear-gradient(90deg, #0d1b3e, #091225 60%, #0a0e1a);
      border-bottom: 1px solid #1e3a6e; flex-shrink: 0;
    }
    .page-title { font-size: 13px; font-weight: 700; color: #4fc3f7; letter-spacing: 2px; }
    .page-sub   { font-size: 10px; color: #5a7fa0; letter-spacing: 1px; }
    .ds-label   { font-size: 10px; color: #5a7fa0; margin-left: auto; }
    .ds-btn-group { display: flex; }
    .ds-btn-group button {
      background: #091225; color: #c8d8ff;
      border: 1px solid #1e3a6e; font-family: 'Courier New',monospace;
      font-size: 11px; padding: 4px 12px; cursor: pointer;
    }
    .ds-btn-group button.active {
      background: #1a3a5c; border-color: #4fc3f7; color: #4fc3f7;
    }

    .tab-bar {
      display: flex; border-bottom: 1px solid #1e3a6e; flex-shrink: 0;
      background: #070c18; align-items: center;
    }
    .tab {
      padding: 9px 20px; font-size: 11px; letter-spacing: 1.5px;
      cursor: pointer; color: #5a7fa0; border-bottom: 2px solid transparent;
      transition: all .15s; text-transform: uppercase;
    }
    .tab:hover  { color: #7ec8f8; }
    .tab.active { color: #4fc3f7; border-bottom-color: #4fc3f7; }

    .expand-btn {
      margin-left: auto; margin-right: 12px;
      background: #091225; color: #5a7fa0;
      border: 1px solid #1e3a6e; border-radius: 3px;
      padding: 4px 10px; cursor: pointer;
      font-family: 'Courier New', monospace; font-size: 11px;
      transition: all .15s;
    }
    .expand-btn:hover { color: #4fc3f7; border-color: #4fc3f7; }

    .tab-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
    .tab-pane    { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

    /* ── Fullscreen overlay ─────────────────────────────────────────────── */
    .fullscreen-overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: #070c18;
      display: flex; flex-direction: column;
    }
    .fullscreen-header {
      display: flex; align-items: center; gap: 12px;
      padding: 8px 16px;
      background: linear-gradient(90deg, #0d1b3e, #091225);
      border-bottom: 1px solid #1e3a6e; flex-shrink: 0;
    }
    .fullscreen-title { font-size: 12px; color: #4fc3f7; letter-spacing: 2px; }
    .fullscreen-close {
      margin-left: auto;
      background: #091225; color: #ef5350;
      border: 1px solid #4a1010; border-radius: 3px;
      padding: 4px 12px; cursor: pointer;
      font-family: 'Courier New', monospace; font-size: 11px;
    }
    .fullscreen-close:hover { background: #1a0808; }
    .fullscreen-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

    /* Also open in new tab button */
    .new-tab-btn {
      background: #091225; color: #5a7fa0;
      border: 1px solid #1e3a6e; border-radius: 3px;
      padding: 4px 10px; cursor: pointer;
      font-family: 'Courier New', monospace; font-size: 11px;
    }
    .new-tab-btn:hover { color: #4fc3f7; border-color: #4fc3f7; }
  `]
})
export class NetworkFlowsComponent {

  activeTab: ActiveTab = 'hop-tree';
  dataset: Dataset     = 'MEADE';
  isFullscreen         = false;

  setTab(tab: ActiveTab): void  { this.activeTab = tab; this.isFullscreen = false; }
  setDataset(ds: Dataset): void { this.dataset = ds; }

  openFullscreen(): void  { this.isFullscreen = true; }
  closeFullscreen(): void { this.isFullscreen = false; }

  openInNewTab(): void {
    // Opens the Python-generated standalone HTML (works perfectly, no Angular dependencies)
    if (this.activeTab === 'hop-tree') {
      window.open(
        `/api/network-flows/hop-tree?hub=UURWMEA110&dataset=${this.dataset}&direction=inbound`,
        '_blank'
      );
    } else {
      window.open(
        `/api/network-flows/trail-map?dataset=${this.dataset}&direction=outbound`,
        '_blank'
      );
    }
  }
}
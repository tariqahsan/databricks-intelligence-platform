// flow-kpis.component.ts
import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NetworkFlowService } from '../../services/network-flow.service';
import { NetworkFlowKpis } from '../../models/network-flow.models';

@Component({
  selector: 'app-flow-kpis',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './flow-kpis.component.html',
  styles: [`
    .kpis-bar {
      display: flex;
      gap: 12px;
      padding: 12px 16px;
      background: linear-gradient(90deg, #0d1b3e, #091225);
      border-bottom: 1px solid #1e3a6e;
      flex-wrap: wrap;
      align-items: center;
    }
    .kpi-card {
      background: #0d1b2e;
      border: 1px solid #1e3a6e;
      border-radius: 4px;
      padding: 8px 14px;
      text-align: center;
      min-width: 90px;
    }
    .kpi-card.healthy  { border-color: #2e7d32; }
    .kpi-card.degraded { border-color: #f57c00; }
    .kpi-card.critical { border-color: #c62828; }
    .kpi-val {
      font-size: 20px;
      font-weight: 700;
      color: #4fc3f7;
      font-family: 'Courier New', monospace;
      line-height: 1;
    }
    .kpi-val.healthy  { color: #66bb6a; }
    .kpi-val.degraded { color: #ffb74d; }
    .kpi-val.critical { color: #ef5350; }
    .kpi-lbl {
      font-size: 9px;
      color: #5a7fa0;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      margin-top: 3px;
    }
    .divider {
      width: 1px;
      height: 36px;
      background: #1e3a6e;
      flex-shrink: 0;
    }
    .loading-bar {
      padding: 16px;
      color: #5a7fa0;
      font-size: 12px;
      font-family: monospace;
    }
  `]
})
export class FlowKpisComponent implements OnInit {

  private readonly svc = inject(NetworkFlowService);

  kpis: NetworkFlowKpis | null = null;
  loading = true;

  ngOnInit(): void {
    this.svc.getKpis().subscribe({
      next:  kpis => { this.kpis = kpis; this.loading = false; },
      error: ()   => { this.loading = false; }
    });
  }

  latencyClass(ms: number): string {
    if (ms > 50) return 'critical';
    if (ms > 10) return 'degraded';
    return '';
  }
}

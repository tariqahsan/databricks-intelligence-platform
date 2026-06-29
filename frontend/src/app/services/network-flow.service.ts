// network-flow.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, shareReplay } from 'rxjs';
import {
  ApiResponse, NetworkFlowKpis, NetworkHubStat,
  NetworkLinkLatency, NetworkPathStat, NetworkFlowSummaryRow,
  RouterCoordinates, Dataset
} from '../models/network-flow.models';

@Injectable({ providedIn: 'root' })
export class NetworkFlowService {

  private readonly http    = inject(HttpClient);
  private readonly baseUrl = '/api/network-flows';

  // ── Gold table queries ─────────────────────────────────────────────────

  getKpis(): Observable<NetworkFlowKpis> {
    return this.http
      .get<ApiResponse<NetworkFlowKpis>>(`${this.baseUrl}/kpis`)
      .pipe(map(r => r.data));
  }

  getHubStats(dataset: Dataset = 'MEADE'): Observable<NetworkHubStat[]> {
    return this.http
      .get<ApiResponse<NetworkHubStat[]>>(`${this.baseUrl}/hub-stats`, {
        params: { dataset }
      })
      .pipe(map(r => r.data));
  }

  getLinkLatency(dataset: Dataset = 'MEADE'): Observable<NetworkLinkLatency[]> {
    return this.http
      .get<ApiResponse<NetworkLinkLatency[]>>(`${this.baseUrl}/link-latency`, {
        params: { dataset }
      })
      .pipe(map(r => r.data));
  }

  getPathDistribution(dataset: Dataset = 'MEADE'): Observable<NetworkPathStat[]> {
    return this.http
      .get<ApiResponse<NetworkPathStat[]>>(`${this.baseUrl}/paths`, {
        params: { dataset }
      })
      .pipe(map(r => r.data));
  }

  getAvailableHubs(dataset: Dataset = 'MEADE'): Observable<string[]> {
    return this.http
      .get<ApiResponse<string[]>>(`${this.baseUrl}/hubs`, {
        params: { dataset }
      })
      .pipe(map(r => r.data));
  }

  /**
   * Returns source-to-destination flow pairs from gold.network_flow_summary.
   * MEADE: DK_* customer sites flowing TO UURWMEA* Fort Meade hub.
   * DAI:   DAI origin sites.
   * ALL:   all DK_* source nodes.
   * Used by trail map (draw routes) and hop tree (add customer site leaves).
   */
  getFlowSummary(dataset: Dataset = 'MEADE'): Observable<NetworkFlowSummaryRow[]> {
    return this.http
      .get<ApiResponse<NetworkFlowSummaryRow[]>>(`${this.baseUrl}/flow-summary`, {
        params: { dataset }
      })
      .pipe(map(r => r.data));
  }

  // ── Coordinate asset ───────────────────────────────────────────────────
  // Loads router-coordinates.json from Angular assets.
  // Generate once by running: python extract_coordinates.py
  // Cached with shareReplay(1) so the JSON is only fetched once per session.

  private coords$?: Observable<RouterCoordinates>;

  getRouterCoordinates(): Observable<RouterCoordinates> {
    if (!this.coords$) {
      this.coords$ = this.http
        .get<RouterCoordinates>('assets/data/router-coordinates.json')
        .pipe(shareReplay(1));
    }
    return this.coords$;
  }
}
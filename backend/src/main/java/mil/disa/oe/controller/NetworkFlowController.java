package mil.disa.oe.controller;

import mil.disa.oe.dto.*;
import mil.disa.oe.service.NetworkFlowService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

// ─────────────────────────────────────────────────────────────────────────────
// NETWORK FLOWS  — DAI + DISA Meade Netflow CSV data
// Sources: All_Complete_Flows_DAI.csv + All_Complete_Flows_DISA_Meade.csv
// Gold tables:
//   gold.network_flow_summary      → /api/network-flows/kpis
//   gold.network_hub_stats         → /api/network-flows/hub-stats
//   gold.network_link_latency      → /api/network-flows/link-latency
//   gold.network_path_distribution → /api/network-flows/paths
// Visualizations: D3.js Hop Tree + Leaflet Ant-Trail Map (iframe embed)
// ─────────────────────────────────────────────────────────────────────────────
@RestController
@RequestMapping("/api/network-flows")
public class NetworkFlowController {

    private final NetworkFlowService service;

    NetworkFlowController(NetworkFlowService service) {
        this.service = service;
    }

    /**
     * GET /api/network-flows/kpis
     * Aggregate KPIs from gold.network_flow_summary.
     */
    @GetMapping("/kpis")
    public ResponseEntity<ApiResponse<NetworkFlowKpis>> getKpis() {
        return ResponseEntity.ok(ApiResponse.ok(service.getKpis()));
    }

    /**
     * GET /api/network-flows/hub-stats?dataset=MEADE
     * Hub-level statistics from gold.network_hub_stats.
     * Feeds hop tree header badges in Angular.
     *
     * @param dataset MEADE (default) or DAI
     */
    @GetMapping("/hub-stats")
    public ResponseEntity<ApiResponse<List<NetworkHubStat>>> getHubStats(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getHubStats(dataset)));
    }

    /**
     * GET /api/network-flows/link-latency?dataset=MEADE
     * Per-circuit latency from gold.network_link_latency.
     * Feeds hop tree edge colours in Angular.
     *
     * @param dataset MEADE (default) or DAI
     */
    @GetMapping("/link-latency")
    public ResponseEntity<ApiResponse<List<NetworkLinkLatency>>> getLinkLatency(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getLinkLatency(dataset)));
    }

    /**
     * GET /api/network-flows/paths?dataset=MEADE
     * Hop-count distribution from gold.network_path_distribution.
     * Feeds trail map node panel in Angular.
     *
     * @param dataset MEADE (default) or DAI
     */
    @GetMapping("/paths")
    public ResponseEntity<ApiResponse<List<NetworkPathStat>>> getPaths(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getPathDistribution(dataset)));
    }

    /**
     * GET /api/network-flows/hubs?dataset=MEADE
     * Available hub names for the Angular hub-selector dropdown.
     *
     * @param dataset MEADE (default) or DAI
     */
    @GetMapping("/hubs")
    public ResponseEntity<ApiResponse<List<String>>> getHubs(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getAvailableHubs(dataset)));
    }

    /**
     * GET /api/network-flows/hop-tree?hub=UURWMEA110&dataset=MEADE&direction=inbound
     * Logical Hop Tree — D3.js HTML generated via generate_hop_tree.py.
     * Angular embeds the response in <iframe [srcdoc]="hopTreeHtml">.
     *
     * @param hub       hub node name (e.g. UURWMEA110 or DK_SAN_JOSE_CA)
     * @param dataset   MEADE (default) or DAI
     * @param direction inbound (many-to-one, default) or outbound (one-to-many)
     */
    @GetMapping(value = "/hop-tree", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> getHopTree(
            @RequestParam(defaultValue = "UURWMEA110") String hub,
            @RequestParam(defaultValue = "MEADE")      String dataset,
            @RequestParam(defaultValue = "inbound")    String direction) {
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_HTML)
                .body(service.generateHopTreeHtml(hub, dataset, direction));
    }

    /**
     * GET /api/network-flows/trail-map?dataset=MEADE&direction=outbound
     * Ant-Trail Route Map — Leaflet HTML generated via generate_trail_map.py.
     * Angular embeds the response in <iframe [srcdoc]="trailMapHtml">.
     *
     * @param dataset   MEADE (default) or DAI
     * @param direction outbound (default), inbound, or both
     */
    @GetMapping(value = "/trail-map", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> getTrailMap(
            @RequestParam(defaultValue = "MEADE")    String dataset,
            @RequestParam(defaultValue = "outbound") String direction) {
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_HTML)
                .body(service.generateTrailMapHtml(dataset, direction));
    }
}

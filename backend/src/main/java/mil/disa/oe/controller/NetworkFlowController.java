package mil.disa.oe.controller;

import mil.disa.oe.dto.*;
import mil.disa.oe.service.NetworkFlowService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * NetworkFlowController
 * =====================
 * REST API for Netflow CSV pipeline data (DAI + DISA Meade sources).
 *
 * All endpoints are under /api/network-flows and serve data from the
 * four Gold Delta tables written by the PySpark Medallion pipeline:
 *
 *   GET /kpis           - aggregate statistics from network_flow_summary
 *   GET /hub-stats      - per-node stats from network_hub_stats
 *   GET /link-latency   - per-circuit stats from network_link_latency
 *   GET /paths          - hop distribution from network_path_distribution
 *   GET /hubs           - list of available hub node names (for Angular dropdown)
 *   GET /flow-summary   - source->dest pairs from network_flow_summary
 *                         (DK_* customer sites to UURWMEA* hubs)
 *   GET /hop-tree       - D3.js HTML via Python script (legacy)
 *   GET /trail-map      - Leaflet HTML via Python script (legacy)
 *
 * dataset parameter:
 *   MEADE (default) - DISA Meade CSV: UURWMEA* core hubs, UJEW/UJPW routers
 *   DAI             - DAI CSV: Pentagon-area flows, UJEWPNT/UJPWPNT nodes
 *   ALL             - combined dataset, no filter
 */
@RestController
@RequestMapping("/api/network-flows")
public class NetworkFlowController {

    private final NetworkFlowService service;

    public NetworkFlowController(NetworkFlowService service) {
        this.service = service;
    }

    // ── 1. Aggregate KPIs ─────────────────────────────────────────────────────

    /**
     * GET /api/network-flows/kpis
     * Aggregate statistics from gold.network_flow_summary.
     */
    @GetMapping("/kpis")
    public ResponseEntity<ApiResponse<NetworkFlowKpis>> getKpis() {
        return ResponseEntity.ok(ApiResponse.ok(service.getKpis()));
    }

    // ── 2. Hub Statistics ─────────────────────────────────────────────────────

    /**
     * GET /api/network-flows/hub-stats?dataset=MEADE
     * Per-node statistics from gold.network_hub_stats.
     */
    @GetMapping("/hub-stats")
    public ResponseEntity<ApiResponse<List<NetworkHubStat>>> getHubStats(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getHubStats(dataset)));
    }

    // ── 3. Available Hubs ─────────────────────────────────────────────────────

    /**
     * GET /api/network-flows/hubs?dataset=MEADE
     * Returns list of CORE_HUB node names for the Angular hub selector dropdown.
     */
    @GetMapping("/hubs")
    public ResponseEntity<ApiResponse<List<String>>> getAvailableHubs(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getAvailableHubs(dataset)));
    }

    // ── 4. Link Latency ───────────────────────────────────────────────────────

    /**
     * GET /api/network-flows/link-latency?dataset=MEADE
     * Per-circuit latency measurements from gold.network_link_latency.
     * Used by Angular hop tree to build the router infrastructure graph.
     */
    @GetMapping("/link-latency")
    public ResponseEntity<ApiResponse<List<NetworkLinkLatency>>> getLinkLatency(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getLinkLatency(dataset)));
    }

    // ── 5. Path Distribution ──────────────────────────────────────────────────

    /**
     * GET /api/network-flows/paths?dataset=MEADE
     * Hop-count distribution from gold.network_path_distribution.
     */
    @GetMapping("/paths")
    public ResponseEntity<ApiResponse<List<NetworkPathStat>>> getPathDistribution(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getPathDistribution(dataset)));
    }

    // ── 6. Flow Summary (customer site pairs) ────────────────────────────────

    /**
     * GET /api/network-flows/flow-summary?dataset=MEADE
     *
     * Returns source-to-destination flow pairs from gold.network_flow_summary
     * where source_node is a customer site (DK_*).
     *
     * dataset=MEADE (default): dest_node LIKE 'UURWMEA%'  - Fort Meade flows
     * dataset=DAI:             DAI origin site flows
     * dataset=ALL:             all DK_* source pairs
     *
     * Used by:
     *   - Angular trail map  : draws ant-path lines from hub to customer sites
     *   - Angular hop tree   : attaches DK_* customer nodes as tree leaves
     */
    @GetMapping("/flow-summary")
    public ResponseEntity<ApiResponse<List<NetworkFlowSummaryRow>>> getFlowSummary(
            @RequestParam(defaultValue = "MEADE") String dataset) {
        return ResponseEntity.ok(ApiResponse.ok(service.getFlowSummary(dataset)));
    }

    // ── 7. Hop Tree HTML (legacy Python ProcessBuilder) ───────────────────────

    /**
     * GET /api/network-flows/hop-tree?hub=UURWMEA110&dataset=MEADE&direction=inbound
     * Generates standalone D3.js hop tree HTML via generate_hop_tree.py.
     * Angular now renders the hop tree natively -- kept for direct file download.
     */
    @GetMapping(value = "/hop-tree", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> getHopTree(
            @RequestParam(defaultValue = "UURWMEA110") String hub,
            @RequestParam(defaultValue = "MEADE")      String dataset,
            @RequestParam(defaultValue = "inbound")    String direction) {
        String html = service.generateHopTreeHtml(hub, dataset, direction);
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_HTML)
                .body(html);
    }

    // ── 8. Trail Map HTML (legacy Python ProcessBuilder) ──────────────────────

    /**
     * GET /api/network-flows/trail-map?dataset=MEADE&direction=outbound
     * Generates standalone Leaflet trail map HTML via generate_trail_map.py.
     * Angular now renders the trail map natively -- kept for direct file download.
     */
    @GetMapping(value = "/trail-map", produces = MediaType.TEXT_HTML_VALUE)
    public ResponseEntity<String> getTrailMap(
            @RequestParam(defaultValue = "MEADE")   String dataset,
            @RequestParam(defaultValue = "outbound") String direction) {
        String html = service.generateTrailMapHtml(dataset, direction);
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_HTML)
                .body(html);
    }
}
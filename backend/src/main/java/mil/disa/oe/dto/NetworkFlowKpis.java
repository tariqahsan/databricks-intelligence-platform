package mil.disa.oe.dto;

import java.math.BigDecimal;

/**
 * NetworkFlowKpis
 * ---------------
 * Aggregated from gold.network_flow_summary (one row per source-to-dest pair).
 * Returned by GET /api/network-flows/kpis
 *
 * @param totalPairs      distinct source-to-destination pairs in the table
 * @param totalFlows      sum of flow_count across all pairs
 * @param avgLatencyMs    average of avg_latency_ms across all pairs
 * @param p95LatencyMs    average of p95_latency_ms across all pairs
 * @param minLatencyMs    global minimum latency observed
 * @param maxLatencyMs    global maximum latency observed
 * @param avgHopCount     average hop count across all pairs
 * @param maxHopCount     maximum hop count observed
 * @param healthyPairs    count of pairs with health_status = HEALTHY
 * @param degradedPairs   count of pairs with health_status = DEGRADED
 * @param criticalPairs   count of pairs with health_status = CRITICAL
 */
public record NetworkFlowKpis(
        long       totalPairs,
        long       totalFlows,
        BigDecimal avgLatencyMs,
        BigDecimal p95LatencyMs,
        BigDecimal minLatencyMs,
        BigDecimal maxLatencyMs,
        BigDecimal avgHopCount,
        int        maxHopCount,
        long       healthyPairs,
        long       degradedPairs,
        long       criticalPairs
) {}
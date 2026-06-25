package mil.disa.oe.dto;

import java.math.BigDecimal;

/**
 * NetworkLinkLatency
 * ------------------
 * One row from gold.network_link_latency - latency stats for a single
 * CCSD circuit (directed link between two adjacent routers).
 * Returned by GET /api/network-flows/link-latency
 *
 * Only links with measured latency are included. First/last-mile customer
 * links annotated "N/A" in the Flow_Path string are excluded during the
 * Silver transform (link_ms IS NOT NULL filter in aggregate_all.py).
 *
 * Link health thresholds (set during Gold aggregation):
 *   HEALTHY  - avg_latency_ms &lt;= 10 ms
 *   DEGRADED - avg_latency_ms 10-50 ms
 *   CRITICAL - avg_latency_ms &gt; 50 ms
 *
 * @param circuitId        CCSD circuit identifier (e.g. "2PH0", "BN94", "BDC7")
 * @param fromNode         upstream router name
 * @param toNode           downstream router name
 * @param measurementCount number of flows observed on this circuit
 * @param avgLatencyMs     mean measured link latency in milliseconds
 * @param minLatencyMs     minimum measured latency
 * @param maxLatencyMs     maximum measured latency
 * @param p95LatencyMs     95th percentile latency
 * @param linkHealth       HEALTHY / DEGRADED / CRITICAL
 */
public record NetworkLinkLatency(
        String     circuitId,
        String     fromNode,
        String     toNode,
        long       measurementCount,
        BigDecimal avgLatencyMs,
        BigDecimal minLatencyMs,
        BigDecimal maxLatencyMs,
        BigDecimal p95LatencyMs,
        String     linkHealth
) {}
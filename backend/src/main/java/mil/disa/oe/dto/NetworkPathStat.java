package mil.disa.oe.dto;

import java.math.BigDecimal;

/**
 * NetworkPathStat
 * ---------------
 * One row from gold.network_path_distribution - one bucket per distinct
 * hop count across all flows in the merged dataset.
 * Returned by GET /api/network-flows/paths
 *
 * Complexity labels (set during Gold aggregation):
 *   LOW       - 1-3  hops
 *   MEDIUM    - 4-6  hops
 *   HIGH      - 7-10 hops
 *   VERY_HIGH - 11+  hops
 *
 * @param hopCount         number of hops (routers traversed minus one)
 * @param flowCount        number of flows with exactly this hop count
 * @param avgLatencyMs     average total end-to-end latency for this bucket
 * @param minLatencyMs     minimum total latency in this bucket
 * @param maxLatencyMs     maximum total latency in this bucket
 * @param pctOfTotal       percentage of all flows in this hop-count bucket
 * @param complexityLabel  LOW / MEDIUM / HIGH / VERY_HIGH
 */
public record NetworkPathStat(
        int        hopCount,
        long       flowCount,
        BigDecimal avgLatencyMs,
        BigDecimal minLatencyMs,
        BigDecimal maxLatencyMs,
        BigDecimal pctOfTotal,
        String     complexityLabel
) {}
package mil.disa.oe.dto;

import java.math.BigDecimal;

/**
 * NetworkFlowSummaryRow
 * ---------------------
 * One row from gold.network_flow_summary.
 * Returned by GET /api/network-flows/flow-summary
 *
 * Used by Angular trail map and hop tree to get actual
 * customer site (DK_*) to hub (UURWMEA*) flow pairs
 * with measured end-to-end latency.
 *
 * @param sourceNode   customer site or origin node (e.g. DK_PENTAGON_DC)
 * @param destNode     hub or destination node (e.g. UURWMEA110)
 * @param flowCount    number of flows observed for this pair
 * @param avgLatencyMs average end-to-end latency in milliseconds
 * @param healthStatus HEALTHY / DEGRADED / CRITICAL
 */
public record NetworkFlowSummaryRow(
        String     sourceNode,
        String     destNode,
        long       flowCount,
        BigDecimal avgLatencyMs,
        String     healthStatus
) {}

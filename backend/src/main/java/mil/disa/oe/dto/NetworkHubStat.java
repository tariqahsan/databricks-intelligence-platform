package mil.disa.oe.dto;

import java.math.BigDecimal;

/**
 * NetworkHubStat
 * --------------
 * One row from gold.network_hub_stats.
 * Returned by GET /api/network-flows/hub-stats
 *
 * Hub types (classified during Gold aggregation by node name prefix):
 *   CORE_HUB      - UURWMEA*         Fort Meade core routers (valid hop-tree roots)
 *   MESH_NODE     - UJPW*            UJP mesh fabric nodes
 *   EDGE_NODE     - UJEW* and UJEE*  UJE edge and access routers
 *   CUSTOMER_SITE - DK_*             customer or destination sites
 *   TRANSIT       - all others       intermediate or unnamed routers
 *
 * @param hubNode            router or site name (e.g. UURWMEA110, DK_PATCHBK_DE)
 * @param hubType            classification label (see above)
 * @param flowsThrough       number of flows that traverse this node
 * @param avgPathLatencyMs   average end-to-end latency of flows passing through
 * @param minPathLatencyMs   minimum end-to-end latency
 * @param maxPathLatencyMs   maximum end-to-end latency
 * @param avgHopCount        average hop count of flows through this node
 */
public record NetworkHubStat(
        String     hubNode,
        String     hubType,
        long       flowsThrough,
        BigDecimal avgPathLatencyMs,
        BigDecimal minPathLatencyMs,
        BigDecimal maxPathLatencyMs,
        BigDecimal avgHopCount
) {}
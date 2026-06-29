package mil.disa.oe.repository;

import mil.disa.oe.config.TableNames;
import mil.disa.oe.dto.*;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.retry.annotation.Backoff;
import org.springframework.retry.annotation.Retryable;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Collections;
import java.util.List;

/**
 * NetworkFlowRepository
 * =====================
 * Queries the four Netflow Gold Delta tables registered in the Hive metastore,
 * plus network_flow_summary for customer-site to hub flow pairs.
 *
 * Gold table schemas (written by aggregate_all.py):
 *
 *   gold.network_flow_summary
 *     source_node, dest_node, flow_count, avg_latency_ms, min_latency_ms,
 *     max_latency_ms, p95_latency_ms, avg_hop_count, max_hop_count,
 *     health_status, snapshot_date, last_updated
 *
 *   gold.network_hub_stats
 *     hub_node, hub_type, flows_through, avg_path_latency_ms,
 *     min_path_latency_ms, max_path_latency_ms, avg_hop_count,
 *     snapshot_date, last_updated
 *
 *   gold.network_link_latency
 *     circuit_id, from_node, to_node, measurement_count, avg_latency_ms,
 *     min_latency_ms, max_latency_ms, p95_latency_ms, link_health,
 *     snapshot_date, last_updated
 *
 *   gold.network_path_distribution
 *     hop_count, flow_count, avg_latency_ms, min_latency_ms, max_latency_ms,
 *     pct_of_total, complexity_label, snapshot_date, last_updated
 */
@Repository
public class NetworkFlowRepository {

    private final NamedParameterJdbcTemplate jdbc;
    private final TableNames                 tables;

    public NetworkFlowRepository(NamedParameterJdbcTemplate jdbc, TableNames tables) {
        this.jdbc   = jdbc;
        this.tables = tables;
    }

    // ── Hive/Databricks JDBC compat helpers ──────────────────────────────────

    private static BigDecimal bd(ResultSet rs, String col) throws SQLException {
        double v = rs.getDouble(col);
        return rs.wasNull() ? null : BigDecimal.valueOf(v);
    }

    private static BigDecimal bd(Object val) {
        if (val == null) return null;
        if (val instanceof BigDecimal b) return b;
        return BigDecimal.valueOf(((Number) val).doubleValue());
    }

    private static long safeLong(Object val) {
        return val == null ? 0L : ((Number) val).longValue();
    }

    // ── 1. KPIs -- gold.network_flow_summary ─────────────────────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public NetworkFlowKpis getKpis() {
        String sql = """
                SELECT
                    COUNT(*)                                          AS total_pairs,
                    COALESCE(SUM(flow_count), 0)                     AS total_flows,
                    ROUND(AVG(avg_latency_ms),  3)                   AS avg_latency_ms,
                    ROUND(AVG(p95_latency_ms),  3)                   AS p95_latency_ms,
                    ROUND(MIN(min_latency_ms),  3)                   AS min_latency_ms,
                    ROUND(MAX(max_latency_ms),  3)                   AS max_latency_ms,
                    ROUND(AVG(avg_hop_count),   1)                   AS avg_hop_count,
                    MAX(max_hop_count)                               AS max_hop_count,
                    SUM(CASE WHEN health_status = 'HEALTHY'  THEN 1 ELSE 0 END) AS healthy_pairs,
                    SUM(CASE WHEN health_status = 'DEGRADED' THEN 1 ELSE 0 END) AS degraded_pairs,
                    SUM(CASE WHEN health_status = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_pairs
                FROM %s
                """.formatted(tables.networkFlowSummary());

        var row = jdbc.queryForMap(sql, Collections.emptyMap());
        return new NetworkFlowKpis(
                safeLong(row.get("total_pairs")),
                safeLong(row.get("total_flows")),
                bd(row.get("avg_latency_ms")),
                bd(row.get("p95_latency_ms")),
                bd(row.get("min_latency_ms")),
                bd(row.get("max_latency_ms")),
                bd(row.get("avg_hop_count")),
                row.get("max_hop_count") == null ? 0 : ((Number) row.get("max_hop_count")).intValue(),
                safeLong(row.get("healthy_pairs")),
                safeLong(row.get("degraded_pairs")),
                safeLong(row.get("critical_pairs"))
        );
    }

    // ── 2. Hub Stats -- gold.network_hub_stats ───────────────────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<NetworkHubStat> getHubStats(String dataset) {
        String datasetClause = buildHubDatasetClause(dataset);
        String sql = """
                SELECT
                    hub_node,
                    hub_type,
                    flows_through,
                    avg_path_latency_ms,
                    min_path_latency_ms,
                    max_path_latency_ms,
                    avg_hop_count
                FROM %s
                WHERE 1=1 %s
                ORDER BY flows_through DESC
                LIMIT 500
                """.formatted(tables.networkHubStats(), datasetClause);

        return jdbc.query(sql, Collections.emptyMap(),
                (rs, i) -> new NetworkHubStat(
                        rs.getString("hub_node"),
                        rs.getString("hub_type"),
                        rs.getLong("flows_through"),
                        bd(rs, "avg_path_latency_ms"),
                        bd(rs, "min_path_latency_ms"),
                        bd(rs, "max_path_latency_ms"),
                        bd(rs, "avg_hop_count")
                ));
    }

    // ── 3. Available Hubs -- for Angular dropdown ─────────────────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<String> getAvailableHubs(String dataset) {
        String datasetClause = buildHubDatasetClause(dataset);
        String sql = """
                SELECT DISTINCT hub_node
                FROM %s
                WHERE hub_type = 'CORE_HUB' %s
                ORDER BY hub_node
                """.formatted(tables.networkHubStats(), datasetClause);

        return jdbc.queryForList(sql, Collections.emptyMap(), String.class);
    }

    // ── 4. Link Latency -- gold.network_link_latency ─────────────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<NetworkLinkLatency> getLinkLatency(String dataset) {
        String datasetClause = buildLinkDatasetClause(dataset);
        String sql = """
                SELECT
                    circuit_id,
                    from_node,
                    to_node,
                    measurement_count,
                    avg_latency_ms,
                    min_latency_ms,
                    max_latency_ms,
                    p95_latency_ms,
                    link_health
                FROM %s
                WHERE 1=1 %s
                ORDER BY avg_latency_ms DESC
                LIMIT 500
                """.formatted(tables.networkLinkLatency(), datasetClause);

        return jdbc.query(sql, Collections.emptyMap(),
                (rs, i) -> new NetworkLinkLatency(
                        rs.getString("circuit_id"),
                        rs.getString("from_node"),
                        rs.getString("to_node"),
                        rs.getLong("measurement_count"),
                        bd(rs, "avg_latency_ms"),
                        bd(rs, "min_latency_ms"),
                        bd(rs, "max_latency_ms"),
                        bd(rs, "p95_latency_ms"),
                        rs.getString("link_health")
                ));
    }

    // ── 5. Path Distribution -- gold.network_path_distribution ───────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<NetworkPathStat> getPathDistribution(String dataset) {
        String sql = """
                SELECT
                    hop_count,
                    flow_count,
                    avg_latency_ms,
                    min_latency_ms,
                    max_latency_ms,
                    pct_of_total,
                    complexity_label
                FROM %s
                ORDER BY hop_count ASC
                """.formatted(tables.networkPathDistribution());

        return jdbc.query(sql, Collections.emptyMap(),
                (rs, i) -> new NetworkPathStat(
                        rs.getInt("hop_count"),
                        rs.getLong("flow_count"),
                        bd(rs, "avg_latency_ms"),
                        bd(rs, "min_latency_ms"),
                        bd(rs, "max_latency_ms"),
                        bd(rs, "pct_of_total"),
                        rs.getString("complexity_label")
                ));
    }

    // ── 6. Flow Summary -- source->dest pairs from gold.network_flow_summary ──
    // Returns actual customer site (DK_*) to hub (UURWMEA*) flow pairs.
    // Used by Angular trail map (draw ant-path routes) and hop tree
    // (add DK_* customer sites as leaf nodes).

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<NetworkFlowSummaryRow> getFlowSummary(String dataset) {
        // Customer sites use various D-prefixes: DK_, DD_, DA_, DC_, DF_, DE_, DR_, DX_, DO_
        // All start with 'D' followed by a letter and underscore. Exclude hub-to-hub
        // flows (UURWMEA->UURWMEA) and unknown nodes like OKCIAPREM1.
        String datasetClause = switch (dataset == null ? "ALL" : dataset.toUpperCase()) {
            // MEADE: all customer D* sites flowing TO Fort Meade core hub
            case "MEADE" -> " AND source_node LIKE 'D%' AND dest_node LIKE 'UURWMEA%' ";
            // DAI: flows where source is any customer D* site to non-MEADE hub
            case "DAI"   -> " AND source_node LIKE 'D%' AND dest_node NOT LIKE 'UURWMEA%' ";
            // ALL: any pair where source is a customer D* site to any UURWMEA hub
            default      -> " AND source_node LIKE 'D%' AND dest_node LIKE 'UURWMEA%' ";
        };

        String sql = """
                SELECT
                    source_node,
                    dest_node,
                    flow_count,
                    ROUND(avg_latency_ms, 3) AS avg_latency_ms,
                    health_status
                FROM %s
                WHERE 1=1 %s
                ORDER BY flow_count DESC
                LIMIT 1000
                """.formatted(tables.networkFlowSummary(), datasetClause);

        return jdbc.query(sql, Collections.emptyMap(),
                (rs, i) -> new NetworkFlowSummaryRow(
                        rs.getString("source_node"),
                        rs.getString("dest_node"),
                        rs.getLong("flow_count"),
                        bd(rs, "avg_latency_ms"),
                        rs.getString("health_status")
                ));
    }

    // ── Dataset filter helpers ────────────────────────────────────────────────

    private static String buildHubDatasetClause(String dataset) {
        return switch (dataset == null ? "ALL" : dataset.toUpperCase()) {
            case "MEADE" -> " AND (hub_node LIKE 'UURWMEA%' OR hub_node LIKE 'UJPW%' OR hub_node LIKE 'UJEW%' OR hub_node LIKE 'UJEE%') ";
            case "DAI"   -> " AND (hub_node LIKE 'DK_%' OR hub_node LIKE 'UJEWPNT%' OR hub_node LIKE 'UJPWPNT%') ";
            default      -> "";
        };
    }

    private static String buildLinkDatasetClause(String dataset) {
        return switch (dataset == null ? "ALL" : dataset.toUpperCase()) {
            case "MEADE" -> " AND (from_node LIKE 'UURWMEA%' OR from_node LIKE 'UJPW%' OR from_node LIKE 'UJEW%' OR to_node LIKE 'UURWMEA%') ";
            case "DAI"   -> " AND (from_node LIKE 'DK_%' OR from_node LIKE 'UJEWPNT%' OR to_node LIKE 'DK_%') ";
            default      -> "";
        };
    }
}
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
 * Queries the four Netflow Gold Delta tables registered in the Hive metastore.
 *
 * Sources: All_Complete_Flows_DAI.csv + All_Complete_Flows_DISA_Meade.csv
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
 *
 * Dataset filtering (hub_stats + link_latency):
 *   MEADE — UURWMEA* core hubs and upstream UJP/UJE router nodes
 *   DAI   — DK_PENTAGON and associated PNT edge routers
 *   null  — no filter; returns full merged dataset
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
    // Copied from NetworkPerformanceRepository — Hive returns numeric columns
    // as Object, not double, so we normalise through BigDecimal.

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

    // ── 1. KPIs — gold.network_flow_summary ──────────────────────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public NetworkFlowKpis getKpis() {
        // Aggregate across all source→dest pairs — no single summary row exists
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

    // ── 2. Hub Stats — gold.network_hub_stats ────────────────────────────────

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

    // ── 3. Available Hubs — for Angular dropdown ──────────────────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<String> getAvailableHubs(String dataset) {
        // Return only CORE_HUB nodes — these are the valid roots for the hop tree
        String datasetClause = buildHubDatasetClause(dataset);
        String sql = """
                SELECT DISTINCT hub_node
                FROM %s
                WHERE hub_type = 'CORE_HUB' %s
                ORDER BY hub_node
                """.formatted(tables.networkHubStats(), datasetClause);

        return jdbc.queryForList(sql, Collections.emptyMap(), String.class);
    }

    // ── 4. Link Latency — gold.network_link_latency ──────────────────────────

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

    // ── 5. Path Distribution — gold.network_path_distribution ────────────────

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<NetworkPathStat> getPathDistribution(String dataset) {
        // Path distribution is a global hop-count histogram — no dataset column.
        // The dataset param is accepted for API consistency but not applied here.
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

    // ── Dataset filter helpers ────────────────────────────────────────────────
    // The Gold tables contain all flows from both CSVs merged together.
    // We filter by node naming conventions established in the real data:
    //   MEADE nodes: UURWMEA* (core), UJPW* (mesh), UJEW*/UJEE* (edge)
    //   DAI nodes:   DK_PENTAGON* (source site), UJEWPNT*/UJPWPNT* (PNT routers)
    // These are inline SQL fragments — safe because they are hardcoded constants,
    // never interpolated from user input.

    private static String buildHubDatasetClause(String dataset) {
        if (dataset == null || dataset.isBlank()) return "";
        return switch (dataset.toUpperCase()) {
            case "MEADE" -> " AND (hub_node LIKE 'UURWMEA%' OR hub_node LIKE 'UJPW%' OR hub_node LIKE 'UJEW%' OR hub_node LIKE 'UJEE%') ";
            case "DAI"   -> " AND (hub_node LIKE 'DK_%' OR hub_node LIKE 'UJEWPNT%' OR hub_node LIKE 'UJPWPNT%') ";
            default      -> "";
        };
    }

    private static String buildLinkDatasetClause(String dataset) {
        if (dataset == null || dataset.isBlank()) return "";
        return switch (dataset.toUpperCase()) {
            case "MEADE" -> " AND (from_node LIKE 'UURWMEA%' OR from_node LIKE 'UJPW%' OR from_node LIKE 'UJEW%' OR to_node LIKE 'UURWMEA%') ";
            case "DAI"   -> " AND (from_node LIKE 'DK_%' OR from_node LIKE 'UJEWPNT%' OR to_node LIKE 'DK_%') ";
            default      -> "";
        };
    }
}
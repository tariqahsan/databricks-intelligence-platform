package mil.disa.oe.repository;

import mil.disa.oe.config.TableNames;
import mil.disa.oe.dto.*;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.retry.annotation.Backoff;
import org.springframework.retry.annotation.Retryable;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;

/** Source: DXNETOPS (Device CPU, Memory & Performance Metrics) */
@Repository
public class DeviceHealthRepository {

    private final NamedParameterJdbcTemplate jdbc;
    private final TableNames tables;

    public DeviceHealthRepository(NamedParameterJdbcTemplate jdbc, TableNames tables) {
        this.jdbc   = jdbc;
        this.tables = tables;
    }

    // ── Hive JDBC compatibility helpers ───────────────────────────────────
    //
    // 1. DOUBLE columns: Hive returns java.lang.Double, not BigDecimal.
    //    Fix: bd() reads via getDouble() and wraps in BigDecimal.valueOf().
    //
    // 2. NULL aggregates: SQL COUNT/SUM/AVG return NULL when 0 rows match.
    //    (e.g. WHERE snapshot_date = current_date() with stale mock data).
    //    Calling ((Number) null).intValue() throws NullPointerException.
    //    Fix: safeInt() and safeLong() return 0 for null values.
    //
    // 3. TIMESTAMP columns: Hive stores timestamps as strings internally.
    //    rs.getTimestamp() throws "Illegal conversion".
    //    Fix: ts() reads as String and parses to LocalDateTime.

    private static BigDecimal bd(ResultSet rs, String col) throws SQLException {
        double v = rs.getDouble(col);
        return rs.wasNull() ? null : BigDecimal.valueOf(v);
    }

    private static BigDecimal bd(Object val) {
        if (val == null) return null;
        if (val instanceof BigDecimal b) return b;
        return BigDecimal.valueOf(((Number) val).doubleValue());
    }

    private static int safeInt(Object val) {
        return val == null ? 0 : ((Number) val).intValue();
    }

    private static long safeLong(Object val) {
        return val == null ? 0L : ((Number) val).longValue();
    }

    private static LocalDateTime ts(ResultSet rs, String col) throws SQLException {
        String s = rs.getString(col);
        if (s == null || s.isBlank()) return null;
        try {
            return LocalDateTime.parse(s.replace(" ", "T")
                                        .replaceAll("\\.\\d+$", ""));
        } catch (Exception e) {
            return null;
        }
    }

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public DeviceHealthKpis getKpis() {
        String kpiSql = """
            SELECT
                COUNT(*)                                                       AS total_devices,
                COUNT(CASE WHEN compliance_state = 'COMPLIANT'     THEN 1 END) AS compliant,
                COUNT(CASE WHEN compliance_state = 'NON_COMPLIANT' THEN 1 END) AS non_compliant,
                COUNT(CASE WHEN compliance_state = 'UNKNOWN'       THEN 1 END) AS unknown,
                ROUND(AVG(health_score), 1)                                    AS avg_health,
                COUNT(CASE WHEN days_since_checkin > 7             THEN 1 END) AS not_checked_in,
                COUNT(CASE WHEN encryption_enabled = true          THEN 1 END) AS encrypted
            FROM %s
            WHERE snapshot_date = current_date()
            """.formatted(tables.deviceHealthSummary());

        String byTypeSql = """
            SELECT device_type, COUNT(*) AS total,
                   COUNT(CASE WHEN compliance_state = 'COMPLIANT'     THEN 1 END) AS compliant,
                   COUNT(CASE WHEN compliance_state = 'NON_COMPLIANT' THEN 1 END) AS non_compliant,
                   ROUND(COUNT(CASE WHEN compliance_state = 'COMPLIANT' THEN 1 END)
                         * 100.0 / NULLIF(COUNT(*),0), 1) AS compliance_rate
            FROM %s
            WHERE snapshot_date = current_date()
            GROUP BY device_type
            ORDER BY total DESC
            """.formatted(tables.deviceHealthSummary());

        String osSql = """
            SELECT os_name, os_version, COUNT(*) AS device_count,
                   is_os_supported AS is_supported, is_os_latest AS is_latest
            FROM %s
            WHERE snapshot_date = current_date()
            GROUP BY os_name, os_version, is_os_supported, is_os_latest
            ORDER BY device_count DESC
            LIMIT 20
            """.formatted(tables.deviceHealthSummary());

        var r = jdbc.queryForMap(kpiSql, Collections.emptyMap());

        List<ComplianceByType> byType = jdbc.query(byTypeSql,
            Collections.emptyMap(), (rs, i) -> new ComplianceByType(
                rs.getString("device_type"), rs.getInt("total"),
                rs.getInt("compliant"), rs.getInt("non_compliant"),
                bd(rs, "compliance_rate")));

        List<OsDistribution> os = jdbc.query(osSql,
            Collections.emptyMap(), (rs, i) -> new OsDistribution(
                rs.getString("os_name"), rs.getString("os_version"),
                rs.getInt("device_count"),
                rs.getBoolean("is_supported"), rs.getBoolean("is_latest")));

        int total     = safeInt(r.get("total_devices"));
        int compliant = safeInt(r.get("compliant"));
        BigDecimal rate = total > 0
            ? new BigDecimal(compliant * 100.0 / total).setScale(1, RoundingMode.HALF_UP)
            : BigDecimal.ZERO;

        return new DeviceHealthKpis(
            total, compliant,
            safeInt(r.get("non_compliant")),
            safeInt(r.get("unknown")),
            rate,
            bd(r.get("avg_health")),
            safeInt(r.get("not_checked_in")),
            safeInt(r.get("encrypted")),
            byType, os);
    }

    @Retryable(retryFor = Exception.class, maxAttempts = 3,
               backoff = @Backoff(delay = 2000, multiplier = 2.0))
    public List<DeviceHealthSummary> getAll(String complianceFilter, int page, int size) {
        String sql = """
            SELECT device_id, device_name, device_type, os_name, os_version,
                   compliance_state, health_score, enrollment_status,
                   last_check_in, assigned_user, location,
                   encryption_enabled, firewall_enabled, antivirus_enabled,
                   management_agent
            FROM %s
            WHERE snapshot_date = current_date()
              AND (:filter IS NULL OR compliance_state = :filter)
            ORDER BY health_score ASC
            LIMIT :size OFFSET :offset
            """.formatted(tables.deviceHealthSummary());

        return jdbc.query(sql,
            new MapSqlParameterSource()
                .addValue("filter", complianceFilter)
                .addValue("size",   size)
                .addValue("offset", page * size),
            (rs, i) -> new DeviceHealthSummary(
                rs.getString("device_id"), rs.getString("device_name"),
                rs.getString("device_type"), rs.getString("os_name"),
                rs.getString("os_version"), rs.getString("compliance_state"),
                bd(rs, "health_score"),
                rs.getString("enrollment_status"),
                ts(rs, "last_check_in"),
                rs.getString("assigned_user"), rs.getString("location"),
                rs.getBoolean("encryption_enabled"),
                rs.getBoolean("firewall_enabled"),
                rs.getBoolean("antivirus_enabled"),
                rs.getString("management_agent")));
    }
}
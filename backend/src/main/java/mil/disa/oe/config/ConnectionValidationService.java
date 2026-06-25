package mil.disa.oe.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Profile;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * ConnectionValidationService
 *
 * On startup (thrift profile only) this service does two things:
 *
 * 1. AUTO-REGISTERS Gold Delta tables in the Spark Thrift Server metastore.
 *
 *    WHY THIS IS NEEDED:
 *    The Spark Thrift Server uses an embedded Derby database as its Hive
 *    metastore. Derby is ephemeral -- it resets every time the Docker container
 *    restarts, forgetting all table registrations. Without registration,
 *    every SQL query fails with "TABLE_OR_VIEW_NOT_FOUND".
 *
 *    Previously this was handled by running a long docker exec beeline
 *    command manually after every container restart. This service automates
 *    that step: Spring Boot registers all Gold tables on startup via
 *    CREATE TABLE IF NOT EXISTS ... USING DELTA LOCATION 's3a://gold/...'.
 *    If the table is already registered, the statement is a no-op.
 *
 *    On AWS GovCloud (Databricks + Unity Catalog), tables are permanently
 *    registered and this step is skipped -- the @Profile("thrift") annotation
 *    ensures this bean is only active in the local dev environment.
 *
 * 2. VALIDATES all 12 Gold tables are accessible and logs row counts.
 *    This confirms end-to-end connectivity before serving any API traffic.
 *
 * Gold tables (12 total):
 *   Core 8 : app_health_summary, network_performance_summary,
 *             packet_loss_root_cause, device_health_summary,
 *             dns_metrics, top_issues_summary,
 *             version_sprawl_summary, data_source_ingestion_status
 *   Netflow : network_flow_summary, network_hub_stats,
 *             network_link_latency, network_path_distribution
 */
@Component
@Profile("thrift")
public class ConnectionValidationService {

    private static final Logger log =
            LoggerFactory.getLogger(ConnectionValidationService.class);

    private final JdbcTemplate jdbc;
    private final TableNames   tables;

    public ConnectionValidationService(JdbcTemplate jdbc, TableNames tables) {
        this.jdbc   = jdbc;
        this.tables = tables;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void validateOnStartup() {
        log.info("═══════════════════════════════════════════════");
        log.info("  OE Data Intelligence - Connection Validation");
        log.info("═══════════════════════════════════════════════");

        // Step 1: Verify connection
        try {
            String version = jdbc.queryForObject("SELECT version()", String.class);
            log.info("  OK  Connected: {}", version);
        } catch (Exception e) {
            log.error("  FAIL  Cannot connect: {}", e.getMessage());
            return;
        }

        // Step 2: Auto-register all Gold tables
        // CREATE TABLE IF NOT EXISTS is a no-op when already registered.
        // Safe to run on every startup.
        log.info("  Registering Gold tables in Hive metastore...");
        registerGoldTables();

        // Step 3: Validate all 12 Gold tables
        String[] goldTables = {
            // Core 8 tables
            tables.appHealthSummary(),
            tables.networkPerformanceSummary(),
            tables.packetLossRootCause(),
            tables.deviceHealthSummary(),
            tables.dnsMetrics(),
            tables.topIssuesSummary(),
            tables.versionSprawlSummary(),
            tables.dataSourceIngestionStatus(),
            // Netflow 4 tables (DAI + DISA Meade CSV pipeline)
            tables.networkFlowSummary(),
            tables.networkHubStats(),
            tables.networkLinkLatency(),
            tables.networkPathDistribution(),
        };

        int ok = 0;
        for (String t : goldTables) {
            try {
                Long n = jdbc.queryForObject("SELECT COUNT(*) FROM " + t, Long.class);
                log.info("  OK  {} ({} rows)", t, n);
                ok++;
            } catch (Exception e) {
                log.warn("  WARN  {} - {}", t, e.getMessage());
            }
        }

        log.info("───────────────────────────────────────────────");
        if (ok == goldTables.length)
            log.info("  OK  All {} Gold tables ready", ok);
        else
            log.warn("  WARN  {}/{} tables accessible - run ingestion pipeline",
                    ok, goldTables.length);
        log.info("═══════════════════════════════════════════════");
    }

    /**
     * Registers all 12 Gold Delta tables in the Spark Thrift Server Hive
     * metastore. Each statement maps a table name to its Delta Lake path
     * in MinIO (S3-compatible storage).
     *
     * On AWS GovCloud, Unity Catalog handles registration permanently --
     * this method is never called (bean is @Profile("thrift") only).
     */
    private void registerGoldTables() {
        runDDL("CREATE DATABASE IF NOT EXISTS gold");

        // ── Core 8 tables ────────────────────────────────────────────────────
        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.app_health_summary
                USING DELTA LOCATION 's3a://gold/app_health_summary'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.network_performance_summary
                USING DELTA LOCATION 's3a://gold/network_performance_summary'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.packet_loss_root_cause
                USING DELTA LOCATION 's3a://gold/packet_loss_root_cause'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.device_health_summary
                USING DELTA LOCATION 's3a://gold/device_health_summary'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.dns_metrics
                USING DELTA LOCATION 's3a://gold/dns_metrics'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.top_issues_summary
                USING DELTA LOCATION 's3a://gold/top_issues_summary'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.version_sprawl_summary
                USING DELTA LOCATION 's3a://gold/version_sprawl_summary'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.data_source_ingestion_status
                USING DELTA LOCATION 's3a://gold/data_source_ingestion_status'
                """);

        // ── Netflow 4 tables (DAI + DISA Meade CSV pipeline) ─────────────────
        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.network_flow_summary
                USING DELTA LOCATION 's3a://gold/network_flow_summary'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.network_hub_stats
                USING DELTA LOCATION 's3a://gold/network_hub_stats'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.network_link_latency
                USING DELTA LOCATION 's3a://gold/network_link_latency'
                """);

        runDDL("""
                CREATE TABLE IF NOT EXISTS gold.network_path_distribution
                USING DELTA LOCATION 's3a://gold/network_path_distribution'
                """);

        log.info("  OK  Gold table registration complete (12 tables)");
    }

    /**
     * Executes a DDL statement and logs any failure without crashing startup.
     * A failed registration shows up as a WARN in the validation step.
     */
    private void runDDL(String sql) {
        try {
            jdbc.execute(sql.strip());
        } catch (Exception e) {
            log.warn("  WARN  DDL failed: {}", e.getMessage());
        }
    }
}
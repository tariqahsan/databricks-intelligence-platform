package mil.disa.oe.service;

import mil.disa.oe.dto.*;
import mil.disa.oe.repository.NetworkFlowRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.stream.Collectors;

/**
 * NetworkFlowService
 * ==================
 * Two responsibilities:
 *
 * 1. Query Gold Delta tables via NetworkFlowRepository
 *      gold.network_flow_summary      - getKpis(), getFlowSummary()
 *      gold.network_hub_stats         - getHubStats()
 *      gold.network_link_latency      - getLinkLatency()
 *      gold.network_path_distribution - getPathDistribution()
 *
 * 2. Run generate_hop_tree.py / generate_trail_map.py via ProcessBuilder
 *    and return the generated HTML for Angular iframe embedding (legacy).
 *
 * Required config in application-thrift.yml:
 *
 *   oe:
 *     network-flows:
 *       python-cmd:  python3
 *       scripts-dir: /path/to/oe-ingestion-pipeline
 *       data-dir:    /path/to/oe-ingestion-pipeline/mock-logs/network_flows
 *       dai-csv:     All_Complete_Flows_DAI.csv
 *       meade-csv:   All_Complete_Flows_DISA_Meade.csv
 */
@Service
public class NetworkFlowService {

    private static final Logger log = LoggerFactory.getLogger(NetworkFlowService.class);

    private final NetworkFlowRepository repo;

    @Value("${oe.network-flows.python-cmd:python3}")
    private String pythonCmd;

    @Value("${oe.network-flows.scripts-dir:/home/jovyan/project}")
    private String scriptsDir;

    @Value("${oe.network-flows.data-dir:/home/jovyan/project/mock-logs/network_flows}")
    private String dataDir;

    @Value("${oe.network-flows.dai-csv:All_Complete_Flows_DAI.csv}")
    private String daiCsv;

    @Value("${oe.network-flows.meade-csv:All_Complete_Flows_DISA_Meade.csv}")
    private String meadeCsv;

    public NetworkFlowService(NetworkFlowRepository repo) {
        this.repo = repo;
    }

    // ── Gold table queries ────────────────────────────────────────────────────

    /** Aggregate KPIs from gold.network_flow_summary */
    public NetworkFlowKpis getKpis() {
        return repo.getKpis();
    }

    /** Per-hub statistics from gold.network_hub_stats */
    public List<NetworkHubStat> getHubStats(String dataset) {
        return repo.getHubStats(dataset);
    }

    /** Per-circuit latency from gold.network_link_latency */
    public List<NetworkLinkLatency> getLinkLatency(String dataset) {
        return repo.getLinkLatency(dataset);
    }

    /** Hop-count distribution from gold.network_path_distribution */
    public List<NetworkPathStat> getPathDistribution(String dataset) {
        return repo.getPathDistribution(dataset);
    }

    /** Available hub node names for the Angular dropdown */
    public List<String> getAvailableHubs(String dataset) {
        return repo.getAvailableHubs(dataset);
    }

    /**
     * Customer-site to hub flow pairs from gold.network_flow_summary.
     * MEADE: DK_* sources flowing to UURWMEA* destinations.
     * Used by Angular trail map (ant-path routes) and hop tree (customer leaves).
     */
    public List<NetworkFlowSummaryRow> getFlowSummary(String dataset) {
        return repo.getFlowSummary(dataset);
    }

    // ── Visualization HTML generation (legacy ProcessBuilder approach) ────────

    /**
     * Runs generate_hop_tree.py and returns standalone D3.js HTML.
     * Angular now renders the hop tree natively -- this endpoint is kept
     * for backward compatibility and direct file download.
     */
    public String generateHopTreeHtml(String hub, String dataset, String direction) {
        String csvPath = resolveCsvPath(dataset);
        Path   tmpOut  = Paths.get(
                System.getProperty("java.io.tmpdir"),
                "hop_tree_%s_%s.html".formatted(hub, direction));
        try {
            ProcessBuilder pb = new ProcessBuilder(
                    pythonCmd,
                    scriptsDir + "/generate_hop_tree.py",
                    "--flows",     csvPath,
                    "--hub",       hub,
                    "--out",       tmpOut.toString(),
                    "--direction", direction
            );
            pb.redirectErrorStream(true);
            pb.directory(new java.io.File(scriptsDir));

            Process proc     = pb.start();
            String  output   = new BufferedReader(
                    new InputStreamReader(proc.getInputStream()))
                    .lines().collect(Collectors.joining("\n"));
            int exitCode = proc.waitFor();

            if (exitCode != 0) {
                log.error("generate_hop_tree.py failed (exit {}): {}", exitCode, output);
                return errorHtml("Hop tree generation failed - see Spring Boot logs.",
                        "generate_hop_tree.py");
            }
            log.info("Hop tree generated hub={} direction={}", hub, direction);
            return Files.readString(tmpOut);

        } catch (Exception e) {
            log.error("Error running generate_hop_tree.py", e);
            return errorHtml(e.getMessage(), "generate_hop_tree.py");
        }
    }

    /**
     * Runs generate_trail_map.py and returns standalone Leaflet HTML.
     * Angular now renders the trail map natively -- this endpoint is kept
     * for backward compatibility and direct file download.
     */
    public String generateTrailMapHtml(String dataset, String direction) {
        String csvPath = resolveCsvPath(dataset);
        Path   tmpOut  = Paths.get(
                System.getProperty("java.io.tmpdir"),
                "trail_map_%s_%s.html".formatted(dataset, direction));
        try {
            ProcessBuilder pb = new ProcessBuilder(
                    pythonCmd,
                    scriptsDir + "/generate_trail_map.py",
                    "--flows",     csvPath,
                    "--direction", direction,
                    "--out",       tmpOut.toString()
            );
            pb.redirectErrorStream(true);
            pb.directory(new java.io.File(scriptsDir));

            Process proc     = pb.start();
            String  output   = new BufferedReader(
                    new InputStreamReader(proc.getInputStream()))
                    .lines().collect(Collectors.joining("\n"));
            int exitCode = proc.waitFor();

            if (exitCode != 0) {
                log.error("generate_trail_map.py failed (exit {}): {}", exitCode, output);
                return errorHtml("Trail map generation failed - see Spring Boot logs.",
                        "generate_trail_map.py");
            }
            log.info("Trail map generated dataset={} direction={}", dataset, direction);
            return Files.readString(tmpOut);

        } catch (Exception e) {
            log.error("Error running generate_trail_map.py", e);
            return errorHtml(e.getMessage(), "generate_trail_map.py");
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private String resolveCsvPath(String dataset) {
        String file = "DAI".equalsIgnoreCase(dataset) ? daiCsv : meadeCsv;
        return dataDir + "/" + file;
    }

    private String errorHtml(String message, String script) {
        return """
                <!DOCTYPE html><html>
                <body style="background:#0a0e1a;color:#ef5350;
                             font-family:monospace;padding:24px">
                  <h3 style="color:#ef5350">&#9888; Visualization Error</h3>
                  <pre style="color:#90a4ae">%s</pre>
                  <p style="color:#546e7a;font-size:12px">
                    Ensure <code style="color:#80cbc4">%s</code> is present in
                    <code style="color:#80cbc4">scripts-dir</code> and CSV files
                    exist in <code style="color:#80cbc4">data-dir</code>.<br/>
                    Check Spring Boot logs for the full stack trace.
                  </p>
                </body></html>
                """.formatted(message, script);
    }
}
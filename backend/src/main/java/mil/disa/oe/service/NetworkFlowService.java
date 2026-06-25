package mil.disa.oe.service;

import mil.disa.oe.dto.*;
import mil.disa.oe.repository.NetworkFlowRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.Cacheable;
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
 * 1. Query Gold Delta tables via NetworkFlowRepository for KPI data
 * 2. Run generate_hop_tree.py / generate_trail_map.py via ProcessBuilder
 *    and return the generated HTML for Angular iframe embedding.
 *
 * Configuration in application-thrift.yml (add the oe.network-flows block):
 *
 *   oe:
 *     network-flows:
 *       python-cmd:  python3
 *       scripts-dir: /home/jovyan
 *       data-dir:    /home/jovyan/mock-logs/network_flows
 *       dai-csv:     All_Complete_Flows_DAI.csv
 *       meade-csv:   All_Complete_Flows_DISA_Meade.csv
 */
@Service
public class NetworkFlowService {

    private static final Logger log = LoggerFactory.getLogger(NetworkFlowService.class);

    private final NetworkFlowRepository repo;

    @Value("${oe.network-flows.python-cmd:python3}")
    private String pythonCmd;

    @Value("${oe.network-flows.scripts-dir:/home/jovyan}")
    private String scriptsDir;

    @Value("${oe.network-flows.data-dir:/home/jovyan/mock-logs/network_flows}")
    private String dataDir;

    @Value("${oe.network-flows.dai-csv:All_Complete_Flows_DAI.csv}")
    private String daiCsv;

    @Value("${oe.network-flows.meade-csv:All_Complete_Flows_DISA_Meade.csv}")
    private String meadeCsv;

    public NetworkFlowService(NetworkFlowRepository repo) {
        this.repo = repo;
    }

    // ── Gold table queries ────────────────────────────────────────────────

    @Cacheable("networkFlowKpis")
    public NetworkFlowKpis getKpis() {
        return repo.getKpis();
    }

    @Cacheable("networkHubStats")
    public List<NetworkHubStat> getHubStats(String dataset) {
        return repo.getHubStats(dataset);
    }

    @Cacheable("networkLinkLatency")
    public List<NetworkLinkLatency> getLinkLatency(String dataset) {
        return repo.getLinkLatency(dataset);
    }

    @Cacheable("networkPathDistribution")
    public List<NetworkPathStat> getPathDistribution(String dataset) {
        return repo.getPathDistribution(dataset);
    }

    public List<String> getAvailableHubs(String dataset) {
        return repo.getAvailableHubs(dataset);
    }

    // ── Visualization HTML generation ─────────────────────────────────────

    /**
     * Runs generate_hop_tree.py → returns standalone D3.js HTML.
     * Angular embeds the result in <iframe [srcdoc]="hopTreeHtml">.
     *
     * @param hub       hub node name, e.g. "UURWMEA110" or "DK_SAN_JOSE_CA"
     * @param dataset   "MEADE" or "DAI"
     * @param direction "inbound" (many-to-one) or "outbound" (one-to-many)
     */
    public String generateHopTreeHtml(String hub, String dataset, String direction) {
        String csvPath = resolveCsvPath(dataset);
        Path   tmpOut  = Paths.get(System.getProperty("java.io.tmpdir"),
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
            Process      proc   = pb.start();
            String       output = new BufferedReader(
                new InputStreamReader(proc.getInputStream()))
                .lines().collect(Collectors.joining("\n"));
            int exitCode = proc.waitFor();

            if (exitCode != 0) {
                log.error("generate_hop_tree.py failed (exit {}): {}", exitCode, output);
                return errorHtml("Hop tree generation failed — see Spring Boot logs.");
            }
            return Files.readString(tmpOut);

        } catch (Exception e) {
            log.error("Error running generate_hop_tree.py", e);
            return errorHtml("Error: " + e.getMessage());
        }
    }

    /**
     * Runs generate_trail_map.py → returns standalone Leaflet HTML.
     * Angular embeds the result in <iframe [srcdoc]="trailMapHtml">.
     *
     * @param dataset   "MEADE" or "DAI"
     * @param direction "outbound", "inbound", or "both"
     */
    public String generateTrailMapHtml(String dataset, String direction) {
        String csvPath = resolveCsvPath(dataset);
        Path   tmpOut  = Paths.get(System.getProperty("java.io.tmpdir"),
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
            Process      proc   = pb.start();
            String       output = new BufferedReader(
                new InputStreamReader(proc.getInputStream()))
                .lines().collect(Collectors.joining("\n"));
            int exitCode = proc.waitFor();

            if (exitCode != 0) {
                log.error("generate_trail_map.py failed (exit {}): {}", exitCode, output);
                return errorHtml("Trail map generation failed — see Spring Boot logs.");
            }
            return Files.readString(tmpOut);

        } catch (Exception e) {
            log.error("Error running generate_trail_map.py", e);
            return errorHtml("Error: " + e.getMessage());
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    private String resolveCsvPath(String dataset) {
        String file = "DAI".equalsIgnoreCase(dataset) ? daiCsv : meadeCsv;
        return dataDir + "/" + file;
    }

    private String errorHtml(String message) {
        return """
            <!DOCTYPE html><html>
            <body style="background:#0a0e1a;color:#ef5350;
                         font-family:monospace;padding:24px">
              <h3 style="color:#ef5350">⚠ Visualization Error</h3>
              <pre style="color:#90a4ae">%s</pre>
              <p style="color:#546e7a;font-size:12px">
                Check that generate_hop_tree.py / generate_trail_map.py
                are present in the scripts-dir and the CSV files are
                in data-dir. See Spring Boot logs for details.
              </p>
            </body></html>
            """.formatted(message);
    }
}

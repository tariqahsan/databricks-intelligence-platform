package mil.disa.oe.service;

import mil.disa.oe.dto.RouterCoordinate;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.File;
import java.io.FileInputStream;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * CoordinateService
 * =================
 * Reads master_dataframe_long.xlsx once on first request and caches
 * the result in memory for the lifetime of the Spring Boot process.
 *
 * The xlsx has three columns: Router | Latitude | Longitude
 * FIX: removed asterisk-slash sequences from node name examples below
 * (8,210 rows: DK_ customer sites + UJEW / UJPW / UURWMEA routers)
 *
 * Configure the file path in application-thrift.yml:
 *
 *   oe:
 *     network-flows:
 *       coords-xlsx: C:/Dev/.../oe-ingestion-pipeline/master_dataframe_long.xlsx
 */
@Service
public class CoordinateService {

    private static final Logger log = LoggerFactory.getLogger(CoordinateService.class);

    @Value("${oe.network-flows.coords-xlsx:}")
    private String coordsXlsxPath;

    // Thread-safe lazy-init cache
    private volatile Map<String, RouterCoordinate> cache = null;

    /**
     * Returns all router coordinates, loading from xlsx on first call.
     * Returns empty map if file is not configured or cannot be read.
     */
    public Map<String, RouterCoordinate> getAll() {
        if (cache == null) {
            synchronized (this) {
                if (cache == null) {
                    cache = load();
                }
            }
        }
        return cache;
    }

    private Map<String, RouterCoordinate> load() {
        if (coordsXlsxPath == null || coordsXlsxPath.isBlank()) {
            log.warn("  coords-xlsx not configured -- router coordinates unavailable");
            return Collections.emptyMap();
        }

        File f = new File(coordsXlsxPath);
        if (!f.exists()) {
            log.warn("  coords-xlsx not found: {}", coordsXlsxPath);
            return Collections.emptyMap();
        }

        log.info("  Loading router coordinates from: {}", coordsXlsxPath);

        Map<String, RouterCoordinate> coords = new LinkedHashMap<>();
        int skipped = 0;

        try (FileInputStream fis = new FileInputStream(f);
             Workbook wb = new XSSFWorkbook(fis)) {

            Sheet sheet = wb.getSheetAt(0);

            // Find column indices from header row
            Row header = sheet.getRow(0);
            int routerCol = -1, latCol = -1, lngCol = -1;
            for (Cell cell : header) {
                String name = cell.getStringCellValue().trim().toLowerCase();
                switch (name) {
                    case "router"                  -> routerCol = cell.getColumnIndex();
                    case "latitude", "lat"         -> latCol    = cell.getColumnIndex();
                    case "longitude", "lng", "lon" -> lngCol    = cell.getColumnIndex();
                }
            }

            if (routerCol < 0 || latCol < 0 || lngCol < 0) {
                log.error("  coords-xlsx missing required columns (Router/Latitude/Longitude)");
                return Collections.emptyMap();
            }

            for (int i = 1; i <= sheet.getLastRowNum(); i++) {
                Row row = sheet.getRow(i);
                if (row == null) continue;

                try {
                    Cell routerCell = row.getCell(routerCol);
                    if (routerCell == null) continue;
                    String router = routerCell.getStringCellValue().trim();
                    if (router.isEmpty()) continue;

                    double lat = numericValue(row.getCell(latCol));
                    double lng = numericValue(row.getCell(lngCol));

                    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
                        skipped++;
                        continue;
                    }

                    // Deduplicate: keep first occurrence per router name
                    coords.putIfAbsent(router, new RouterCoordinate(
                            Math.round(lat * 1_000_000.0) / 1_000_000.0,
                            Math.round(lng * 1_000_000.0) / 1_000_000.0
                    ));
                } catch (Exception e) {
                    skipped++;
                }
            }

        } catch (Exception e) {
            log.error("  Failed to read coords-xlsx: {}", e.getMessage());
            return Collections.emptyMap();
        }

        log.info("  OK  Loaded {} router coordinates ({} skipped)", coords.size(), skipped);
        return Collections.unmodifiableMap(coords);
    }

    private static double numericValue(Cell cell) {
        if (cell == null) return Double.NaN;
        return switch (cell.getCellType()) {
            case NUMERIC -> cell.getNumericCellValue();
            case STRING  -> Double.parseDouble(cell.getStringCellValue().trim());
            default      -> Double.NaN;
        };
    }
}
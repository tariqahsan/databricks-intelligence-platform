package mil.disa.oe.dto;

/**
 * RouterCoordinate
 * ----------------
 * Latitude/longitude for a single router or customer site node.
 * Returned by GET /api/network-flows/coordinates
 * as Map<String, RouterCoordinate> keyed by node name.
 *
 * Consumed by Angular trail map component to draw ant-path routes.
 * Eliminates dependency on the static assets/data/router-coordinates.json file.
 */
public record RouterCoordinate(
        double lat,
        double lng
) {}

package mil.disa.oe.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCache;
import org.springframework.cache.support.SimpleCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;
import java.util.concurrent.TimeUnit;

@Configuration
public class CacheConfig {

    @Bean
    public CacheManager cacheManager() {
        SimpleCacheManager mgr = new SimpleCacheManager();
        mgr.setCaches(List.of(
            // ── Core Gold dashboard caches ───────────────────────────────────
            build("appHealth",          300, 200),
            build("deviceHealth",       300, 200),
            build("networkPerformance", 300, 200),
            build("topIssues",          120, 200),  // shorter -- more volatile
            build("versionSprawl",      600, 100),  // longer  -- slow changing
            build("ingestionStatus",     60,  50),  // very short -- near real-time
            build("platformSummary",    300,  50),

            // ── Netflow Gold caches (DAI + DISA Meade CSV pipeline) ──────────
            // TTL 300s (5 min) -- CSV data is batch-updated, not streaming.
            // maxSize is small since these are aggregated Gold tables, not rows.
            build("networkFlowKpis",          300,  10),
            build("networkHubStats",          300, 300),  // 282 hub nodes
            build("networkLinkLatency",       300, 200),  // 162 circuits
            build("networkPathDistribution",  300,  20)   // 9 hop buckets
        ));
        return mgr;
    }

    private CaffeineCache build(String name, long ttlSeconds, long maxSize) {
        return new CaffeineCache(name,
            Caffeine.newBuilder()
                .expireAfterWrite(ttlSeconds, TimeUnit.SECONDS)
                .maximumSize(maxSize)
                .recordStats()
                .build()
        );
    }
}
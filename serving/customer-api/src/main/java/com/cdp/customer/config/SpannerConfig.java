package com.cdp.customer.config;

import com.google.cloud.spanner.DatabaseClient;
import com.google.cloud.spanner.DatabaseId;
import com.google.cloud.spanner.Spanner;
import com.google.cloud.spanner.SpannerOptions;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SpannerConfig {

    @Bean(destroyMethod = "close")
    public Spanner spanner(SpannerProperties props) {
        return SpannerOptions.newBuilder().setProjectId(props.project()).build().getService();
    }

    @Bean
    public DatabaseClient databaseClient(Spanner spanner, SpannerProperties props) {
        return spanner.getDatabaseClient(DatabaseId.of(props.project(), props.instance(), props.database()));
    }
}

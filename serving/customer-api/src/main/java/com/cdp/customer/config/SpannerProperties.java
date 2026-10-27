package com.cdp.customer.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Spanner connection settings, set by Terraform as environment variables on the Cloud Run service. */
@ConfigurationProperties(prefix = "cdp.spanner")
public record SpannerProperties(String project, String instance, String database) {
}

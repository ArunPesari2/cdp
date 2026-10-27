package com.cdp.customer.repository;

import com.cdp.customer.model.Customer;
import com.cdp.customer.model.Interaction;
import com.google.cloud.spanner.DatabaseClient;
import com.google.cloud.spanner.Key;
import com.google.cloud.spanner.ResultSet;
import com.google.cloud.spanner.Statement;
import com.google.cloud.spanner.Struct;
import com.google.cloud.spanner.StructReader;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Repository;

/**
 * All hot-path reads are primary-key point reads or primary-key prefix scans,
 * so each lookup touches a single Spanner split.
 */
@Repository
public class SpannerCustomerRepository implements CustomerRepository {

    private static final List<String> CUSTOMER_COLUMNS =
            List.of("customer_id", "first_name", "last_name", "email", "phone", "status");

    private final DatabaseClient db;

    public SpannerCustomerRepository(DatabaseClient db) {
        this.db = db;
    }

    @Override
    public Optional<String> findCustomerIdByIdentifier(String idType, String idValue) {
        Struct row = db.singleUse().readRow("IdentityMap", Key.of(idType, idValue), List.of("customer_id"));
        return Optional.ofNullable(row).map(r -> r.getString("customer_id"));
    }

    @Override
    public Optional<Customer> findCustomer(String customerId) {
        Struct row = db.singleUse().readRow("Customer", Key.of(customerId), CUSTOMER_COLUMNS);
        return Optional.ofNullable(row).map(r -> new Customer(
                r.getString("customer_id"),
                nullableString(r, "first_name"),
                nullableString(r, "last_name"),
                nullableString(r, "email"),
                nullableString(r, "phone"),
                nullableString(r, "status")));
    }

    @Override
    public List<Interaction> findRecentInteractions(String customerId, int limit, String channel) {
        String sql = """
                SELECT event_id, event_ts, event_type, channel, intent, agent_id, duration_sec, summary, source
                FROM Interaction
                WHERE customer_id = @customerId
                """ + (channel != null ? "  AND channel = @channel\n" : "") + """
                ORDER BY event_ts DESC
                LIMIT @limit
                """;
        Statement.Builder stmt = Statement.newBuilder(sql)
                .bind("customerId").to(customerId)
                .bind("limit").to(limit);
        if (channel != null) {
            stmt.bind("channel").to(channel);
        }

        List<Interaction> interactions = new ArrayList<>();
        try (ResultSet rs = db.singleUse().executeQuery(stmt.build())) {
            while (rs.next()) {
                interactions.add(new Interaction(
                        rs.getString("event_id"),
                        rs.getTimestamp("event_ts").toString(),
                        rs.getString("event_type"),
                        nullableString(rs, "channel"),
                        nullableString(rs, "intent"),
                        nullableString(rs, "agent_id"),
                        rs.isNull("duration_sec") ? null : rs.getLong("duration_sec"),
                        nullableString(rs, "summary"),
                        rs.getString("source")));
            }
        }
        return interactions;
    }

    private static String nullableString(StructReader row, String column) {
        return row.isNull(column) ? null : row.getString(column);
    }
}

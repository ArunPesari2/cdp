package com.cdp.customer.repository;

import com.cdp.customer.model.Customer;
import com.cdp.customer.model.Interaction;
import java.util.List;
import java.util.Optional;

public interface CustomerRepository {

    /** Resolve a raw identifier (phone, email) to a CDP customer id. */
    Optional<String> findCustomerIdByIdentifier(String idType, String idValue);

    Optional<Customer> findCustomer(String customerId);

    /** Newest first; channel is optional. */
    List<Interaction> findRecentInteractions(String customerId, int limit, String channel);
}

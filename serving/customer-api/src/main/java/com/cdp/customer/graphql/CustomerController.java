package com.cdp.customer.graphql;

import com.cdp.customer.model.Customer;
import com.cdp.customer.model.Interaction;
import com.cdp.customer.repository.CustomerRepository;
import java.util.List;
import java.util.Optional;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.graphql.data.method.annotation.SchemaMapping;
import org.springframework.stereotype.Controller;

@Controller
public class CustomerController {

    private static final int MAX_INTERACTIONS = 50;

    private final CustomerRepository repository;

    public CustomerController(CustomerRepository repository) {
        this.repository = repository;
    }

    /** Look up a customer by CDP id, or by a raw identifier the channel already knows. */
    @QueryMapping
    public Customer customer(@Argument String id, @Argument String phone, @Argument String email) {
        Optional<String> customerId;
        if (id != null) {
            customerId = Optional.of(id);
        } else if (phone != null) {
            customerId = repository.findCustomerIdByIdentifier("phone", phone);
        } else if (email != null) {
            customerId = repository.findCustomerIdByIdentifier("email", email);
        } else {
            throw new IllegalArgumentException("Provide one of: id, phone, email");
        }
        return customerId.flatMap(repository::findCustomer).orElse(null);
    }

    @SchemaMapping(typeName = "Customer")
    public List<Interaction> recentInteractions(Customer customer, @Argument int limit, @Argument String channel) {
        return repository.findRecentInteractions(customer.customerId(), Math.min(Math.max(limit, 1), MAX_INTERACTIONS), channel);
    }
}

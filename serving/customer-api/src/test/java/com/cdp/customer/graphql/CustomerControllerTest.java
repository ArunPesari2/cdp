package com.cdp.customer.graphql;

import static org.mockito.Mockito.when;

import com.cdp.customer.model.Customer;
import com.cdp.customer.model.Interaction;
import com.cdp.customer.repository.CustomerRepository;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.graphql.GraphQlTest;
import org.springframework.graphql.test.tester.GraphQlTester;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

@GraphQlTest(CustomerController.class)
class CustomerControllerTest {

    private static final Customer JAMES =
            new Customer("cust-1", "James", "Davis", "james@example.com", "+12065551488", "active");

    @Autowired
    private GraphQlTester graphQlTester;

    @MockitoBean
    private CustomerRepository repository;

    @Test
    void findsCustomerByPhoneWithRecentInteractions() {
        when(repository.findCustomerIdByIdentifier("phone", "+12065551488")).thenReturn(Optional.of("cust-1"));
        when(repository.findCustomer("cust-1")).thenReturn(Optional.of(JAMES));
        when(repository.findRecentInteractions("cust-1", 5, null)).thenReturn(List.of(
                new Interaction("c-2", "2026-10-18T09:47:29Z", "contact_ended", "call", "billing_question",
                        "A-2208", 343L, "Explained one-time activation fee.", "care")));

        graphQlTester.document("""
                        { customer(phone: "+12065551488") {
                            firstName
                            recentInteractions(limit: 5) { eventTs channel intent summary }
                        } }""")
                .execute()
                .path("customer.firstName").entity(String.class).isEqualTo("James")
                .path("customer.recentInteractions[0].intent").entity(String.class).isEqualTo("billing_question");
    }

    @Test
    void unknownPhoneReturnsNull() {
        when(repository.findCustomerIdByIdentifier("phone", "+19995550000")).thenReturn(Optional.empty());

        graphQlTester.document("{ customer(phone: \"+19995550000\") { firstName } }")
                .execute()
                .path("customer").valueIsNull();
    }
}

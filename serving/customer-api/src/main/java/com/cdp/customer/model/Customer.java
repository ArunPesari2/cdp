package com.cdp.customer.model;

public record Customer(
        String customerId,
        String firstName,
        String lastName,
        String email,
        String phone,
        String status) {
}

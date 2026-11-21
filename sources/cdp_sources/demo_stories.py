"""Fixed demo customers and their care journeys, for testing the profile (and later MCP) on a known person.

The world generator adds these people next to the random ones, and the mock vendor sends their
contacts with `--scenario demo`. Random contacts never go to a demo customer, so the story stays clean.

Each contact is dated relative to the day it is sent (days_ago, at HH:MM UTC), so the story always
looks recent and stays inside Spanner's 90-day row deletion policy on Interaction.
Intents must be one of cdp_common.events.CARE_INTENTS, or the pipeline rejects the contact.
"""

# example.com is reserved for examples (RFC 2606), and 555-0100..0199 numbers are fictional, so demo
# people can't clash with a real address or number. The smoke test skips customers on this domain.
DEMO_EMAIL_DOMAIN = "example.com"

DEMO_CUSTOMERS = [
    {
        "story": "billing escalation",
        "person": {
            "person_id": "P-DEMO-001",
            "first_name": "Priya",
            "last_name": "Sharma",
            "email": "priya.sharma@example.com",
            "phone": "+12065550101",
            "status": "active",
        },
        "contacts": [
            {"days_ago": 21, "at": "15:10", "channel": "VOICE", "minutes": 9, "agent": "agent2214",
             "intent": "plan_change",
             "summary": "Moved from Essentials to Unlimited Plus, effective immediately. "
                        "Customer wanted more hotspot data for work."},
            {"days_ago": 12, "at": "18:42", "channel": "CHAT", "minutes": 14, "agent": "agent2231",
             "intent": "billing_question",
             "summary": "Bill is $40 higher than expected after the plan change. Explained mid-cycle "
                        "proration; customer not convinced and asked for an itemised bill."},
            {"days_ago": 4, "at": "16:05", "channel": "VOICE", "minutes": 22, "agent": "agent2207",
             "intent": "billing_question",
             "summary": "Says she was charged twice for November. Confirmed two plan charges on the "
                        "account. Raised billing dispute ticket; resolution promised in 3-5 days."},
            {"days_ago": 1, "at": "14:28", "channel": "VOICE", "minutes": 17, "agent": "agent2245",
             "intent": "cancel_request",
             "summary": "Dispute still open and no callback received. Customer is upset and says she "
                        "will switch carriers this week. Escalated to retention for a callback."},
        ],
    },
]

DEMO_PHONES = frozenset(c["person"]["phone"] for c in DEMO_CUSTOMERS)

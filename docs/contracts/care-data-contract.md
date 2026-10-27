# Care data contract (v1)

How customer-service contacts enter the CDP. Status: locked for slice 1.

## Source and delivery

| Item | Value |
| --- | --- |
| Source system | Contact-centre platform (calls and chats), vendor format modelled on Amazon Connect CTRs |
| Pattern | P3 Stream: the vendor publishes to Pub/Sub topic `vendor-care-ctr` |
| Message attributes | `source=care`, `vendor=connect`, `record_type=CTR` |
| Delivery | At-least-once; the vendor may resend a record; order is not guaranteed |
| Retention | 7 days on the topic (replay window) |
| Reconciliation | Nightly API pull from the vendor (v2) |

## Vendor record (input)

Sample: [contracts/vendor/connect/ctr.sample.json](../../contracts/vendor/connect/ctr.sample.json)

| Field | Required | Notes |
| --- | --- | --- |
| `ContactId` | Yes | Unique per contact; stable across resends |
| `Channel` | Yes | `VOICE` or `CHAT` |
| `InitiationTimestamp` | Yes | ISO-8601 with an explicit offset (`Z` or `+hh:mm`) |
| `DisconnectTimestamp` | Yes | ISO-8601 with an explicit offset; when the contact ended; not before `InitiationTimestamp` |
| `CustomerEndpoint.Address` | Yes | Caller phone, E.164 |
| `Agent.Username` | Yes | `agentNNNN` |
| `Queue.Name` | No | Routing queue |
| `Attributes.intent` | Yes | One of the intents below |
| `Attributes.summary` | Yes | Agent wrap-up summary |

Timestamp rule: a timestamp without a time-zone offset is rejected (`INVALID_TIMESTAMP`); the CDP never guesses the zone.

## Canonical event (output of the adapter)

Schema: [contracts/events/care/contact_ended.v1.avsc](../../contracts/events/care/contact_ended.v1.avsc)

| Vendor field | Canonical field | Transformation |
| --- | --- | --- |
| `ContactId` | `event_id` | As is |
| (fixed) | `event_type` | `contact_ended` |
| `DisconnectTimestamp` | `event_ts` | Converted to UTC, millisecond precision, `Z` suffix (`2026-10-18T09:47:29.000Z`) |
| `CustomerEndpoint.Address` | `identifiers.phone` | As is |
| `Channel` | `payload.channel` | `VOICE` → `call`, `CHAT` → `chat` |
| `Attributes.intent` | `payload.intent` | As is, validated |
| `Agent.Username` | `payload.agent_id` | `agent2208` → `A-2208` |
| `DisconnectTimestamp − InitiationTimestamp` | `payload.duration_sec` | Seconds, rounded to the nearest second |
| `Queue.Name` | `payload.queue` | As is, optional |
| `Attributes.summary` | `payload.summary` | As is |

Allowed values:

- `channel`: `call`, `chat`
- `intent`: `network_issue`, `billing_question`, `upgrade_inquiry`, `plan_change`, `device_support`, `cancel_request`

## Processing rules

1. Adapt vendor record → canonical event.
2. Validate against this contract.
3. Drop duplicates by `event_id` (24-hour window); Spanner writes are upserts, so replays are safe.
4. Resolve `identifiers.phone` (then `email`) to `customer_id` via Spanner `IdentityMap`.
5. Write Spanner `Interaction` and BigQuery `core.interactions`.

## Dead-letter codes (`ops.dead_letter`)

| Stage | Code | Meaning |
| --- | --- | --- |
| adapter | `INVALID_ENCODING` | Message body is not valid UTF-8 |
| adapter | `INVALID_JSON` | Message body is not JSON |
| adapter | `INVALID_TYPE` | A field has the wrong type (e.g. object expected, string received): vendor format change |
| adapter | `MISSING_FIELD` | A required vendor field is missing or empty |
| adapter | `INVALID_TIMESTAMP` | A timestamp cannot be parsed, has no time zone, or the contact ends before it starts |
| adapter | `UNSUPPORTED_CHANNEL` | `Channel` is not `VOICE` or `CHAT` |
| validate | `MISSING_FIELD` / `INVALID_VALUE` | Canonical event breaks this contract |
| resolve_identity | `UNKNOWN_IDENTITY` | No customer matches the identifiers |

# Collector JSON parsing integrity

The anonymous `POST /api/v1/collect` endpoint rejects **duplicate JSON
object keys at every nesting level** rather than adopting the last or first
value. The accepted format otherwise remains JSON with a bounded 4 KiB
request body, a nonempty `site_id`, allowed `type`, and existing per-field
privacy constraints.

This protects consistent interpretation of repeated `site_id`, `url`,
`properties` and arbitrary nested keys before authorization, event
normalization or database writes. It does not authenticate anonymous events,
validate signatures, prevent spoofing or eliminate sensitive data transmitted
in a rejected request. Developer integrations must generate JSON objects with
unique keys. A duplicate returns HTTP 400 with the generic Invalid JSON
response without reflecting the supplied key or value.

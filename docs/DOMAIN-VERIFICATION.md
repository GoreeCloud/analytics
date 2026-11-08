# DNS ownership proof — early development

**Maturity:** source gate with local regression coverage. No production DNS, deployment, migration or browser acceptance has been verified.

## Procedure

1. An administrator registers an exact hostname through the local dashboard or administrator API. Each domain receives its own 32-byte random URL-safe challenge.
2. The DNS operator adds a TXT record at `_goreecloud-analytics.<hostname>` whose value is `goreecloud-analytics-verification=<challenge>`.
3. After propagation, the administrator uses **Check DNS TXT record** or sends authenticated `POST /api/v1/sites/{site_id}/domains/verify` with JSON `{"domain":"example.com"}`.
4. The server resolves only TXT records with a three-second lifetime, checks an exact token match, stores the verification timestamp and erases the challenge.
5. New events are accepted only from verified hostnames. Other domains attached to the same site remain unverified until individually proved.

## Migration, operations, limitations

- **Back up first.** A startup schema addition creates `site_domains` and migrates previous domain registrations as **pending** without deleting old sites, sessions or events. Pending domains stop ingesting events until checked. This is an intentional breaking behavior change and requires a planned maintenance window for any existing installation.
- DNS queries use the machine's configured recursive resolver, not arbitrary URLs or shell programs. Queries are bounded to three seconds; repeated requests are limited per site and domain on this node. DNS resolver failure returns 503 and missing/mismatched records return 409.
- Proof grants event ingestion permission for an exact hostname; it does **not** authenticate individual event submissions or prove legal domain ownership. It does not defend against subsequent domain transfers, DNS tampering, forged client data, or distributed abuse.
- An authenticated manual `POST /api/v1/sites/{site_id}/domains/revoke` action can invalidate one hostname's proof and rotate its TXT challenge without deleting historical events. Collection immediately stops until reverified. There is still no periodic DNS re-verification, automated ownership-transfer detection, or versioned migration/rollback path.
- The current dashboard administrator token remains a single shared secret. GoreeCloud Identity RBAC, Wardveil network-edge enforcement, and GoreeShield privacy-consent governance are not implemented.

Tests use an injected DNS resolver fake, with no external TXT lookups. No live DNS propagation, browser visual acceptance, or production migration has been asserted.

# Data Distribution and Public-Repository Policy

This repository is public source-control for research code, configuration, validation logic, and auditable evidence metadata. Public availability of repository code does **not** grant redistribution rights for third-party source data.

## Allowed in the public repository

- source code, tests, workflow definitions, and non-secret configuration;
- source URLs, publication identifiers, timestamps, row counts, schemas, and cryptographic hashes used for reproducibility;
- small synthetic fixtures and manually authored regression fixtures that do not reproduce restricted source datasets;
- derived audit summaries that do not expose restricted raw payloads.

## Must not be committed

- credentials, API keys, private keys, session cookies, access tokens, or authenticated request material;
- raw or bulk third-party market data, exchange datasets, CNINFO filing payloads/PDF mirrors, BaoStock datasets, or other source material unless redistribution rights have been independently verified;
- personally identifying or confidential business data not intended for public distribution;
- generated artifacts that contain any of the above.

## Runtime evidence

Large or potentially restricted source artifacts should remain ephemeral CI/runtime artifacts or be retained in access-controlled storage according to the applicable source terms. Durable public evidence should prefer:

- source locator / announcement ID;
- source publication time and point-in-time availability fields;
- SHA-256 of the exact source bytes;
- normalized row counts and schema version;
- derived dataset/content fingerprints;
- gate result and software commit SHA.

A source hash proves identity/integrity; it does not grant permission to redistribute the hashed source.

## Secrets

Repository validation should remain read-only by default. High-confidence secret scanning is a hard gate. If a suspected credential is found, reports must contain only the file path, line number, and finding type; never copy the credential value into logs, issues, PR descriptions, or audit reports.

## Licensing

No software license is selected by this policy document. A separate `LICENSE` file should be added only after the repository owner chooses the intended code license. Third-party data remains governed by its own provider terms regardless of the code license selected later.

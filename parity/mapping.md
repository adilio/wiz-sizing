# Parity map — official Python → wiz-*.sh

Structural parity layer (§8.1): for every count a `wiz-<csp>.sh` emits, this
file cites the official script's source (under `reference/`, the parity
oracle) and the exact bash query + `jq` reduction that reproduces it. A
reviewer can diff intent side-by-side with no credentials.

Conventions:

- **Official** cites `reference/<path>:<line>` at the point the count is
  produced (the API call or the accumulation into the CSV row).
- **Ours** names the `wiz-<csp>.sh` function and the REST/CLI call + `jq`
  reduction.
- **Deviation** links the ledger entry (PLAN.md §9, D1–D6) when the count is
  intentionally non-identical; `—` means the mapping is intended exact.
- Rows marked *pending* are filled in the phase that builds that script.
  A CSP's section being complete is part of that phase's Definition of Done.

## Azure — `wiz-azure.sh`

*Pending — filled in Phase 1.*

| Count (CSV row) | Official | Ours | Deviation |
|---|---|---|---|

## AWS — `wiz-aws.sh`

*Pending — filled in Phase 2.*

| Count (CSV row) | Official | Ours | Deviation |
|---|---|---|---|

## GCP — `wiz-gcp.sh`

*Pending — filled in Phase 3.*

| Count (CSV row) | Official | Ours | Deviation |
|---|---|---|---|

## Code — `wiz-code.sh`

*Pending — filled in Phase 4.*

| Count (output) | Official | Ours | Deviation |
|---|---|---|---|

## M365 — `wiz-365.ps1`

Nothing to map: `wiz-365.ps1` **is** the hardened official PowerShell script
(`reference/saas/microsoft-365/365_Sizing_Script.ps1` promoted verbatim), so
it is its own oracle (PLAN.md §5, §10). Verify with:

```sh
diff wiz-365.ps1 reference/saas/microsoft-365/365_Sizing_Script.ps1
```

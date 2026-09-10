# Repository instructions

Read the workspace instructions at `../workspace/CLAUDE.md`.
This three-runtime Package Skill operates five Neon machines through a directly pinned
`colors-compute` dependency. The package owns topology, application templates,
managed Neon S3 storage/IAM, Cloudflare DNS, local SSH aliases and acceptance.
Compute Terraform, provider selection, backend bucket bootstrap and retirement,
node fan-out, keypair ownership and network resources belong to colors-compute.

`colors.yml` contains non-secret desired state. Credentials use ignored private
environment files. Never export `COLORS_PAR_PROFILE`, track `.colors/`, or edit
generated output. Preserve `compute-prevent-destroy: true`; an explicitly
authorized deletion uses the one-run environment override.

The five nodes are compute-0, pageserver-0 (also broker), and safekeeper-0/1/2.
Do not describe this as complete high availability: compute and pageserver are
single service failure points. Three independent safekeeper disks form WAL quorum.
Native PostgreSQL TLS needs a DNS-only Cloudflare record and explicit plaintext
rejection in HBA. Keep immutable storage and compute image digests paired with
the source versions used to validate their configuration.

Build and dry-run must work without credentials, state reads or local SSH access.
Run each runtime's tests, Red typechecking, golden comparisons, three-color
parity, syntax checks and launcher tests before
publication. Use `NEON_MULTI_NODE_LIB_ROOT` during development; final launchers
must resolve an actual pushed commit. Root deployment launchers must match their
installed payload copies. Write no credentials to output, tests or evidence.

Before deleting application storage, independently prove every writer stopped.
Remove DNS and SSH aliases before compute, then retire the managed backend after
all state resources and local keys have been cleaned. A repeated delete is safe.

Commit and push only when authorized by the user. Every sibling is a separate
repository; preserve unrelated working changes.

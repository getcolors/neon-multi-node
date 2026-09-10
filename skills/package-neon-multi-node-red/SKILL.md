---
name: package-neon-multi-node-red
description: Deploy and operate self-hosted Neon Postgres 17 across separate compute and pageserver machines plus three safekeepers, using Colors Red and colors-compute, managed AWS S3 storage and state, Cloudflare DNS, and native PostgreSQL TLS. Use for neon-multi-node colors.yml deployments, convergence, recovery rehearsals, inspection, and guarded teardown.
---

# Neon Multi-Node Package Skill

Operate the five-machine topology in `getcolors/neon-multi-node`: compute-0,
pageserver-0 (also storage broker), and safekeeper-0/1/2. This skill supplies the
Red TypeScript/Bun runtime; sibling Green and Blue skills use the same desired state and state
addresses. Run one lifecycle operation per profile at a time. The package pins
Colors and colors-compute to immutable Git commits.

Install Bun plus the shared operator tools: OpenTofu, Ansible, AWS CLI 2 with
conditional S3 writes, OpenSSH and PostgreSQL client. The copied executable
resolves immutable package and SDK pins into a local cache. Local source
development can use `NEON_MULTI_NODE_LIB_ROOT=/path/to/neon-multi-node`, while
published validation must run without that override.

Install into the deployment repository:

```sh
npx skills add https://github.com/getcolors/neon-multi-node --skill package-neon-multi-node-red
cp .agents/skills/package-neon-multi-node-red/red ./red
chmod +x red
```

Keep the root launcher synchronized after each skill update. Start from the
non-secret desired state in the public `getcolors/neon-multi-node-aws` deployment,
then change its profile, fixed tenant/timeline identities, bucket names,
provider settings, DNS name, and allowed SSH/Postgres source CIDRs for a new
independent deployment. Never reuse an existing profile to point at fresh state.

Before live actions, run:

```sh
./red build
./red create --dry-run
```

These paths render deterministic artifacts without contacting providers or
accessing SSH files. Resolve all validation errors before continuing. `.colors/`
is generated output; edit desired state or package source, never generated files.

Use `./red create` to converge, `./red describe` to inspect, and
`./red rehearse` for disruptive data-recovery verification. Respect the user's
authorized resources and operations. Rehearsal is intended for test deployments.

Credentials live in ignored private environment files. AWS uses its ambient SDK
credential chain; a non-secret loader may map `COLORS_PAR_AWS_ACCESS_KEY_ID` and
`COLORS_PAR_AWS_SECRET_ACCESS_KEY` to AWS variables. DNS uses
`COLORS_PAR_CLOUDFLARE_API_TOKEN`. Scoped application S3 credentials are created
by the package and passed privately to Ansible. They remain in encrypted
Terraform backend state and root-readable files on owned machines.
Never export `COLORS_PAR_PROFILE` or commit credentials, Terraform state, private
keys, or generated output.

The `neon-r2-bucket`, `neon-r2-region`, `neon-r2-endpoint` and `neon-r2-prefix`
keys retain the existing Neon configuration vocabulary and select native AWS S3.
Use a distinct managed S3 backend bucket (`s3-bucket-mode: managed`) and
`neon-storage-managed: true`. Compute configuration is delegated to the pinned
colors-compute library; application code must not fork its provider templates.

PostgreSQL uses native TLS on port 55433 and a **DNS-only** Cloudflare A record.
A configured certificate alone does not reject plaintext; preserve the custom
HBA policy and exercise negative authentication/TLS checks. The operator path is
`sslmode=verify-full` with a trusted CA bundle and the configured hostname. Obtain
the generated password privately from `/etc/neon/secrets/neon_role_password`
over the generated entry SSH alias using sudo. Do not print it in evidence.

Three independent safekeepers form WAL quorum. Compute and pageserver remain
single service failure points. Treat S3 uploads as asynchronous; never claim
full high availability or zero full-storage-loss RPO from a successful converge.
Acceptance must include real SQL writes and reads, specific auth/plaintext
refusals, fresh WAL objects, persistence through convergence and recovery.

Deletion destroys application data. Keep `compute-prevent-destroy: true` in
committed desired state. For an explicitly authorized teardown only:

```sh
COLORS_PAR_COMPUTE_PREVENT_DESTROY=false ./red delete
```

The DAG must prove every writer stopped before purging the application bucket,
remove DNS and local aliases before destroying machines, retain access keys on
failure, and finalize the state bucket only after complete retirement. Confirm
cloud absence independently and exercise repeated deletion for a lifecycle test.

Live qualification on September 10, 2026 completed fresh Red create, Blue
reconvergence with unchanged resource identities, Blue recovery rehearsal and
Blue deletion with independent resource-absence checks and repeated deletion.
The reverse cycle also passed fresh Blue create, Red reconvergence with unchanged
identities, and Red recovery with exact external witness readback. Red teardown
and independent absence audits passed, followed by successful repeated deletion
through both Red and Blue and a final independent absence audit.
These results cover the recorded source pins and a single availability zone;
see the deployment report before extending them to other versions or failures.

Read the [package README](https://github.com/getcolors/neon-multi-node#readme)
for operation and recovery limits, the [Red SDK](https://github.com/getcolors/red)
for workflow semantics, and [colors-compute](https://github.com/getcolors/colors-compute)
for the compute contract. The [AWS deployment](https://github.com/getcolors/neon-multi-node-aws)
records what was actually verified at the published pins.

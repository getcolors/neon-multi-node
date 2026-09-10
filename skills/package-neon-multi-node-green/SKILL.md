---
name: package-neon-multi-node-green
description: Deploy and operate self-hosted Neon Postgres 17 across separate compute and pageserver machines plus three safekeepers, using Colors Green and colors-compute, managed AWS S3 storage and state, Cloudflare DNS, and native PostgreSQL TLS. Use for neon-multi-node colors.yml deployments, convergence, recovery rehearsals, inspection, and guarded teardown.
---

# Neon Multi-Node Package Skill

Operate the five-machine topology in `getcolors/neon-multi-node`: compute-0,
pageserver-0 (also storage broker), and safekeeper-0/1/2. Green is the provided
runtime. The package pins Colors and colors-compute to immutable Git commits.

Install into the deployment repository:

```sh
npx skills add https://github.com/getcolors/neon-multi-node --skill package-neon-multi-node-green
cp .agents/skills/package-neon-multi-node-green/green ./green
chmod +x green
```

Keep the root launcher synchronized after each skill update. Start from the
non-secret desired state in the public `getcolors/neon-multi-node-aws` deployment,
then change its profile, fixed tenant/timeline identities, bucket names,
provider settings, DNS name, and allowed SSH/Postgres source CIDRs for a new
independent deployment. Never reuse an existing profile to point at fresh state.

Before live actions, run:

```sh
./green build
./green create --dry-run
```

These paths render deterministic artifacts without contacting providers or
accessing SSH files. Resolve all validation errors before continuing. `.colors/`
is generated output; edit desired state or package source, never generated files.

Use `./green create` to converge, `./green describe` to inspect, and
`./green rehearse` for disruptive data-recovery verification. Respect the user's
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
COLORS_PAR_COMPUTE_PREVENT_DESTROY=false ./green delete
```

The DAG must prove every writer stopped before purging the application bucket,
remove DNS and local aliases before destroying machines, retain access keys on
failure, and finalize the state bucket only after complete retirement. Confirm
cloud absence independently and exercise repeated deletion for a lifecycle test.

Read the [package README](https://github.com/getcolors/neon-multi-node#readme)
for operation and recovery limits, the [Green SDK](https://github.com/getcolors/green)
for workflow semantics, and [colors-compute](https://github.com/getcolors/colors-compute)
for the compute contract. The [AWS deployment](https://github.com/getcolors/neon-multi-node-aws)
records what was actually verified at the published pins.

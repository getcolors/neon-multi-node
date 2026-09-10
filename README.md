# Neon Multi-Node

A Colors Package Skill in Green (Clojure/Babashka), Red (TypeScript/Bun), and
Blue (Python/uv) for self-hosted Neon Postgres 17 across five
machines: one compute node, one pageserver with a storage broker, and three
safekeepers with separate disks. Compute and network resources are managed by
[colors-compute](https://github.com/getcolors/colors-compute).

The package manages an S3 Terraform backend bucket and a separate Neon data
bucket, scoped application IAM credentials, a machine SSH keypair, Cloudflare
DNS, and native PostgreSQL TLS. The database endpoint is restricted to configured
client CIDRs. Cloudflare serves DNS only; PostgreSQL does not use its HTTP proxy.

## Install and operate

```sh
npx skills add https://github.com/getcolors/neon-multi-node --skill package-neon-multi-node-green
cp .agents/skills/package-neon-multi-node-green/green ./green
chmod +x green
./green build
./green create --dry-run
./green create
./green describe
./green rehearse
```

Choose `package-neon-multi-node-red` and its `red` launcher, or
`package-neon-multi-node-blue` and its `blue` launcher, for the other runtimes.
All three read the same `colors.yml`, use the same state addresses and execute
their native Colors graphs through matching `colors-compute` implementations.
Run only one lifecycle operation for a profile at a time.

Use the [AWS deployment](https://github.com/getcolors/neon-multi-node-aws)
for complete desired state. Keep credentials in ignored `.envrc.private`; the
tracked `.envrc` loads it. AWS compute and state use the ambient AWS SDK chain;
Cloudflare uses `COLORS_PAR_CLOUDFLARE_API_TOKEN`. Never export
`COLORS_PAR_PROFILE`. After a skill update, copy its launcher again.

The inherited `neon-r2-*` configuration keys name S3-compatible application
storage. In this package they select a lifecycle-managed native AWS S3 bucket;
their names do not imply Cloudflare R2 is being used.

The generated application password stays on the compute machine at
`/etc/neon/secrets/neon_role_password`. Read it privately over `ssh <profile>`
with `sudo`, then connect using `sslmode=verify-full`, the configured hostname,
port 55433 and a trusted system CA bundle. Do not paste passwords into logs.

## Recovery and deletion

The `rehearse` operation performs disruptive recovery checks on the owned test
deployment. Use it only where those interruptions are authorized. Separate
safekeepers provide WAL quorum; compute and pageserver remain single service
failure points. S3 uploads are asynchronous, and a full storage-tier loss has a
weaker recovery bound than loss of one safekeeper. Do not infer zone or region
survival from a single-zone functional test.

`compute-prevent-destroy` defaults to true. Authorized teardown uses:

```sh
COLORS_PAR_COMPUTE_PREVENT_DESTROY=false ./green delete
```

Deletion stops and verifies every writer, removes DNS and SSH aliases, destroys
the application bucket and scoped IAM credentials, destroys compute, and finally
retires the managed state bucket and local keypair. **This deletes the database.**
Export data first if it must survive. Do not add object-expiration lifecycle
rules to Neon storage; objects may still be referenced by live timelines.

## Verified deployment

The [AWS verification report](https://github.com/getcolors/neon-multi-node-aws/blob/main/verification.md)
records the live build on September 10, 2026: PostgreSQL 17.5 across five EC2
instances and six containers in one availability zone. Trusted public TLS,
authentication and network isolation, fresh S3 WAL uploads, and reconvergence
with unchanged machine, disk and container identities passed.

Recovery tests replaced compute, exercised every single-safekeeper outage,
withheld write acknowledgement without quorum, restarted the broker, reattached
a wiped pageserver cache from S3 and surviving WAL, and rebuilt one empty
safekeeper. Independent external queries retained the random deployment witness
and every recorded acknowledged outage write. A timed-out write was present
after quorum returned: a client timeout does not establish rollback.

Use the report's final inventory for the test deployment's resource status.
These results do not prove availability-zone survival, automatic compute or
pageserver failover, or recovery from simultaneous loss of all storage machines.

## Implementation dependencies

The matching [Green](https://github.com/getcolors/green),
[Red](https://github.com/getcolors/red), or [Blue](https://github.com/getcolors/blue)
SDK supplies execution graphs, scaffolding and provider boundaries.
[colors-compute](https://github.com/getcolors/colors-compute)
owns machine, network, SSH keypair and state-backend lifecycles. Exact dependency
commits live in [green/deps.edn](green/deps.edn),
[red/package.json](red/package.json), and [blue/pyproject.toml](blue/pyproject.toml).

The package reuses the pinned [Neon package](https://github.com/getcolors/neon)
Ansible configuration and local inventory templates. Its multi-node runtime,
playbooks and application-storage Terraform live in this repository. The
bootstrap ownership protocol, compute specification and SCRAM helper were
adapted from that Neon package; they are maintained here for this topology.
Application storage credentials remain in encrypted Terraform backend state and
root-readable files on the owned machines.

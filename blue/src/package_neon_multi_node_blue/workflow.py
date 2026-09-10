"""The graph, the port of io.github.getcolors.neon-multi-node.workflow."""

from __future__ import annotations

import os

from blue import dry_run, progress, tofu
from blue.cli import par_name, read_pars
from blue.lifecycle import preflight
from blue.workflow import advice_add, failed, workflow
from colors_compute.inspection import read_deployment
from colors_compute import finalize_backend

from . import ssh, ssh_config, tools, validate, topology, storage

DEFAULTS = {"provider-compute": validate.default_compute_provider, "provider-dns": "cloudflare",
            "provider-backend": "s3", "compute-prevent-destroy": True,
            "workdir": ".colors", "neon-pg-version":17, "neon-storage-managed":True, "cloudflare-proxied":False}


STATE_EVENTS = ('delete', 'rehearse', 'describe')


async def start_step(original, env=None):
    environment = dict(os.environ if env is None else env)
    async def after(opts, _env, context):
        if context['real'] and context['event'] in STATE_EVENTS:
            result = await read_deployment(opts, {**environment, **storage.aws_env(opts)}, None, topology.requirements(opts))
            if context['event'] == 'delete' and opts.get('s3-bucket-mode') == 'managed' and result['status'] in ('absent','destroyed','error'):
                return {**opts, 'neon-multi-node/finalize-only': True, 'blue/exit': 0}
            if result['status'] == 'destroyed' and context['event'] == 'delete':
                return {**opts, 'neon-multi-node/already-destroyed': True, 'blue/exit': 0}
            if result['status'] != 'present':
                return {**opts, 'blue/exit': 1, 'blue/err': 'compute state unavailable; legacy monolithic state requires explicit migration'}
            opts = {**opts, 'colors-compute/cluster': result['cluster'], 'colors-compute/shared': result.get('shared', {})}
            path = result.get('key', {}).get('private_key_path')
            if path:
                opts['ssh-private-key-path'] = path
            if context['event'] == 'rehearse' and storage.managed(opts):
                opts = await storage.read_credentials(opts)
            return {**opts, 'blue/exit': 0}
        if context['real'] and context['event'] == 'create':
            return ssh_config.preflight(opts)
        return {**ssh.with_machine_key(opts), 'blue/exit': 0}
    return await preflight(original, defaults=DEFAULTS, overlay=read_pars, env=env,
        validators=[lambda _o, e, _c: validate.env_errors(e),
            lambda o, _e, _c: validate.state_errors(o),
            lambda o, _e, c: validate.secret_errors(o, c['event']) if c['real'] and c['event'] in ('create', 'delete') and not validate.state_errors(o) else [],
            lambda o, _e, c: ['compute destruction is protected; set COLORS_PAR_COMPUTE_PREVENT_DESTROY=false to delete'] if c['real'] and c['event'] == 'delete' and o.get('compute-prevent-destroy') else []],
        after_validate=after)


async def backend_finalize_step(opts):
    try:
        result = await finalize_backend(opts, {**os.environ, **storage.aws_env(opts)})
        if result['status'] not in ('destroyed', 'absent', 'skipped'):
            raise ValueError()
        return {**opts, 'blue/exit': 0}
    except Exception:
        return {**opts, 'blue/exit': 1, 'blue/err': 'managed backend finalization refused; live or unowned state remains'}


def wire_fn(step: str, run_opts: dict):
    event = run_opts.get("blue/event")
    if event == "delete":
        return {
            "neon-multi-node/start": (start_step, "neon-multi-node/ansible"),
            "neon-multi-node/ansible": (tools.ansible_step, "neon-multi-node/ssh-config"),
            # The `~/.ssh/config` block goes before the destroy, the opposite
            # of the keypair below. A block that outlives its hosts is stale
            # but harmless; a key that predeceases them locks the operator out
            # of machines that still exist. Both orders are deliberate; see
            # standards/ssh-config.md.
            "neon-multi-node/ssh-config": (tools.ansible_local_step, "neon-multi-node/dns"),
            # DNS before the compute destroy: a record pointing at a released
            # address is worse than no record.
            "neon-multi-node/dns": (tools.dns_step, "neon-multi-node/storage" if storage.managed(run_opts) else "neon-multi-node/infrastructure"),
            "neon-multi-node/storage": (storage.storage_step, "neon-multi-node/infrastructure"),
            "neon-multi-node/infrastructure": (tools.infrastructure_step, "neon-multi-node/backend-finalize") if run_opts.get("s3-bucket-mode") == "managed" else (tools.infrastructure_step,),
            "neon-multi-node/backend-finalize": (backend_finalize_step,),
        }.get(step)
    if event == "rehearse":
        return {
            "neon-multi-node/start": (start_step, "neon-multi-node/rehearsal"),
            "neon-multi-node/rehearsal": (tools.rehearsal_step,),
        }.get(step)
    if event == "describe":
        return {
            "neon-multi-node/start": (start_step, "neon-multi-node/describe"),
            "neon-multi-node/describe": (tools.describe_step,),
        }.get(step)
    return {
        "neon-multi-node/start": (start_step, "neon-multi-node/infrastructure"),
        # After compute, which is where the addresses first exist, and before
        # the stage that converges the machines — the converge and the
        # acceptance both ride the aliases this stage writes.
        "neon-multi-node/infrastructure": (tools.infrastructure_step, "neon-multi-node/storage" if storage.managed(run_opts) else "neon-multi-node/dns"),
        "neon-multi-node/storage": (storage.storage_step, "neon-multi-node/dns"),
        # DNS before the converge: Certbot provisions its certificate over ACME
        # on first start, and the HTTP-01 challenge needs the name to already
        # resolve to the compute host.
        "neon-multi-node/dns": (tools.dns_step, "neon-multi-node/ssh-config"),
        "neon-multi-node/ssh-config": (tools.ansible_local_step, "neon-multi-node/ansible"),
        "neon-multi-node/ansible": (tools.ansible_step, "neon-multi-node/acceptance"),
        "neon-multi-node/acceptance": (tools.acceptance_step,),
    }.get(step)


def backend_advice(tool: str):
    return tofu.conventional_backend_advice(
        dir=lambda o, tool=tool: tools.tool_dir(o, tool),
        key=lambda o, tool=tool: f"{o.get('profile') or ''}/{tool}.tfstate")


side_effecting = [
    "neon-multi-node/backend-finalize", "neon-multi-node/storage",
    "neon-multi-node/infrastructure", "neon-multi-node/dns", "neon-multi-node/ssh-config",
    "neon-multi-node/ansible", "neon-multi-node/acceptance",
    "neon-multi-node/rehearsal", "neon-multi-node/describe",
]


def create_workflow():
    wf = workflow(start="neon-multi-node/start", wire_fn=wire_fn, next_fn=lambda step, successors, opts: [] if opts.get("neon-multi-node/already-destroyed") or failed(opts) else [("neon-multi-node/backend-finalize", opts)] if step == "neon-multi-node/start" and opts.get("neon-multi-node/finalize-only") else [(successor, opts) for successor in successors or []])
    wf = advice_add(wf, "neon-multi-node/dns", "before", "neon-multi-node.workflow/backend",
                    backend_advice(tools.dns_tool))
    wf = advice_add(wf, "neon-multi-node/storage", "before", "neon-multi-node.workflow/storage-backend", backend_advice(storage.tool))
    return dry_run.advise(progress.advise(wf), side_effecting)


neon_multi_node_workflow = create_workflow()

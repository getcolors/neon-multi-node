"""The steps and every template spec, the port of io.github.getcolors.neon-multi-node.tools."""

from __future__ import annotations

import json
import math
import os
from decimal import Decimal
from pathlib import Path

import package_neon_blue
from blue import tofu
from blue.ansible import ansible_with_spec, parse_recap
from blue.cli import stage_dir
from blue.runtime import runtime
from blue.scaffold import PRESERVE_JINJA_DELIMITERS, content_spec
from colors_compute.orchestration import orchestrate
from colors_compute.planning import plan_deployment
from blue.scaffold import scaffold

from . import ssh_config, topology, validate, storage
from .utils import clj_str as _s

infrastructure_tool = "neon-multi-node-infrastructure"
dns_tool = "neon-multi-node-dns"
ansible_tool = "neon-multi-node-ansible"
ansible_local_tool = "neon-multi-node-ansible-local"
ROOT = Path(__file__).parent / "resources"

# Pinned Neon supplies generic Ansible config; application resources are owned here.
NEON_ROOT = Path(package_neon_blue.__file__).parent / "resources"

template_opts = PRESERVE_JINJA_DELIMITERS


def tool_dir(opts: dict, tool: str) -> str:
    return stage_dir(opts, tool, default_profile="neon-multi-node")


def template(path: str, file: str) -> dict:
    name = f"tools/{path}/{file}"
    return {"name": name, "content": (ROOT / name).read_text()}


def neon_template(path: str, file: str) -> dict:
    name = f"tools/{path}/{file}"
    return {"name": f"neon/{name}", "content": (NEON_ROOT / name).read_text()}


def spec(source: dict, target: str, data: dict) -> dict:
    return {"template": source, "target": target, "data": data, "opts": template_opts}


def raw_spec(target: str, content: str) -> dict:
    return content_spec(target, content)


def credential_env(opts: dict, *slots: str) -> dict[str, str] | None:
    merged: dict[str, str] = {}
    for slot in [*slots, "provider-backend"]:
        merged.update(validate.tofu_env(opts, slot))
    result = {}
    for key, env_var in merged.items():
        value = _s(opts.get(key))
        if value:
            result[env_var] = value
    return result or None


def backend_credential_env(opts: dict) -> dict[str, str] | None:
    return credential_env(opts)


# ------------------------------------------------------------------- json


def _java_double(value: float) -> str:
    """`Double.toString`, which is what Cheshire writes for a double: plain
    decimal with at least one fractional digit between 1e-3 and 1e7, and
    `d.dddE<n>` computerized scientific notation outside that range."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    sign = "-" if value < 0 else ""
    digits, exponent = Decimal(repr(abs(value))).as_tuple()[1:]
    text = "".join(str(d) for d in digits).rstrip("0") or "0"
    # the decimal point sits after `point` digits of `text`
    point = len(digits) + exponent
    if 1e-3 <= abs(value) < 1e7:
        if point <= 0:
            return f"{sign}0.{'0' * (-point)}{text}"
        if point >= len(text):
            return f"{sign}{text}{'0' * (point - len(text))}.0"
        return f"{sign}{text[:point]}.{text[point:]}"
    mantissa = text[0] + "." + (text[1:] or "0")
    return f"{sign}{mantissa}E{point - 1}"


def _json_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _java_double(value)
    return json.dumps(str(value), ensure_ascii=False)


def _pretty(value, indent: int = 0) -> str:
    """Cheshire's pretty JSON, byte for byte — Green's artifact contract. In
    insertion order: `tofu.constructs_json` sorts keys, which is right for a
    Terraform document and wrong for the documents this package writes
    itself, where the order is the caller's."""
    if isinstance(value, (list, tuple)):
        if not value:
            return "[ ]"
        return "[ " + ", ".join(_pretty(item, indent) for item in value) + " ]"
    if isinstance(value, dict):
        if not value:
            return "{ }"
        pad = " " * (indent + 2)
        body = ",\n".join(f"{pad}{json.dumps(str(k), ensure_ascii=False)} : {_pretty(v, indent + 2)}"
                          for k, v in value.items())
        return "{\n" + body + "\n" + " " * indent + "}"
    return _json_scalar(value)


# ------------------------------------------------------------- compute output


def hosts(opts: dict) -> list[dict]:
    """The host list for every stage after compute: the recorded cluster
    under `colors-compute/cluster` on a real run, library plans on a build (see
    `topology.hosts`)."""
    return topology.hosts(opts)


# ---------------------------------------------------------------- compute

def http_sources(opts):return {'source':'explicit','ranges':[]}
def ranges_checksum(values):return 'none'

async def infrastructure_step(opts):
    resolved = http_sources(opts)
    if opts.get('blue/event') == 'create' and not opts.get('blue/dry-run') and resolved['source'] == 'fallback':
        return {**opts, 'blue/exit': 1, 'blue/err': 'Cloudflare ingress ranges unavailable; refusing stale fallback'}
    requirements = topology.requirements(opts)
    try:
        if opts.get('blue/event') == 'build' or opts.get('blue/dry-run'):
            result = plan_deployment(opts, topology.topology(opts), requirements)
            specs = []
            root = Path(opts['workdir']) / opts['profile'] / 'compute'
            for name, document in result['documents']['shared'].items():
                specs.append(raw_spec(str(root / 'shared' / name), json.dumps(document, indent=2, sort_keys=True) + '\n'))
            for node_id, documents in result['documents']['nodes'].items():
                for name, document in documents.items():
                    specs.append(raw_spec(str(root / 'nodes' / node_id / name), json.dumps(document, indent=2, sort_keys=True) + '\n'))
            specs.append(raw_spec(str(root / 'http-sources.json'), _pretty({'origin': resolved['source'], 'checksum': ranges_checksum(resolved['ranges']), 'ranges': resolved['ranges']})))
            scaffold(opts, specs)
        else:
            result = await orchestrate(opts, topology.topology(opts), requirements, {**os.environ, **storage.aws_env(opts)})
        if result['status'] not in ('planned', 'ready', 'destroyed'):
            return {**opts, 'blue/exit': 1, 'blue/err': '\n'.join(result.get('errors', [])) or 'compute lifecycle refused'}
        output = {**opts, 'blue/exit': 0}
        if 'cluster' in result:
            output['colors-compute/cluster'] = result['cluster']
            output['colors-compute/shared'] = result.get('shared', {})
        path = result.get('key', {}).get('private_key_path')
        if path:
            output['ssh-private-key-path'] = path.replace('$HOME', '/home/build-placeholder') if result['status'] == 'planned' else path
        return output
    except (ValueError, KeyError):
        return {**opts, 'blue/exit': 1, 'blue/err': 'invalid compute deployment requirements'}


# ------------------------------------------------------------------- dns


def zone_id() -> str:
    return "${data.cloudflare_zone.zone.id}"


def dns_json(opts: dict, app_ip: str | None) -> str:
    """DNS-only public A record; PostgreSQL cannot use the HTTP proxy."""
    return tofu.constructs_json([
        tofu.construct("resource", "cloudflare_dns_record", "neon-multi-node", {
            "zone_id": zone_id(),
            "name": opts.get("neon-host"),
            "type": "A",
            "content": app_ip,
            "ttl": 1,
            "proxied": bool(opts.get("cloudflare-proxied")),
        }),
    ])


async def dns_step(opts: dict) -> dict:
    dir = tool_dir(opts, dns_tool)
    app = topology.host_of(hosts(opts), "compute") or {}
    specs = [spec(template("dns", "main.tf"), f"{dir}/main.tf", opts),
             raw_spec(f"{dir}/record.tf.json", dns_json(opts, app.get("ip")))]
    return await tofu.tofu_with_spec(
        opts, specs, dir=dir, env=credential_env(opts, "provider-dns"))


# ------------------------------------------------------- ssh config (local)


def ansible_local_data(opts: dict) -> dict:
    """Only what a `build` genuinely knows. Addresses are run-time facts and
    reach the play as extra-vars instead, so the rendered playbook carries no
    IP and is identical on every workstation (SSH Config Standard §6)."""
    return {**opts,
            "ssh-keygen": validate.keygen(opts),
            "ssh-config-identity-file": ssh_config.identity_file(opts) if validate.keygen(opts) else opts.get("ssh-private-key-path", "")}


def ansible_local_specs(opts: dict) -> list[dict]:
    dir = tool_dir(opts, ansible_local_tool)
    data = ansible_local_data(opts)
    # ansible.cfg and the inventory are the dependency's, unchanged; the play
    # is this package's own because it writes six stanzas, not one.
    return [spec(neon_template("ansible-local", "ansible.cfg"), f"{dir}/ansible.cfg", data),
            spec(neon_template("ansible-local", "inventory.ini"), f"{dir}/inventory.ini", data),
            spec(template("ansible-local", "main.yml"), f"{dir}/main.yml", data)]


def ssh_config_hosts(opts, hosts_):
    app = topology.host_of(hosts_, 'compute')
    return [{'name': ssh_config.host_alias(opts), 'ip': app['ip'], 'user': app['user']},
            *[{'name': ssh_config.machine_alias(opts, h), 'ip': h['ip'], 'user': h['user']} for h in hosts_]]


async def ansible_local_step(opts: dict) -> dict:
    """Write or remove the `~/.ssh/config` block. The same playbook serves
    both events; `block_state` is what distinguishes them."""
    dir = tool_dir(opts, ansible_local_tool)
    delete = opts.get("blue/event") == "delete"
    return await ansible_with_spec(
        opts, ansible_local_specs(opts),
        dir=dir, inventory="inventory.ini",
        playbooks={"create": "main.yml", "delete": "main.yml"},
        extra_vars={"host_alias": ssh_config.host_alias(opts),
                    "ssh_hosts": ssh_config_hosts(opts, hosts(opts)),
                    "block_state": "absent" if delete else "present"})



def inventory(opts,nodes):
    children={}
    for role in ['compute','pageserver','safekeeper']:
        children[role]={'hosts':{h['node_id']:{'ansible_host':h['ip'],'ansible_user':h['user'],'vpc_ip':h['vpc_ip'],'role':role,'ordinal':h['index']} for h in sorted(nodes,key=lambda x:x['node_id']) if h['role']==role}}
    return _pretty({'all':{'children':children}})

def ansible_data(opts):
    return {**{k:v for k,v in opts.items() if k!='neon-multi-node/storage-credentials'},'domain':opts['neon-host'],'ssh-keygen':validate.keygen(opts)}

ANSIBLE_FILES=['site.yml','cleanup.yml','rehearsal.yml','runtime.py','bootstrap.sh','scramgen.py','compute-spec.json','acceptance.py','renew-tls.sh','rehearse-member.yml']

def ansible_specs(opts):
    directory=tool_dir(opts,ansible_tool);data=ansible_data(opts)
    return [spec(neon_template('ansible','ansible.cfg'),directory+'/ansible.cfg',data),
            raw_spec(directory+'/inventory.json',inventory(opts,hosts(opts))),
            *[spec(template('ansible',name),directory+'/'+name,data) for name in ANSIBLE_FILES]]

def cleanup_proof(opts,output):
    import re
    expected={n['node_id'] for n in hosts(opts)}
    recap=parse_recap(output)
    reported=set(re.findall(r'(?m)^\s*"msg": "WRITERS_STOPPED ([a-z0-9-]+) PASS independent absence of Neon containers and writer processes"\s*$',output))
    if not (len(expected)==5 and expected==reported and expected==set(recap) and all(c['ok']>0 and all(c.get(k,-1)==0 for k in ['failed','unreachable','rescued','ignored']) for c in recap.values())):
        raise RuntimeError('writer stop proof incomplete; storage deletion refused')
    return expected

async def run_play(opts,playbook,credentials=False):
    rendered={**scaffold({**opts,'blue/event':'build'},ansible_specs(opts)),'blue/event':opts.get('blue/event')}
    if opts.get('blue/event')=='build':return {**rendered,'blue/exit':0}
    env={'ANSIBLE_HOST_KEY_CHECKING':'True','ANSIBLE_SSH_ARGS':'-o StrictHostKeyChecking=accept-new'}
    if credentials:env.update(storage.credential_env(opts))
    result=await runtime.exec(['ansible-playbook','-i','inventory.json',playbook],cwd=tool_dir(opts,ansible_tool),env=env,timeout_ms=7200000)
    if result.exit:return {**rendered,'blue/exit':1,'blue/err':'Ansible failed: '+result.out+result.err}
    if playbook=='cleanup.yml':
        try:
            stopped=cleanup_proof(opts,result.out)
            target=Path(opts['workdir'])/opts['profile']/'writer-stop-evidence.txt';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(result.out)
            return {**rendered,'blue/exit':0,'ansible/recap':parse_recap(result.out),'neon-multi-node/writers-stopped':stopped}
        except Exception as e:return {**rendered,'blue/exit':1,'blue/err':str(e)}
    return {**rendered,'blue/exit':0,'ansible/recap':parse_recap(result.out)}

async def ansible_step(opts):
    if opts.get('blue/event')=='delete' and opts.get('colors-compute/cluster') is None:return {**opts,'blue/exit':0}
    return await run_play(opts,'cleanup.yml' if opts.get('blue/event')=='delete' else 'site.yml',opts.get('blue/event')=='create')
async def rehearsal_step(opts):return await run_play(opts,'rehearsal.yml',True)
async def acceptance_step(opts):
    if opts.get('blue/event')=='build' or opts.get('blue/dry-run'):return {**opts,'blue/exit':0}
    cfg={k:opts[k] for k in ['profile','neon-host','neon-role','neon-database']}
    result=await runtime.exec(['python3','acceptance.py',json.dumps(cfg)],cwd=tool_dir(opts,ansible_tool),timeout_ms=600000)
    return {**opts,'blue/exit':0 if result.exit==0 else 1,'blue/err':result.out+result.err}
async def describe_step(opts):
    try:
        for node in hosts(opts):
            alias=opts['profile']+'-'+node['node_id']
            result=await runtime.exec(['ssh','-o','BatchMode=yes',alias,'sudo','-n','python3','/opt/neon/runtime.py','status'])
            rows=[json.loads(line) for line in result.out.splitlines() if line.strip()]
            expected=2 if node['role']=='pageserver' else 1
            if result.exit or len(rows)!=expected or not all(row['State']=='running' and row.get('Health')!='unhealthy' for row in rows):raise RuntimeError('unhealthy role: '+node['node_id'])
            print('PASS healthy '+node['node_id'])
        return {**opts,'blue/exit':0}
    except Exception as e:return {**opts,'blue/exit':1,'blue/err':str(e)}

"""Application validation; provider validation remains in colors-compute."""
import re
from colors_compute.planning import plan_deployment
from colors_compute.ssh import _mode
from . import topology
default_compute_provider=topology.default_compute_provider
def keygen(opts):return _mode(opts)['mode']=='managed'
def env_errors(env):return ['COLORS_PAR_PROFILE is forbidden; set profile in colors.yml'] if env.get('COLORS_PAR_PROFILE') else []
REQUIRED=['profile','neon-image','neon-compute-image','neon-tenant-id','neon-timeline-id','neon-database','neon-role','neon-r2-bucket','neon-r2-region','neon-r2-endpoint','neon-r2-prefix','neon-host','cloudflare-zone']
def state_errors(opts):
    errors=[k+' is required' for k in REQUIRED if not str(opts.get(k) or '').strip()]
    if type(opts.get('neon-pg-version')) is not int or opts['neon-pg-version']!=17:errors.append('neon-pg-version must be 17; this package supports PostgreSQL 17 only')
    if not re.search(r'(?:^|/)compute-node-v17:',str(opts.get('neon-compute-image'))):errors.append('neon-compute-image must identify compute-node-v17 to match neon-pg-version')
    if opts.get('provider-dns')!='cloudflare':errors.append('provider-dns must be cloudflare')
    if opts.get('cloudflare-proxied') is not False:errors.append('PostgreSQL DNS must be unproxied')
    for k in ['neon-image','neon-compute-image']:
        if not re.search(r'@sha256:[0-9a-f]{64}$',str(opts.get(k))):errors.append(k+' must be pinned by digest')
    for k in ['neon-tenant-id','neon-timeline-id']:
        if not re.fullmatch(r'[0-9a-f]{32}',str(opts.get(k))):errors.append(k+' must contain 32 lowercase hex digits')
    for k in ['neon-role','neon-database']:
        if not re.fullmatch(r'[a-z_][a-z0-9_]*',str(opts.get(k))):errors.append(k+' must be a SQL identifier')
    if type(opts.get('compute-prevent-destroy')) is not bool:errors.append('compute-prevent-destroy must be boolean')
    if opts.get('neon-storage-managed') is not True:errors.append('neon-storage-managed must be true')
    patterns={'neon-host':r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}','cloudflare-zone':r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}','neon-r2-bucket':r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]','neon-r2-region':r'[a-z]{2}(?:-[a-z]+)+-[0-9]','neon-r2-endpoint':r'https://[a-z0-9.-]+(?::[0-9]+)?','neon-r2-prefix':r'[a-zA-Z0-9][a-zA-Z0-9/_-]*'}
    for k,pattern in patterns.items():
        if not re.fullmatch(pattern,str(opts.get(k))):errors.append(k+' has invalid characters or format')
    if opts.get('s3-region')!=opts.get('neon-r2-region'):errors.append('application storage region must match backend region')
    if opts.get('s3-bucket')==opts.get('neon-r2-bucket'):errors.append('state and application buckets must differ')
    try:plan_deployment(opts,topology.topology(opts),topology.requirements(opts))
    except Exception as e:errors.append(str(e))
    return errors
def secret_errors(opts,event):return ['COLORS_PAR_CLOUDFLARE_API_TOKEN is required'] if event=='create' and not str(opts.get('cloudflare-api-token') or '').strip() else []
def tofu_env(opts,slot):return {'cloudflare-api-token':'CLOUDFLARE_API_TOKEN'} if slot=='provider-dns' else {}

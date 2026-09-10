"""Five stable application roles delegated to colors-compute."""
from colors_compute.contract import collect, expand
from colors_compute.deployment_request import source_cidrs
from colors_compute.planning import plan_deployment
default_compute_provider='aws'
def topology(opts):
    return [{'role':'compute','count':1},{'role':'pageserver','count':1},{'role':'safekeeper','count':3}]
def requirements(opts):
    ssh={'id':'ssh','protocol':'tcp','from_port':22,'to_port':22,'sources':source_cidrs(opts,'ssh-sources','ssh-sources')}
    def peer(id,port,roles):return {'id':id,'protocol':'tcp','from_port':port,'to_port':port,'peer_roles':roles}
    def policy(rules):return {'ingress':[ssh,*rules],'egress':'all','private_filter':True}
    return {'private':True,'entry_node_id':'compute-0','security':policy([]),'roles':{
        'compute':{'security':policy([{'id':'postgres','protocol':'tcp','from_port':55433,'to_port':55433,'sources':source_cidrs(opts,'postgres-sources','postgres-sources')},{'id':'acme','protocol':'tcp','from_port':80,'to_port':80,'sources':['0.0.0.0/0']}])},
        'pageserver':{'security':policy([peer('pages',6400,['compute']),peer('broker',50051,['safekeeper','pageserver']),peer('pages-api',9898,['compute'])])},
        'safekeeper':{'security':policy([peer('wal',5454,['compute','pageserver','safekeeper']),peer('wal-api',7676,['compute'])])}}}
def hosts(opts):
    cluster=opts.get('colors-compute/cluster')
    if cluster is None:
        if opts.get('blue/event')!='build' and not opts.get('blue/dry-run'):raise ValueError('compute cluster unavailable')
        cluster=plan_deployment(opts,topology(opts),requirements(opts))['cluster']
    return collect([{**n,'private':True} for n in expand(topology(opts))],cluster['nodes'],'compute-0')['nodes']
def host_of(nodes,role):return next((n for n in nodes if n['role']==role),None)

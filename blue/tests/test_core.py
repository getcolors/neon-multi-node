import copy,json,re
from pathlib import Path
import pytest,yaml
from blue.runtime import ExecResult
from colors_compute.planning import plan_deployment
from colors_compute.contract import expand
from package_neon_multi_node_blue import tools,topology,validate,workflow,storage,ssh_config
@pytest.fixture
def opts():return yaml.safe_load((Path(__file__).parents[2]/'test/fixtures/colors.yml').read_text())
def observed(opts):
    return {**opts,'colors-compute/cluster':plan_deployment(opts,topology.topology(opts),topology.requirements(opts))['cluster']}
def proof_output(opts):
    nodes=[n['node_id'] for n in expand(topology.topology(opts))]
    return '\n'.join('    "msg": "WRITERS_STOPPED '+n+' PASS independent absence of Neon containers and writer processes"' for n in nodes)+'\nPLAY RECAP\n'+'\n'.join(n+' : ok=2 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0' for n in nodes)
def test_topology_and_join(opts):
    actual=observed(opts)
    assert [n['node_id'] for n in topology.hosts(actual)]==['compute-0','pageserver-0','safekeeper-0','safekeeper-1','safekeeper-2']
    actual['colors-compute/cluster']['nodes'].reverse()
    assert topology.hosts(actual)[0]['node_id']=='compute-0'
    actual['colors-compute/cluster']['nodes'].pop()
    with pytest.raises(Exception):topology.hosts(actual)
def test_role_boundaries(opts):
    r=topology.requirements(opts)
    assert r['roles']['compute']['security']['ingress'][1]['sources']==opts['postgres-sources']
    assert r['roles']['pageserver']['security']['ingress'][1]['peer_roles']==['compute']
    assert r['roles']['safekeeper']['security']['ingress'][1]['peer_roles']==['compute','pageserver','safekeeper']
def test_validation(opts):
    assert validate.state_errors(opts)==[]
    for key,value in [('neon-pg-version',16),('neon-pg-version','17'),('neon-host','bad\n.example.com'),('neon-r2-prefix','${unsafe}'),('cloudflare-proxied',True)]:
        assert validate.state_errors({**opts,key:value})
    assert validate.state_errors({**opts,'neon-r2-bucket':opts['s3-bucket']})
    assert validate.env_errors({'COLORS_PAR_PROFILE':'unsafe'})
@pytest.mark.asyncio
async def test_guard_before_read(opts,monkeypatch):
    async def forbidden(*args):raise AssertionError('state must not be read')
    monkeypatch.setattr(workflow,'read_deployment',forbidden)
    result=await workflow.start_step({**opts,'blue/event':'delete'},env={})
    assert result['blue/exit']==2 and 'protected' in result['blue/err']
@pytest.mark.asyncio
@pytest.mark.parametrize('event',['create','delete','describe','rehearse'])
async def test_dryrun_no_credentials_or_state(opts,event,monkeypatch):
    async def forbidden(*args):raise AssertionError('remote read')
    monkeypatch.setattr(workflow,'read_deployment',forbidden)
    monkeypatch.setattr(ssh_config,'preflight',lambda *_:pytest.fail('SSH read'))
    result=await workflow.start_step({**opts,'blue/event':event,'blue/dry-run':True},env={})
    assert result['blue/exit']==0
    assert result['ssh-private-key-path']=='/home/build-placeholder/.ssh/neon-multi-node-fixture'
@pytest.mark.asyncio
async def test_repeat_delete_authority(opts,monkeypatch):
    async def unreadable(*args):return {'status':'error'}
    monkeypatch.setattr(workflow,'read_deployment',unreadable)
    result=await workflow.start_step({**opts,'blue/event':'delete','compute-prevent-destroy':False},env={})
    assert result['neon-multi-node/finalize-only'] is True
    async def refused(*args):raise RuntimeError('unreadable state')
    monkeypatch.setattr(workflow,'finalize_backend',refused)
    assert (await workflow.backend_finalize_step(result))['blue/exit']==1
    async def absent(*args):return {'status':'absent'}
    monkeypatch.setattr(workflow,'finalize_backend',absent)
    assert (await workflow.backend_finalize_step(result))['blue/exit']==0
@pytest.mark.asyncio
async def test_cleanup_renders_before_exec_and_current_proof(opts,tmp_path,monkeypatch):
    opts={**observed(opts),'workdir':str(tmp_path),'blue/event':'delete'}
    output=proof_output(opts)
    async def execute(command,**kwargs):
        directory=Path(kwargs['cwd'])
        assert (directory/'cleanup.yml').exists() and (directory/'inventory.json').exists()
        assert kwargs['timeout_ms']==7200000
        return ExecResult(0,output,'')
    monkeypatch.setattr(tools.runtime,'exec',execute)
    result=await tools.run_play(opts,'cleanup.yml')
    assert result['blue/event']=='delete' and result['blue/exit']==0
    assert storage.writer_proof(result)
    assert (tmp_path/opts['profile']/'writer-stop-evidence.txt').read_text()==output
    assert not storage.writer_proof(opts)
def test_cleanup_requires_complete_checks(opts):
    opts=observed(opts);output=proof_output(opts)
    assert len(tools.cleanup_proof(opts,output))==5
    for altered in [output.replace('failed=0','failed=1'),output.replace('WRITERS_STOPPED compute-0','WRITERS_STOPPED other-0'),output.replace('    "msg":','echo "msg":')]:
        with pytest.raises(RuntimeError):tools.cleanup_proof(opts,altered)
@pytest.mark.asyncio
async def test_storage_no_proof_never_calls_tofu(opts,monkeypatch):
    async def forbidden(*args,**kwargs):pytest.fail('Terraform called without writer proof')
    monkeypatch.setattr(storage.tofu,'tofu_with_spec',forbidden)
    assert (await storage.storage_step({**opts,'blue/event':'delete'}))['blue/exit']==1
def test_credentials_stay_environment_only():
    opts={'neon-multi-node/storage-credentials':{'credentials':{'neon':{'access_key_id':'fixture','secret_access_key':'secret'}}}}
    env=storage.credential_env(opts)
    assert env['COLORS_PAR_NEON_R2_ACCESS_KEY_ID']=='fixture' and env['COLORS_PAR_NEON_S3_SECRET_ACCESS_KEY']=='secret'
    with pytest.raises(RuntimeError):storage.credential_env({})
@pytest.mark.asyncio
@pytest.mark.parametrize('exit_code',[-1,-15,1])
async def test_acceptance_nonzero_is_workflow_failure(opts,exit_code,monkeypatch):
    from blue.workflow import failed
    async def execute(*args,**kwargs):return ExecResult(exit_code,'','process failed')
    monkeypatch.setattr(tools.runtime,'exec',execute)
    result=await tools.acceptance_step({**opts,'blue/event':'create'})
    assert result['blue/exit']==1 and failed(result)

#!/usr/bin/env python3
"""Host-local Neon convergence and observable acceptance; never prints credentials."""
import json, os, pathlib, subprocess, sys, time, urllib.request
P=pathlib.Path('/etc/neon')
C={}
def run(args, **kw):
    return subprocess.run(args,check=True,text=True,capture_output=True,**kw).stdout.strip()
def write(path,body,mode=0o600,uid=0):
    path=pathlib.Path(path); data=body if isinstance(body,str) else json.dumps(body,indent=2)
    changed=not path.exists() or path.read_text()!=data
    if changed:
        tmp=path.with_suffix(path.suffix+'.new'); tmp.write_text(data); os.chmod(tmp,mode); os.chown(tmp,uid,uid); os.replace(tmp,path)
    os.chmod(path,mode); os.chown(path,uid,uid)
    return changed
def dc(*args): return run(['docker','compose','-f','/opt/neon/compose.json',*args])
def api(path,host=None):
    return json.load(urllib.request.urlopen('http://'+(host or C['pageserver'])+':9898'+path,timeout=10))
def retry(fn,timeout=180):
    end=time.time()+timeout; last=None
    while time.time()<end:
        try:
            value=fn()
            if value: return value
        except Exception as e: last=type(e).__name__
        time.sleep(2)
    raise RuntimeError('condition timed out: '+str(last))
def password(role): return (P/'secrets'/ (role+'_password')).read_text().strip()
def sql(query,role=None,pw=None,tls='require',host='127.0.0.1',expect=True,refusal=None):
    role=role or C['role']; pw=password('neon_role') if pw is None else pw
    env={'PATH':os.environ['PATH'],'PGPASSFILE':'/dev/null','PGCONNECT_TIMEOUT':'8','PGPASSWORD':pw}
    p=subprocess.run(['psql','-w','-X','-v','ON_ERROR_STOP=1',f'host={host} port=55433 dbname={C["database"]} user={role} sslmode={tls}','-Atc',query],env=env,text=True,capture_output=True,timeout=45)
    if expect and p.returncode: raise RuntimeError('SQL gate failed: '+p.stderr.replace(pw,'[redacted]')[:800] if pw else 'SQL gate failed: '+p.stderr[:800])
    if not expect and p.returncode==0: raise RuntimeError('negative SQL gate unexpectedly succeeded')
    if not expect and refusal and not any(token.lower() in p.stderr.lower() for token in refusal): raise RuntimeError('negative SQL gate failed for unexpected reason: '+p.stderr.replace(pw,'[redacted]')[:500] if pw else 'negative SQL gate failed for unexpected reason')
    return p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ''
def storage_env():
    env=os.environ.copy()
    for line in (P/'r2.env').read_text().splitlines():
        k,v=line.split('=',1); env[k]=v
    env.update(RCLONE_CONFIG_R2_TYPE='s3',RCLONE_CONFIG_R2_PROVIDER='AWS',RCLONE_CONFIG_R2_ACCESS_KEY_ID=env['AWS_ACCESS_KEY_ID'],RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=env['AWS_SECRET_ACCESS_KEY'],RCLONE_CONFIG_R2_ENDPOINT=C['endpoint'],RCLONE_CONFIG_R2_REGION=C['region'],RCLONE_CONFIG_R2_NO_CHECK_BUCKET='true')
    return env
def objects(sub): return set(run(['rclone','lsf',f'r2:{C["bucket"]}/{C["prefix"]}/{sub}/','--recursive','--files-only'],env=storage_env()).splitlines())
def render():
    image=C['image']; role=C['node_role']; services={}; common={'image':image,'restart':'unless-stopped'}
    if role=='pageserver':
        d=pathlib.Path('/opt/neon/pageserver'); d.mkdir(exist_ok=True); os.chown(d,1000,1000)
        write(d/'identity.toml','id=1\n',0o600,1000)
        remote={'endpoint':C['endpoint'],'bucket_name':C['bucket'],'bucket_region':C['region'],'prefix_in_bucket':C['prefix']+'/pageserver'}
        toml="broker_endpoint='http://127.0.0.1:50051'\npg_distrib_dir='/usr/local/'\nlisten_pg_addr='0.0.0.0:6400'\nlisten_http_addr='0.0.0.0:9898'\ncontrol_plane_api='http://127.0.0.1:6666'\ncontrol_plane_emergency_mode=true\nremote_storage={"+', '.join(k+'='+json.dumps(v) for k,v in remote.items())+'}\n'
        if write(d/'pageserver.toml',toml,0o600,1000): write(P/'recreate','yes')
        services['broker']={**common,'network_mode':'host','command':['storage_broker','--listen-addr=0.0.0.0:50051']}
        services['pageserver']={**common,'network_mode':'host','env_file':['/etc/neon/r2.env'],'volumes':['/opt/neon/pageserver:/data/.neon']}
    elif role=='safekeeper':
        d=pathlib.Path('/opt/neon/safekeeper'); d.mkdir(exist_ok=True); os.chown(d,1000,1000)
        remote='{'+', '.join(k+'='+json.dumps(v) for k,v in {'endpoint':C['endpoint'],'bucket_name':C['bucket'],'bucket_region':C['region'],'prefix_in_bucket':C['prefix']+'/safekeeper/'}.items())+'}'
        services['safekeeper']={**common,'network_mode':'host','env_file':['/etc/neon/r2.env'],'volumes':['/opt/neon/safekeeper:/data'],'entrypoint':['safekeeper'],'command':['--listen-pg=0.0.0.0:5454','--advertise-pg='+C['private_ip']+':5454','--listen-http=0.0.0.0:7676','--id='+str(C['ordinal']+1),'--broker-endpoint=http://'+C['pageserver']+':50051','-D','/data','--remote-storage='+remote]}
    else:
        secrets=P/'secrets'; secrets.mkdir(exist_ok=True); os.chmod(secrets,0o700)
        for name in ['cloud_admin','neon_role']:
            f=secrets/(name+'_password')
            if not f.exists(): write(f,run(['openssl','rand','-hex','24']))
            v=secrets/(name+'_verifier')
            if not v.exists(): write(v,run(['python3','/opt/neon/scramgen.py'],input=f.read_text().strip()+'\n'))
        spec=json.loads((P/'compute-spec.json').read_text().replace('@CLOUD_ADMIN_VERIFIER@',(secrets/'cloud_admin_verifier').read_text()).replace('@NEON_ROLE_VERIFIER@',(secrets/'neon_role_verifier').read_text()).replace('@JWKS_KID@','local').replace('@JWKS_X@','11qYAYKxCrfVS_7TyW8yJkb9qmY4Fk8THNV1ZmJw1vE'))
        # Generate deployment-specific public JWKS once; private material never leaves host.
        key=secrets/'jwks.pem'
        if not key.exists(): write(key,run(['openssl','genpkey','-algorithm','ED25519']))
        import base64
        pub=subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-outform','DER'],check=True,capture_output=True).stdout[-32:]
        spec['compute_ctl_config']['jwks']['keys'][0]['x']=base64.urlsafe_b64encode(pub).decode().rstrip('=')
        settings=spec['spec']['cluster']['settings']
        for s in settings:
            if s['name']=='neon.safekeepers': s['value']=','.join(x+':5454' for x in C['safekeepers'])
            if s['name']=='neon.pageserver_connstring': s['value']='host='+C['pageserver']+' port=6400'
        settings.append({'name':'hba_file','value':'/etc/neon/pg_hba.conf','vartype':'string'})
        spec['compute_ctl_config']['tls']={'key_path':'/etc/neon/tls/privkey.pem','cert_path':'/etc/neon/tls/fullchain.pem'}
        changed=write(P/'config.json',spec,0o400,1000)
        write(P/'pg_hba.conf','local all all trust\nhost all all 127.0.0.1/32 trust\nhost all all ::1/128 trust\nhostnossl all all 0.0.0.0/0 reject\nhostnossl all all ::/0 reject\nhostssl all all 0.0.0.0/0 scram-sha-256\nhostssl all all ::/0 scram-sha-256\n',0o444)
        services['compute']={'image':C['compute_image'],'restart':'unless-stopped','ports':['55433:55433','127.0.0.1:3080:3080'],'volumes':['/etc/neon/config.json:/var/db/postgres/configs/config.json:ro','/etc/neon/pg_hba.conf:/etc/neon/pg_hba.conf:ro','/etc/neon/tls:/etc/neon/tls:ro'],'tmpfs':['/tmp'],'environment':{'OTEL_SDK_DISABLED':'true'},'entrypoint':['/usr/local/bin/compute_ctl'],'command':['--pgdata','/var/db/postgres/compute','-C','postgresql://cloud_admin@localhost:55433/postgres','-b','/usr/local/bin/postgres','--compute-id',C['profile'],'--config','/var/db/postgres/configs/config.json']}
        if changed: write(P/'recreate','yes')
    if write('/opt/neon/compose.json',{'name':'neon','services':services},0o600): write(P/'recreate','yes'); print('CHANGED compose')
def start():
    if (P/'recreate').exists(): dc('up','-d','--force-recreate'); (P/'recreate').unlink()
    else: dc('up','-d')
def check():
    retry(lambda: sql('SELECT 1')=='1')
    witness="CREATE TABLE IF NOT EXISTS public.colors_witness (id text PRIMARY KEY, value text NOT NULL); INSERT INTO public.colors_witness VALUES ('deployment','durable') ON CONFLICT (id) DO UPDATE SET value=EXCLUDED.value; SELECT value FROM public.colors_witness WHERE id='deployment'"
    assert sql(witness)=='durable'
    sql('SELECT 1',pw='wrong-password',expect=False,refusal=['password authentication failed'])
    sql('SELECT 1',pw='',expect=False,refusal=['no password supplied'])
    sql('ALTER ROLE '+C['role']+' SUPERUSER',expect=False,refusal=['permission denied','must be superuser','Only roles with'])
    sql('SELECT 1',tls='disable',expect=False,refusal=['pg_hba.conf rejects','no pg_hba.conf entry'])
    assert sql('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()')=='t'
    target=sql('SELECT pg_current_wal_flush_lsn()',role='cloud_admin',pw=password('cloud_admin'))
    def lsn(value):
        if isinstance(value,int): return value
        high,low=value.split('/'); return (int(high,16)<<32)+int(low,16)
    for host in C['safekeepers']:
        def caught_up():
            info=json.load(urllib.request.urlopen('http://'+host+':7676/v1/tenant/'+C['tenant']+'/timeline/'+C['timeline'],timeout=10))
            return lsn(info.get('commit_lsn','0/0')) >= lsn(target)
        retry(caught_up)
    before=objects('safekeeper'); sql('SELECT pg_switch_wal()',role='cloud_admin',pw=password('cloud_admin'))
    retry(lambda: objects('safekeeper')-before,180)
    retry(lambda: objects('pageserver'),180)
    run(['/opt/neon/bootstrap.sh'])
    marker=P/'ready-marker'; write(marker,C['profile'])
    dest=f'r2:{C["bucket"]}/{C["prefix"]}/.colors-ready'
    run(['rclone','copyto',str(marker),dest],env=storage_env())
    assert run(['rclone','cat',dest],env=storage_env())==C['profile']
    print('PASS SQL witness, TLS, auth negatives, three safekeepers, fresh S3 WAL, pageserver objects')
def quorum_write(member):
    import uuid
    witness_id='quorum-'+uuid.uuid4().hex
    value=uuid.uuid4().hex
    assert sql("INSERT INTO public.colors_witness VALUES ('"+witness_id+"','"+value+"') RETURNING value")==value
    ledger=P/'rehearsal-witnesses.json'
    records=json.loads(ledger.read_text()) if ledger.exists() else []
    records.append({'id':witness_id,'value':value,'member':member})
    write(ledger,records)
    print('PASS unique acknowledged witness '+witness_id+' while '+member+' absent')
def quorum_witness():
    ledger=P/'rehearsal-witnesses.json'
    records=json.loads(ledger.read_text())
    assert records, 'no acknowledged rehearsal witnesses recorded'
    for item in records:
        assert all(c in '0123456789abcdef-' for c in item['id'].removeprefix('quorum-'))
        assert sql("SELECT value FROM public.colors_witness WHERE id='"+item['id']+"'")==item['value'], 'acknowledged outage witness missing'
    print('PASS all '+str(len(records))+' unique acknowledged outage witnesses retained')
def status():
    print(dc('ps','--format','json'))
if __name__=='__main__':
    try:
        C=json.loads((P/'deployment.json').read_text())
        cmd=sys.argv[1]
        if cmd=='render': render()
        elif cmd=='start': start()
        elif cmd=='check': check()
        elif cmd=='witness': assert sql("SELECT value FROM public.colors_witness WHERE id='deployment'")=='durable'; print('PASS retained witness')
        elif cmd=='quorum-witness': quorum_witness()
        elif cmd=='write': quorum_write(sys.argv[2] if len(sys.argv)>2 else 'unspecified-member')
        elif cmd=='no-quorum':
            try:
                sql("INSERT INTO public.colors_witness VALUES ('uncertain-quorum','possibly-committed') ON CONFLICT(id) DO UPDATE SET value=EXCLUDED.value")
            except subprocess.TimeoutExpired: print('PASS no write acknowledgement without quorum; transaction outcome uncertain until recovery')
            except RuntimeError as exc:
                if 'statement timeout' not in str(exc): raise
                print('PASS bounded write canceled without quorum; transaction outcome uncertain until recovery')
            else: raise RuntimeError('write acknowledged without quorum')
        elif cmd=='status': status()
        else: raise ValueError('unknown command')
    except Exception as e:
        print('FAIL '+type(e).__name__+': '+str(e) if not isinstance(e,subprocess.CalledProcessError) else 'FAIL subprocess (output suppressed to protect credentials)',file=sys.stderr); sys.exit(1)

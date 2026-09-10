import * as ansible from 'red/ansible';
import {stageDir} from 'red/cli';
import {scaffold,PRESERVE_JINJA_DELIMITERS,contentSpec,type Spec} from 'red/scaffold';
import * as tofu from 'red/tofu';
import {runtime} from 'red/runtime';
import type {Opts} from 'red/workflow';
import {orchestrate,plan_deployment} from 'colors-compute-red';
import {mkdirSync,writeFileSync} from 'node:fs';
import {dirname,join} from 'node:path';
import * as topology from './topology.ts';
import * as storage from './storage.ts';
import * as sshConfig from './ssh-config.ts';
import * as validate from './validate.ts';
import {resources} from './resources.ts';
export const infrastructureTool='neon-multi-node-infrastructure',dnsTool='neon-multi-node-dns',ansibleTool='neon-multi-node-ansible',ansibleLocalTool='neon-multi-node-ansible-local';
export const toolDir=(opts:Opts,tool:string)=>stageDir(opts,tool,{defaultProfile:'neon-multi-node'});
export const hosts=topology.hosts;
const spec=(path:string,target:string,data:Opts):Spec=>({template:{name:path,content:resources[path]!},target,data,opts:PRESERVE_JINJA_DELIMITERS});
export function credentialEnv(opts:Opts,...slots:string[]):Record<string,string>{
 const mapping=Object.assign({},...[...slots,'provider-backend'].map(slot=>validate.tofuEnv(opts,slot)));
 return Object.fromEntries(Object.entries(mapping).filter(([k])=>validate.s(opts[k])).map(([k,v])=>[String(v),String(opts[k])]));
}
// Cheshire layout for package-owned JSON, including insertion-ordered inventory fields.
export function pretty(value:any,indent=0):string{
 if(Array.isArray(value))return value.length?'[ '+value.map(x=>pretty(x,indent)).join(', ')+' ]':'[ ]';
 if(value!==null&&typeof value==='object'){const entries=Object.entries(value);return entries.length?'{'+'\n'+entries.map(([k,v])=>' '.repeat(indent+2)+JSON.stringify(k)+' : '+pretty(v,indent+2)).join(',\n')+'\n'+' '.repeat(indent)+'}':'{ }';}
 return JSON.stringify(value??null);
}
const sorted=(value:any):any=>Array.isArray(value)?value.map(sorted):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,sorted(value[k])])):value;
export async function infrastructureStep(opts:Opts,deps:any={}):Promise<Opts>{
 try{
  const planning=opts['red/event']==='build'||opts['red/dry-run'];
  const result:any=planning?plan_deployment(opts,topology.topology(opts),topology.requirements(opts)):await (deps.orchestrate??orchestrate)(opts,topology.topology(opts),topology.requirements(opts),{...process.env,...storage.awsEnv(opts)});
  if(planning){const root=join(opts.workdir,opts.profile,'compute');const stages:any[]=[['shared',result.documents.shared],...Object.entries(result.documents.nodes).map(([id,docs])=>['nodes/'+id,docs])];for(const[stage,docs]of stages){mkdirSync(join(root,stage),{recursive:true});for(const[name,doc]of Object.entries(docs))writeFileSync(join(root,stage,name),JSON.stringify(sorted(doc),null,2)+'\n');}writeFileSync(join(root,'http-sources.json'),pretty({origin:'explicit',checksum:'none',ranges:[]}));}
  if(!['planned','ready','destroyed'].includes(result.status))return {...opts,'red/exit':1,'red/err':'compute lifecycle refused; legacy monolithic state requires explicit migration'};
  return {...opts,'red/exit':0,...(result.cluster?{'colors-compute/cluster':result.cluster,'colors-compute/shared':result.shared}:{}),...(result.key?.private_key_path?{'ssh-private-key-path':planning?result.key.private_key_path.replace('$HOME','/home/build-placeholder'):result.key.private_key_path}:{})};
 }catch(e){return {...opts,'red/exit':1,'red/err':'compute deployment failed: '+(e as Error).message};}
}
export const dnsJson=(opts:Opts,ip:string)=>tofu.constructsJson([tofu.construct('resource','cloudflare_dns_record','neon-multi-node',{zone_id:'${data.cloudflare_zone.zone.id}',name:opts['neon-host'],type:'A',content:ip,ttl:1,proxied:Boolean(opts['cloudflare-proxied'])})]);
export async function dnsStep(opts:Opts):Promise<Opts>{const dir=toolDir(opts,dnsTool);return tofu.tofuWithSpec(opts,[spec('dns/main.tf',dir+'/main.tf',opts),contentSpec(dir+'/record.tf.json',dnsJson(opts,topology.hostOf(hosts(opts),'compute')!.ip))],{dir,env:credentialEnv(opts,'provider-dns')});}
export function ansibleLocalData(opts:Opts):Opts{return {...opts,'ssh-keygen':validate.keygen(opts),'ssh-config-identity-file':validate.keygen(opts)?sshConfig.identityFile(opts):opts['ssh-private-key-path']??''};}
export function ansibleLocalSpecs(opts:Opts):Spec[]{const dir=toolDir(opts,ansibleLocalTool),data=ansibleLocalData(opts);return ['ansible.cfg','inventory.ini','main.yml'].map(name=>spec('ansible-local/'+name,dir+'/'+name,data));}
export function sshConfigHosts(opts:Opts,list:topology.Host[]){return [{...topology.hostOf(list,'compute'),name:opts.profile},...list.map(h=>({...h,name:sshConfig.machineAlias(opts,h)}))];}
export async function ansibleLocalStep(opts:Opts):Promise<Opts>{return ansible.ansibleWithSpec(opts,{dir:toolDir(opts,ansibleLocalTool),inventory:'inventory.ini',playbooks:{create:'main.yml',delete:'main.yml'},extraVars:{host_alias:sshConfig.hostAlias(opts),ssh_hosts:sshConfigHosts(opts,hosts(opts)),block_state:opts['red/event']==='delete'?'absent':'present'}},ansibleLocalSpecs(opts));}
export function inventory(_opts:Opts,list:topology.Host[]):string{
 const children=Object.fromEntries(['compute','pageserver','safekeeper'].map(role=>[role,{hosts:Object.fromEntries(list.filter(h=>h.role===role).sort((a,b)=>a.node_id.localeCompare(b.node_id)).map(h=>[h.node_id,{ansible_host:h.ip,ansible_user:h.user,vpc_ip:h.vpc_ip,role:h.role,ordinal:h.index}]))}]));
 return pretty({all:{children}});
}
export function ansibleData(opts:Opts):Opts{const{'neon-multi-node/storage-credentials':_secret,...rest}=opts;return {...rest,domain:opts['neon-host'],'ssh-keygen':validate.keygen(opts)};}
export const ansibleFiles=['site.yml','cleanup.yml','rehearsal.yml','runtime.py','bootstrap.sh','scramgen.py','compute-spec.json','acceptance.py','renew-tls.sh','rehearse-member.yml'];
export function ansibleSpecs(opts:Opts):Spec[]{const dir=toolDir(opts,ansibleTool),data=ansibleData(opts);return [spec('ansible/ansible.cfg',dir+'/ansible.cfg',data),contentSpec(dir+'/inventory.json',inventory(opts,hosts(opts))),...ansibleFiles.map(name=>spec('ansible/'+name,dir+'/'+name,data))];}
export function cleanupProof(opts:Opts,output:string):Set<string>{
 const expected=hosts(opts).map(h=>h.node_id).sort(),recap=ansible.parseRecap(output);
 const reported=[...output.matchAll(/^\s*"msg": "WRITERS_STOPPED ([a-z0-9-]+) PASS independent absence of Neon containers and writer processes"\s*$/gm)].map(m=>m[1]!);
 const equal=(a:string[],b:string[])=>JSON.stringify([...new Set(a)].sort())===JSON.stringify([...new Set(b)].sort());
 if(expected.length!==5||!equal(expected,reported)||!equal(expected,Object.keys(recap))||!Object.values(recap).every((row:any)=>row.ok>0&&['failed','unreachable','rescued','ignored'].every(k=>row[k]===0)))throw Error('writer stop proof incomplete; storage deletion refused');
 return new Set(expected);
}
export async function runPlay(opts:Opts,playbook:string,credentials:boolean,deps:any={}):Promise<Opts>{
 if(opts['red/event']==='build')return {...scaffold(opts,ansibleSpecs(opts)),'red/exit':0};
 const rendered={...scaffold({...opts,'red/event':'build'},ansibleSpecs(opts)),'red/event':opts['red/event']};
 const env={ANSIBLE_HOST_KEY_CHECKING:'True',ANSIBLE_SSH_ARGS:'-o StrictHostKeyChecking=accept-new',...(credentials?storage.credentialEnv(opts):{})};
 const result=await(deps.exec??runtime.exec)(['ansible-playbook','-i','inventory.json',playbook],{cwd:toolDir(opts,ansibleTool),env,timeoutMs:7200000});
 if(result.exit)return {...rendered,'red/exit':1,'red/err':'Ansible failed: '+result.out+result.err};
 if(playbook==='cleanup.yml')try{const stopped=cleanupProof(opts,result.out),target=join(opts.workdir,opts.profile,'writer-stop-evidence.txt');mkdirSync(dirname(target),{recursive:true});writeFileSync(target,result.out);return {...rendered,'red/exit':0,'ansible/recap':ansible.parseRecap(result.out),'neon-multi-node/writers-stopped':stopped};}catch(e){return {...rendered,'red/exit':1,'red/err':(e as Error).message};}
 return {...rendered,'red/exit':0,'ansible/recap':ansible.parseRecap(result.out)};
}
export const ansibleStep=(opts:Opts):Promise<Opts>=>opts['red/event']==='delete'&&!opts['colors-compute/cluster']?Promise.resolve({...opts,'red/exit':0}):runPlay(opts,opts['red/event']==='delete'?'cleanup.yml':'site.yml',opts['red/event']==='create');
export const rehearsalStep=(opts:Opts)=>runPlay(opts,'rehearsal.yml',true);
export async function acceptanceStep(opts:Opts):Promise<Opts>{if(opts['red/event']==='build'||opts['red/dry-run'])return {...opts,'red/exit':0};const cfg=Object.fromEntries(['profile','neon-host','neon-role','neon-database'].map(k=>[k,opts[k]]));const result=await runtime.exec(['python3','acceptance.py',JSON.stringify(cfg)],{cwd:toolDir(opts,ansibleTool),timeoutMs:600000});return {...opts,'red/exit':result.exit===0?0:1,'red/err':result.out+result.err};}
export async function describeStep(opts:Opts):Promise<Opts>{try{for(const node of hosts(opts)){const result=await runtime.exec(['ssh','-o','BatchMode=yes',opts.profile+'-'+node.node_id,'sudo','-n','python3','/opt/neon/runtime.py','status'],{timeoutMs:60000});const rows=result.out.split(/\r?\n/).filter(x=>x.trim()).map(x=>JSON.parse(x));if(result.exit||rows.length!==(node.role==='pageserver'?2:1)||rows.some(r=>r.State!=='running'||r.Health==='unhealthy'))throw Error('container health check failed');runtime.log('PASS healthy '+node.node_id);}return {...opts,'red/exit':0};}catch{return {...opts,'red/exit':1,'red/err':'one or more role services unavailable'};}}

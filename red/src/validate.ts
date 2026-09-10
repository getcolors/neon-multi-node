import type {Opts} from 'red/workflow';
import {keyMode,plan_deployment} from 'colors-compute-red';
import * as topology from './topology.ts';
export const defaultComputeProvider=topology.defaultComputeProvider;
export const keygen=(opts:Opts)=>keyMode(opts).mode==='managed';
export const s=(value:unknown)=>value==null?'':String(value);
export const envErrors=(env:Record<string,string|undefined>)=>env.COLORS_PAR_PROFILE?['COLORS_PAR_PROFILE is forbidden; set profile in colors.yml']:[];
export const required=['profile','neon-image','neon-compute-image','neon-tenant-id','neon-timeline-id','neon-database','neon-role','neon-r2-bucket','neon-r2-region','neon-r2-endpoint','neon-r2-prefix','neon-host','cloudflare-zone'];
export function stateErrors(opts:Opts):string[]{
 const errors=required.filter(k=>!s(opts[k]).trim()).map(k=>`${k} is required`);
 if(opts['neon-pg-version']!==17)errors.push('neon-pg-version must be 17; this package supports PostgreSQL 17 only');
 if(!/(?:^|\/)compute-node-v17:/.test(s(opts['neon-compute-image'])))errors.push('neon-compute-image must identify compute-node-v17 to match neon-pg-version');
 if(opts['provider-dns']!=='cloudflare')errors.push('provider-dns must be cloudflare');
 if(opts['cloudflare-proxied']!==false)errors.push('PostgreSQL DNS must be unproxied');
 for(const k of ['neon-image','neon-compute-image'])if(!/@sha256:[0-9a-f]{64}$/.test(s(opts[k])))errors.push(k+' must be pinned by digest');
 for(const k of ['neon-tenant-id','neon-timeline-id'])if(!/^[0-9a-f]{32}$/.test(s(opts[k])))errors.push(k+' must contain 32 lowercase hex digits');
 for(const k of ['neon-role','neon-database'])if(!/^[a-z_][a-z0-9_]*$/.test(s(opts[k])))errors.push(k+' must be a SQL identifier');
 if(typeof opts['compute-prevent-destroy']!=='boolean')errors.push('compute-prevent-destroy must be boolean');
 if(opts['neon-storage-managed']!==true)errors.push('neon-storage-managed must be true');
 const patterns:Record<string,RegExp>={'neon-host':/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/,'cloudflare-zone':/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/,'neon-r2-bucket':/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/,'neon-r2-region':/^[a-z]{2}(?:-[a-z]+)+-[0-9]$/,'neon-r2-endpoint':/^https:\/\/[a-z0-9.-]+(?::[0-9]+)?$/,'neon-r2-prefix':/^[a-zA-Z0-9][a-zA-Z0-9/_-]*$/};
 for(const[k,p]of Object.entries(patterns))if(!p.test(s(opts[k])))errors.push(k+' has invalid characters or format');
 if(opts['s3-region']!==opts['neon-r2-region'])errors.push('application storage region must match backend region');
 if(opts['s3-bucket']===opts['neon-r2-bucket'])errors.push('state and application buckets must differ');
 try{plan_deployment(opts,topology.topology(opts),topology.requirements(opts));}catch(e){errors.push((e as Error).message);}
 return errors;
}
export const secretErrors=(opts:Opts,event:string)=>event==='create'&&!s(opts['cloudflare-api-token']).trim()?['COLORS_PAR_CLOUDFLARE_API_TOKEN is required']:[];
export const tofuEnv=(_opts:Opts,slot:string):Record<string,string>=>slot==='provider-dns'?{'cloudflare-api-token':'CLOUDFLARE_API_TOKEN'}:{};

import type {Opts} from 'red/workflow';
import {collect,expand,plan_deployment,source_cidrs} from 'colors-compute-red';
export const defaultComputeProvider='aws';
export const topology=(_opts:Opts)=>[{role:'compute',count:1},{role:'pageserver',count:1},{role:'safekeeper',count:3}];
export interface Host {role:string;index:number;node_id:string;name:string;ip:string;vpc_ip:string;user:string;sudoer:string;[key:string]:any}
export function requirements(opts:Opts):any {
 const ssh={id:'ssh',protocol:'tcp',from_port:22,to_port:22,sources:source_cidrs(opts,'ssh-sources','ssh-sources')};
 const peer=(id:string,port:number,peer_roles:string[])=>({id,protocol:'tcp',from_port:port,to_port:port,peer_roles});
 const policy=(rules:any[])=>({ingress:[ssh,...rules],egress:'all',private_filter:true});
 return {private:true,entry_node_id:'compute-0',security:policy([]),roles:{
 compute:{security:policy([{id:'postgres',protocol:'tcp',from_port:55433,to_port:55433,sources:source_cidrs(opts,'postgres-sources','postgres-sources')},{id:'acme',protocol:'tcp',from_port:80,to_port:80,sources:['0.0.0.0/0']}])},
 pageserver:{security:policy([peer('pages',6400,['compute']),peer('broker',50051,['safekeeper','pageserver']),peer('pages-api',9898,['compute'])])},
 safekeeper:{security:policy([peer('wal',5454,['compute','pageserver','safekeeper']),peer('wal-api',7676,['compute'])])}}};
}
export function hosts(opts:Opts):Host[]{
 let cluster=opts['colors-compute/cluster'];
 if(!cluster){if(opts['red/event']!=='build'&&!opts['red/dry-run'])throw Error('compute cluster unavailable');cluster=plan_deployment(opts,topology(opts),requirements(opts)).cluster;}
 return collect(expand(topology(opts)).map(n=>({...n,private:true})),cluster.nodes,'compute-0').nodes as Host[];
}
export const hostOf=(list:Host[],role:string)=>list.find(h=>h.role===role);

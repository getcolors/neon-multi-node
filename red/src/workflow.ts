import { readPars, parName } from "red/cli";
import * as dryRun from "red/dry-run";
import { preflight, type PreflightContext } from "red/lifecycle";
import * as progress from "red/progress";
import * as tofu from "red/tofu";
import { adviceAdd, failed, workflow, type Opts, type WireDecl } from "red/workflow";
import {read_deployment,finalize_backend} from "colors-compute-red";
import * as topology from "./topology.ts";
import * as ssh from "./ssh.ts";
import * as sshConfig from "./ssh-config.ts";
import * as storage from "./storage.ts";
import * as tools from "./tools.ts";
import * as validate from "./validate.ts";

export const defaults: Opts = {
  "provider-compute": validate.defaultComputeProvider, "provider-dns": "cloudflare",
  "provider-backend": "s3", "compute-prevent-destroy": true,
  "neon-pg-version":17,"neon-storage-managed":true,"cloudflare-proxied":false,
  workdir: ".colors",
};

export const stateEvents=['delete','rehearse','describe'];
export async function startStep(original:Opts,env:Record<string,string|undefined>=process.env,deps:any={}):Promise<Opts>{
 return preflight(original,{defaults,overlay:readPars,validators:[
  (_o,e)=>validate.envErrors(e),
  o=>validate.stateErrors(o),
  (o,_e,c)=>c.real&&['create','delete'].includes(c.event??'')&&!validate.stateErrors(o).length?validate.secretErrors(o,c.event??''):[],
  (o,_e,c)=>c.real&&c.event==='delete'&&o['compute-prevent-destroy']?['compute destruction is protected; set COLORS_PAR_COMPUTE_PREVENT_DESTROY=false to delete']:[]],
  afterValidate:async(opts,_env,c)=>{
   if(c.real&&stateEvents.includes(c.event??'')){
    const result:any=await (deps.readDeployment??read_deployment)(opts,{...env,...storage.awsEnv(opts)},undefined,topology.requirements(opts));
    if(c.event==='delete'&&opts['s3-bucket-mode']==='managed'&&['absent','destroyed','error'].includes(result.status))return {...opts,'neon-multi-node/finalize-only':true,'red/exit':0};
    if(result.status==='destroyed'&&c.event==='delete')return {...opts,'neon-multi-node/already-destroyed':true,'red/exit':0};
    if(result.status!=='present')return {...opts,'red/exit':1,'red/err':'compute state unavailable; legacy monolithic state requires explicit migration'};
    const ready={...opts,'colors-compute/cluster':result.cluster,'colors-compute/shared':result.shared??{},...(result.key?.private_key_path?{'ssh-private-key-path':result.key.private_key_path}:{}),'red/exit':0};
    return c.event==='rehearse'&&storage.managed(opts)?await storage.readCredentials(ready):ready;
   }
   if(c.real&&c.event==='create')return sshConfig.preflight(opts);
   return {...ssh.withMachineKey(opts),'red/exit':0};
  }},env);
}

export async function backendFinalizeStep(opts:Opts,deps:any={}):Promise<Opts>{
 try{const result=await (deps.finalizeBackend??finalize_backend)(opts,{...process.env,...storage.awsEnv(opts)});if(!['destroyed','absent','skipped'].includes(result.status))throw Error();return {...opts,'red/exit':0};}
 catch{return {...opts,'red/exit':1,'red/err':'managed backend finalization refused; live or unowned state remains'};}
}

export function wireFn(step: string, runOpts: Opts): WireDecl | undefined {
  switch (runOpts["red/event"]) {
    case "delete": {
      const graph: Record<string, WireDecl> = {
        "neon-multi-node/start": [startStep, "neon-multi-node/ansible"],
        "neon-multi-node/ansible": [tools.ansibleStep, "neon-multi-node/ssh-config"],
        // The `~/.ssh/config` block goes before the destroy, the opposite of
        // the keypair below. A block that outlives its hosts is stale but
        // harmless; a key that predeceases them locks the operator out of
        // machines that still exist. Both orders are deliberate; see
        // standards/ssh-config.md.
        "neon-multi-node/ssh-config": [tools.ansibleLocalStep, "neon-multi-node/dns"],
        // DNS before the compute destroy: a record pointing at a released
        // address is worse than no record.
        "neon-multi-node/dns": [tools.dnsStep, storage.managed(runOpts)?"neon-multi-node/storage":"neon-multi-node/infrastructure"],
        "neon-multi-node/storage": [storage.storageStep,"neon-multi-node/infrastructure"],
        "neon-multi-node/infrastructure": runOpts["s3-bucket-mode"]==="managed"?[tools.infrastructureStep,"neon-multi-node/backend-finalize"]:[tools.infrastructureStep],
        "neon-multi-node/backend-finalize": [backendFinalizeStep],
      };
      return graph[step];
    }
    case "rehearse": {
      const graph: Record<string, WireDecl> = {
        "neon-multi-node/start": [startStep, "neon-multi-node/rehearsal"],
        "neon-multi-node/rehearsal": [tools.rehearsalStep],
      };
      return graph[step];
    }
    case "describe": {
      const graph: Record<string, WireDecl> = {
        "neon-multi-node/start": [startStep, "neon-multi-node/describe"],
        "neon-multi-node/describe": [tools.describeStep],
      };
      return graph[step];
    }
    default: {
      const graph: Record<string, WireDecl> = {
        "neon-multi-node/start": [startStep, "neon-multi-node/infrastructure"],
        // After compute, which is where the addresses first exist, and before
        // the stage that converges the machines — the converge and the
        // acceptance both ride the aliases this stage writes.
        "neon-multi-node/infrastructure": [tools.infrastructureStep,storage.managed(runOpts)?"neon-multi-node/storage":"neon-multi-node/dns"],
        "neon-multi-node/storage": [storage.storageStep,"neon-multi-node/dns"],
        // DNS before the converge: Certbot provisions its certificate over ACME
        // on first start, and the HTTP-01 challenge needs the name to already
        // resolve to the app host.
        "neon-multi-node/dns": [tools.dnsStep, "neon-multi-node/ssh-config"],
        "neon-multi-node/ssh-config": [tools.ansibleLocalStep, "neon-multi-node/ansible"],
        "neon-multi-node/ansible": [tools.ansibleStep, "neon-multi-node/acceptance"],
        "neon-multi-node/acceptance": [tools.acceptanceStep],
      };
      return graph[step];
    }
  }
}

export function backendAdvice(tool: string) {
  return tofu.conventionalBackendAdvice({
    dir: (opts) => tools.toolDir(opts, tool),
    key: (opts) => `${opts.profile ?? ""}/${tool}.tfstate`,
  });
}

export const sideEffecting = [
  "neon-multi-node/backend-finalize", "neon-multi-node/storage",
  "neon-multi-node/infrastructure", "neon-multi-node/dns", "neon-multi-node/ssh-config",
  "neon-multi-node/ansible", "neon-multi-node/acceptance",
  "neon-multi-node/rehearsal", "neon-multi-node/describe",
];

function create() {
  let wf = workflow({ start: "neon-multi-node/start", wireFn, nextFn:(step,successors,opts)=>opts["neon-multi-node/already-destroyed"]||failed(opts)?[]:step==="neon-multi-node/start"&&opts["neon-multi-node/finalize-only"]?[["neon-multi-node/backend-finalize",opts]]:(successors??[]).map(step=>[step,opts]) });
  wf = adviceAdd(wf, "neon-multi-node/dns", "before", "neon-multi-node.workflow/backend",
    backendAdvice(tools.dnsTool));
  wf = adviceAdd(wf,"neon-multi-node/storage","before","neon-multi-node.workflow/storage-backend",backendAdvice(storage.tool));
  return dryRun.advise(progress.advise(wf), sideEffecting);
}

export const neonMultiNodeWorkflow = create();

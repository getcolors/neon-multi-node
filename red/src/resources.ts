import r0 from "../resources/tools/ansible/acceptance.py" with { type: "text" };
import r1 from "../resources/tools/ansible/ansible.cfg" with { type: "text" };
import r2 from "../resources/tools/ansible/bootstrap.sh" with { type: "text" };
import r3 from "../resources/tools/ansible/cleanup.yml" with { type: "text" };
import r4 from "../resources/tools/ansible/compute-spec.json" with { type: "text" };
import r5 from "../resources/tools/ansible/rehearsal.yml" with { type: "text" };
import r6 from "../resources/tools/ansible/rehearse-member.yml" with { type: "text" };
import r7 from "../resources/tools/ansible/renew-tls.sh" with { type: "text" };
import r8 from "../resources/tools/ansible/runtime.py" with { type: "text" };
import r9 from "../resources/tools/ansible/scramgen.py" with { type: "text" };
import r10 from "../resources/tools/ansible/site.yml" with { type: "text" };
import r11 from "../resources/tools/ansible-local/ansible.cfg" with { type: "text" };
import r12 from "../resources/tools/ansible-local/inventory.ini" with { type: "text" };
import r13 from "../resources/tools/ansible-local/main.yml" with { type: "text" };
import r14 from "../resources/tools/dns/main.tf" with { type: "text" };
import r15 from "../resources/tools/storage/main.tf" with { type: "text" };
export const resources:Record<string,string>={
  "ansible/acceptance.py":r0 as unknown as string,
  "ansible/ansible.cfg":r1 as unknown as string,
  "ansible/bootstrap.sh":r2 as unknown as string,
  "ansible/cleanup.yml":r3 as unknown as string,
  "ansible/compute-spec.json":r4 as unknown as string,
  "ansible/rehearsal.yml":r5 as unknown as string,
  "ansible/rehearse-member.yml":r6 as unknown as string,
  "ansible/renew-tls.sh":r7 as unknown as string,
  "ansible/runtime.py":r8 as unknown as string,
  "ansible/scramgen.py":r9 as unknown as string,
  "ansible/site.yml":r10 as unknown as string,
  "ansible-local/ansible.cfg":r11 as unknown as string,
  "ansible-local/inventory.ini":r12 as unknown as string,
  "ansible-local/main.yml":r13 as unknown as string,
  "dns/main.tf":r14 as unknown as string,
  "storage/main.tf":r15 as unknown as string,
};

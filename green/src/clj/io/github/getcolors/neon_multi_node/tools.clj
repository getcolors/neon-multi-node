(ns io.github.getcolors.neon-multi-node.tools
  (:require [cheshire.core :as json]
            [clojure.string :as str]
            [clojure.java.io :as io]
            [green.ansible :as ansible]
            [green.cli :as green-cli]
            [green.process :as process]
            [green.scaffold :as sc]
            [green.tofu :as tofu]
            [green.workflow :as wf]
            [io.github.getcolors.neon-multi-node.ssh-config :as ssh-config]
            [io.github.getcolors.neon-multi-node.topology :as topology]
            [io.github.getcolors.neon-multi-node.validate :as validate]
            [io.github.getcolors.neon-multi-node.storage :as storage]
            [io.github.getcolors.compute-deployment-request :as deployment]
            [io.github.getcolors.compute-planning :as planning]
            [io.github.getcolors.compute-orchestration :as orchestration]))

(def infrastructure-tool "neon-multi-node-infrastructure")
(def dns-tool "neon-multi-node-dns")
(def ansible-tool "neon-multi-node-ansible")
(def ansible-local-tool "neon-multi-node-ansible-local")
(def root "io.github.getcolors.neon_multi_node.tools")

 ;; The pinned Neon dependency supplies generic Ansible configuration resources.
;; Multi-node application templates are owned by this package.
(def neon-root "io.github.getcolors.neon.tools")
(def template-opts sc/preserve-jinja-delimiters)

(defn tool-dir [opts tool] (green-cli/stage-dir opts tool {:default-profile "neon-multi-node"}))
(defn template [path file] (keyword (str root "." path) file))
(defn neon-template [path file] (keyword (str neon-root "." path) file))
(defn spec [source target data] {:template source :target target :data data :opts template-opts})
(defn raw-spec [target content] (sc/content-spec target content))

(defn credential-env [opts & slots]
  (not-empty
   (into {} (keep (fn [[k env-var]]
                    (when-let [v (not-empty (str (get opts k)))] [env-var v])))
         (apply merge (map #(validate/tofu-env opts %) (conj (vec slots) :provider-backend))))))
(defn backend-credential-env [opts] (credential-env opts))

;; ------------------------------------------------------------- compute output

(defn hosts
  "Host facts from the validated library join, with offline planning for build."
  [opts]
  (topology/hosts opts))

;; ---------------------------------------------------------------- compute

(defn http-sources [_] {:source :explicit :ranges []})
(defn ranges-checksum [_] "none")

(defn- compute-json [value indent]
  (let [padding #(apply str (repeat % " "))]
    (cond
      (map? value) (if (empty? value) "{}"
                      (str "{\n" (str/join ",\n" (for [[key item] (sort-by key value)]
                                                       (str (padding (+ indent 2)) (json/generate-string key) ": " (compute-json item (+ indent 2)))))
                           "\n" (padding indent) "}"))
      (sequential? value) (if (empty? value) "[]"
                              (str "[\n" (str/join ",\n" (map #(str (padding (+ indent 2)) (compute-json % (+ indent 2))) value)) "\n" (padding indent) "]"))
      :else (json/generate-string value))))

(defn infrastructure-step [opts]
  (let [{:keys [source ranges]} (http-sources opts)]
    (if (and (= :create (:green/event opts)) (not (:green/dry-run opts)) (= source :fallback))
      (assoc opts :green/exit 1 :green/err "Cloudflare ingress ranges unavailable; refusing stale fallback")
      (try
        (let [requirements (topology/requirements opts)
              planning? (or (= :build (:green/event opts)) (:green/dry-run opts))
              result (if planning? (planning/plan-deployment opts (topology/topology opts) requirements)
                         (orchestration/orchestrate opts (topology/topology opts) requirements (merge (into {} (System/getenv)) (storage/aws-env opts))))]
          (when planning?
            (let [root (str (:workdir opts) "/" (:profile opts) "/compute")
                  stages (cons ["shared" (get-in result [:documents :shared])] (map (fn [[id docs]] [(str "nodes/" id) docs]) (get-in result [:documents :nodes])))]
              (doseq [[stage docs] stages [filename document] docs]
                (let [file (io/file root stage filename)] (io/make-parents file) (spit file (str (compute-json document 0) "\n"))))
              (spit (io/file root "http-sources.json") (json/generate-string {:origin (name source) :checksum (ranges-checksum ranges) :ranges ranges} {:pretty true}))))
          (if-not (contains? #{"planned" "ready" "destroyed"} (:status result))
            (assoc opts :green/exit 1 :green/err "compute lifecycle refused; legacy monolithic state requires explicit migration")
            (cond-> (assoc opts :green/exit 0)
              (:cluster result) (assoc :colors-compute/cluster (:cluster result) :colors-compute/shared (:shared result))
              (get-in result [:key :private_key_path]) (assoc :ssh-private-key-path (if planning? (str/replace (get-in result [:key :private_key_path]) "$HOME" "/home/build-placeholder") (get-in result [:key :private_key_path]))))))
        (catch Exception e (assoc opts :green/exit 1 :green/err (str "compute deployment failed: " (ex-message e))))))))

(defn zone-id [] "${data.cloudflare_zone.zone.id}")

(defn dns-json
  "One DNS-only A record pointing at the compute host; TTL 1 means automatic."
  [opts app-ip]
  (tofu/constructs-json
   [(tofu/construct :resource :cloudflare_dns_record :neon-multi-node
                    {:zone_id (zone-id)
                     :name (:neon-host opts)
                     :type "A"
                     :content app-ip
                     :ttl 1
                     :proxied (boolean (:cloudflare-proxied opts))})]))

(defn dns-step [opts]
  (let [dir (tool-dir opts dns-tool)
        app (topology/host-of (hosts opts) :compute)
        specs [(spec (template "dns" "main.tf") (str dir "/main.tf") opts)
               (raw-spec (str dir "/record.tf.json") (dns-json opts (:ip app)))]]
    (tofu/tofu-with-spec opts specs {:dir dir :env (credential-env opts :provider-dns)})))

;; ------------------------------------------------------- ssh config (local)

(defn ansible-local-data
  "Only what a `build` genuinely knows. Addresses are run-time facts and reach
  the play as extra-vars instead, so the rendered playbook carries no IP and
  is identical on every workstation (SSH Config Standard §6)."
  [opts]
  (assoc opts
         :ssh-keygen (validate/keygen? opts)
         :ssh-config-identity-file (if (validate/keygen? opts) (ssh-config/identity-file opts) (get opts :ssh-private-key-path ""))))

(defn ansible-local-specs [opts]
  (let [dir (tool-dir opts ansible-local-tool) data (ansible-local-data opts)]
    ;; ansible.cfg and the inventory are the dependency's, unchanged; the play
    ;; is this package's own because it writes six stanzas, not one.
    [(spec (neon-template "ansible-local" "ansible.cfg") (str dir "/ansible.cfg") data)
     (spec (neon-template "ansible-local" "inventory.ini") (str dir "/inventory.ini") data)
     (spec (template "ansible-local" "main.yml") (str dir "/main.yml") data)]))

(defn ssh-config-hosts
  "The stanzas the managed block carries: the bare profile reaching the compute
  host (the topology entry), then one per machine (Compute Cluster Standard §6)."
  [opts hosts*]
  (into [(assoc (topology/host-of hosts* :compute) :name (:profile opts))] (map #(assoc % :name (ssh-config/machine-alias opts %)) hosts*)))

(defn ansible-local-step
  "Write or remove the `~/.ssh/config` block. The same playbook serves both
  events; `block_state` is what distinguishes them."
  [opts]
  (let [dir (tool-dir opts ansible-local-tool)
        delete? (= :delete (:green/event opts))]
    (ansible/ansible-with-spec opts
      {:dir dir :inventory "inventory.ini"
       :playbooks {:create "main.yml" :delete "main.yml"}
       :extra-vars {:host_alias (ssh-config/host-alias opts)
                    :ssh_hosts (ssh-config-hosts opts (hosts opts))
                    :block_state (if delete? "absent" "present")}}
      (ansible-local-specs opts))))


(defn inventory [opts nodes]
 (json/generate-string
 {:all {:children (into (sorted-map)
 (for [role ["compute" "pageserver" "safekeeper"]]
 [role {:hosts (into (sorted-map)
 (for [h nodes :when (= role (:role h))]
 [(:node_id h) {:ansible_host (:ip h) :ansible_user (:user h) :vpc_ip (:vpc_ip h) :role role :ordinal (:index h)}]))}]))}} {:pretty true}))
(defn ansible-data [opts]
 (-> opts (dissoc :neon-multi-node/storage-credentials) (assoc :domain (:neon-host opts) :ssh-keygen (validate/keygen? opts))))
(def ansible-files ["site.yml" "cleanup.yml" "rehearsal.yml" "runtime.py" "bootstrap.sh" "scramgen.py" "compute-spec.json" "acceptance.py" "renew-tls.sh" "rehearse-member.yml"])
(defn ansible-specs [opts]
 (let [dir (tool-dir opts ansible-tool) data (ansible-data opts)]
 (into [(spec (neon-template "ansible" "ansible.cfg") (str dir "/ansible.cfg") data)
 (raw-spec (str dir "/inventory.json") (inventory opts (hosts opts)))]
 (map #(spec (template "ansible" %) (str dir "/" %) data) ansible-files))))
(defn cleanup-proof [opts output]
 (let [expected (set (map :node_id (hosts opts)))
       recap (ansible/parse-recap output)
       reported (set (map second (re-seq #"(?m)^\s*\"msg\": \"WRITERS_STOPPED ([a-z0-9-]+) PASS independent absence of Neon containers and writer processes\"\s*$" output)))]
  (when-not (and (= 5 (count expected)) (= expected reported) (= expected (set (keys recap)))
    (every? (fn [[_ counters]] (and (pos? (:ok counters)) (every? #(zero? (get counters % -1)) [:failed :unreachable :rescued :ignored]))) recap))
   (throw (ex-info "writer stop proof incomplete; storage deletion refused" {})))
  expected))

(defn run-play [opts playbook credentials?]
 (let [dir (tool-dir opts ansible-tool)]
 (if (= :build (:green/event opts))
 (assoc (sc/scaffold opts (ansible-specs opts)) :green/exit 0)
 (let [rendered (sc/scaffold opts (ansible-specs opts))
 env (merge {"ANSIBLE_HOST_KEY_CHECKING" "True" "ANSIBLE_SSH_ARGS" "-o StrictHostKeyChecking=accept-new"}
 (when credentials? (storage/credential-env opts)))
 result (process/run-with-timeout ["ansible-playbook" "-i" "inventory.json" playbook] {:dir dir :extra-env env} 7200000)]
 (if (zero? (:exit result))
 (if (= playbook "cleanup.yml")
 (try
  (let [stopped (cleanup-proof opts (:out result))
        target (io/file (:workdir opts) (:profile opts) "writer-stop-evidence.txt")]
   (io/make-parents target)
   (spit target (:out result))
   (assoc rendered :green/exit 0 :ansible/recap (ansible/parse-recap (:out result)) :neon-multi-node/writers-stopped stopped))
  (catch Exception e (assoc rendered :green/exit 1 :green/err (ex-message e))))
 (assoc rendered :green/exit 0 :ansible/recap (ansible/parse-recap (:out result))))
 (assoc rendered :green/exit 1 :green/err (str "Ansible failed: " (:out result) (:err result))))))))
(defn ansible-step [opts]
 (if (and (= :delete (:green/event opts)) (nil? (:colors-compute/cluster opts)))
 (assoc opts :green/exit 0)
 (run-play opts (if (= :delete (:green/event opts)) "cleanup.yml" "site.yml") (= :create (:green/event opts)))))
(defn rehearsal-step [opts] (run-play opts "rehearsal.yml" true))
(defn acceptance-step [opts]
 (if (or (= :build (:green/event opts)) (:green/dry-run opts)) (assoc opts :green/exit 0)
 (let [cfg (select-keys opts [:profile :neon-host :neon-role :neon-database])
 r (process/run-with-timeout ["python3" "acceptance.py" (json/generate-string cfg)] {:dir (tool-dir opts ansible-tool)} 600000)]
 (assoc opts :green/exit (:exit r) :green/err (str (:out r) (:err r))))))
(defn describe-step [opts]
 (try
 (doseq [node (hosts opts)]
 (let [alias (str (:profile opts) "-" (:node_id node))
 r (process/run ["ssh" "-o" "BatchMode=yes" alias "sudo" "-n" "python3" "/opt/neon/runtime.py" "status"] {})
 rows (map #(json/parse-string % true) (remove str/blank? (str/split-lines (:out r))))
 expected (if (= "pageserver" (:role node)) 2 1)]
 (when-not (and (zero? (:exit r)) (= expected (count rows)) (every? #(and (= "running" (:State %)) (not= "unhealthy" (:Health %))) rows))
 (throw (ex-info (str "unhealthy role: " (:node_id node)) {})))
 (println "PASS healthy" (:node_id node))))
 (assoc opts :green/exit 0)
 (catch Exception e (assoc opts :green/exit 1 :green/err (ex-message e)))))

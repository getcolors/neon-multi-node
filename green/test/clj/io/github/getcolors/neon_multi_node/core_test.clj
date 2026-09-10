(ns io.github.getcolors.neon-multi-node.core-test
 (:require [clojure.test :refer [deftest is]] [clojure.edn :as edn]
 [io.github.getcolors.compute :as compute]
 [io.github.getcolors.neon-multi-node.topology :as topology]
 [io.github.getcolors.neon-multi-node.storage :as storage]
 [io.github.getcolors.neon-multi-node.workflow :as workflow]))
(deftest stable-role-identities
 (is (= ["compute-0" "pageserver-0" "safekeeper-0" "safekeeper-1" "safekeeper-2"]
 (mapv :node_id (compute/expand (topology/topology {})))))
 (is (thrown? Exception (topology/hosts {}))))
(deftest private-peer-rules
 (let [r (topology/requirements {:ssh-sources ["192.0.2.1/32"] :postgres-sources ["192.0.2.1/32"]})]
 (is (= "compute-0" (:entry_node_id r)))
 (is (= ["compute" "pageserver" "safekeeper"] (get-in r [:roles :safekeeper :security :ingress 1 :peer_roles])))
 (is (= ["compute"] (get-in r [:roles :pageserver :security :ingress 1 :peer_roles])))))
(deftest nested-secret-output
 (let [env (storage/credential-env {:neon-multi-node/storage-credentials {:credentials {"neon" {"access_key_id" "fixture-id" "secret_access_key" "fixture-secret"}}}})]
 (is (= "fixture-id" (get env "COLORS_PAR_NEON_R2_ACCESS_KEY_ID")))
 (is (= "fixture-secret" (get env "COLORS_PAR_NEON_S3_SECRET_ACCESS_KEY")))))
(deftest delete-order
 (let [opts {:green/event :delete :neon-storage-managed true :s3-bucket-mode "managed"}]
 (is (= :neon-multi-node/ssh-config (second (workflow/wire-fn :neon-multi-node/ansible opts))))
 (is (= :neon-multi-node/storage (second (workflow/wire-fn :neon-multi-node/dns opts))))
 (is (= :neon-multi-node/infrastructure (second (workflow/wire-fn :neon-multi-node/storage opts))))
 (is (= :neon-multi-node/backend-finalize (second (workflow/wire-fn :neon-multi-node/infrastructure opts))))))

(require '[clj-yaml.core :as yaml]
         '[clojure.walk :as walk]
         '[io.github.getcolors.compute-planning :as planning]
         '[io.github.getcolors.compute-inspection :as inspection]
         '[io.github.getcolors.neon-multi-node.validate :as validate]
         '[io.github.getcolors.neon-multi-node.ssh-config :as ssh-config]
         '[io.github.getcolors.compute-managed-backend :as managed-backend])
(defn fixture []
 (walk/postwalk (fn [x] (if (and (sequential? x) (not (vector? x))) (vec x) x))
  (yaml/parse-string (slurp "../test/fixtures/colors.yml"))))
(deftest guard-precedes-state-and-mutation
 (let [called (atom false)]
 (with-redefs [inspection/read-deployment (fn [& _] (reset! called true) (throw (Exception. "must not inspect protected delete")))]
 (let [r (workflow/start-step (assoc (fixture) :green/event :delete) {})]
 (is (= 2 (:green/exit r)))
 (is (re-find #"destruction is protected" (:green/err r)))
 (is (false? @called))))))
(deftest safe-defaults-and-secret-boundaries
 (is (true? (:compute-prevent-destroy workflow/defaults)))
 (is (false? (:cloudflare-proxied workflow/defaults)))
 (is (true? (:neon-storage-managed workflow/defaults)))
 (is (seq (validate/env-errors {"COLORS_PAR_PROFILE" "other"})))
 (is (seq (validate/secret-errors (fixture) :create)))
 (is (nil? (validate/secret-errors (fixture) :delete)))
 (is (thrown? Exception (storage/credential-env {:neon-multi-node/storage-credentials {:credentials {}}}))))
(deftest dry-run-never-reads-state-or-local-ssh
 (with-redefs [inspection/read-deployment (fn [& _] (throw (Exception. "forbidden remote read")))
               ssh-config/preflight! (fn [& _] (throw (Exception. "forbidden SSH read")))]
 (doseq [event [:create :delete :rehearse :describe]]
 (let [r (workflow/start-step (assoc (fixture) :green/event event :green/dry-run true) {})]
 (is (= 0 (:green/exit r)) (:green/err r))
 (is (= "/home/build-placeholder/.ssh/neon-multi-node-fixture" (:ssh-private-key-path r)))))))
(deftest join-refuses-incomplete-or-duplicated-inventory
 (let [opts (fixture) cluster (:cluster (planning/plan-deployment opts (topology/topology opts) (topology/requirements opts)))
 nodes (:nodes cluster)]
 (is (= 5 (count (topology/hosts (assoc opts :colors-compute/cluster cluster)))))
 (is (thrown? Exception (topology/hosts (assoc opts :colors-compute/cluster (assoc cluster :nodes (vec (rest nodes)))))))
 (is (thrown? Exception (topology/hosts (assoc opts :colors-compute/cluster (assoc cluster :nodes (conj nodes (first nodes)))))))
 (is (= (mapv :node_id nodes) (mapv :node_id (topology/hosts (assoc opts :colors-compute/cluster (assoc cluster :nodes (vec (reverse nodes))))))))))
(deftest input-interpolation-and-bucket-boundaries
 (doseq [[k value] [[:neon-host "bad.example.com\nINJECT"] [:neon-r2-prefix "${secret}"] [:neon-r2-endpoint "https://example.com/\"secret"] [:cloudflare-proxied true]]]
 (is (seq (validate/state-errors (assoc (fixture) k value)))))
 (is (seq (validate/state-errors (assoc (fixture) :neon-r2-bucket (:s3-bucket (fixture)))))))
(deftest unreadable-state-never-becomes-absent
 (with-redefs [inspection/read-deployment (fn [& _] {:status "error"})
               managed-backend/finalize-backend! (fn [& _] (throw (Exception. "access denied")))]
 (let [r (workflow/start-step (assoc (fixture) :green/event :delete :compute-prevent-destroy false) {})]
 (is (= 0 (:green/exit r)))
 (is (true? (:neon-multi-node/finalize-only r)))
 (is (nil? (:neon-multi-node/already-destroyed r)))
 (is (= 1 (:green/exit (workflow/backend-finalize-step r))))))
 (doseq [status ["absent" "destroyed"]]
 (with-redefs [inspection/read-deployment (fn [& _] {:status status})]
 (let [r (workflow/start-step (assoc (fixture) :green/event :delete :compute-prevent-destroy false) {})]
 (is (= 0 (:green/exit r)))
 (is (true? (:neon-multi-node/finalize-only r)))))))

(deftest postgres-major-contract
 (is (= 17 (:neon-pg-version workflow/defaults)))
 (is (empty? (validate/state-errors (fixture))))
 (doseq [major [nil 16 18 "17"]]
  (is (some #(re-find #"neon-pg-version must be 17" %) (validate/state-errors (assoc (fixture) :neon-pg-version major)))))
 (is (some #(re-find #"compute-node-v17" %) (validate/state-errors (assoc (fixture) :neon-compute-image "ghcr.io/neondatabase/compute-node-v16:release@sha256:166022a72bf9983eba96d061d794f4740edbd4c3301e66202c1180acce9a323c"))))
 (is (= 0 (:green/exit (workflow/start-step (assoc (dissoc (fixture) :neon-pg-version) :green/event :create :green/dry-run true) {})))))
(require '[io.github.getcolors.neon-multi-node.tools :as tools]
         '[clojure.string :as str]
         '[green.tofu :as tofu])
(deftest current-run-writer-proof
 (let [opts (fixture)
       nodes (mapv :node_id (compute/expand (topology/topology opts)))
       cluster (:cluster (planning/plan-deployment opts (topology/topology opts) (topology/requirements opts)))
       opts (assoc opts :colors-compute/cluster cluster)
       output (str (str/join "\n" (map #(str "    \"msg\": \"WRITERS_STOPPED " % " PASS independent absence of Neon containers and writer processes\"") nodes))
                   "\nPLAY RECAP\n"
                   (str/join "\n" (map #(str % " : ok=2 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0") nodes)))]
  (is (= (set nodes) (tools/cleanup-proof opts output)))
  (is (thrown? Exception (tools/cleanup-proof opts (str/replace output "WRITERS_STOPPED compute-0" "WRITERS_STOPPED unknown-0"))))
  (is (thrown? Exception (tools/cleanup-proof opts (str/replace output "failed=0" "failed=1"))))
  (is (thrown? Exception (tools/cleanup-proof opts (str/replace output "    \"msg\":" "echo \"msg\":"))))
  (is (false? (storage/writer-proof? opts)))
  (is (false? (storage/writer-proof? (assoc opts :neon-multi-node/writers-stopped #{"compute-0"}))))
  (is (true? (storage/writer-proof? (assoc opts :neon-multi-node/writers-stopped (set nodes)))))
  (let [called (atom false)]
   (with-redefs [tofu/tofu-with-spec (fn [& _] (reset! called true) {:green/exit 0})]
    (is (= 1 (:green/exit (storage/step (assoc opts :green/event :delete)))))
    (is (false? @called))))))

(require '[clojure.java.io :as io]
         '[cheshire.core :as json]
         '[green.process :as process])
(deftest delete-materializes-playbook-before-execution-and-keeps-delete-semantics
 (let [tmp (.toFile (java.nio.file.Files/createTempDirectory "neon-delete-render-" (make-array java.nio.file.attribute.FileAttribute 0)))
       base (assoc (fixture) :green/event :delete :workdir (.getPath tmp))
       cluster (:cluster (planning/plan-deployment base (topology/topology base) (topology/requirements base)))
       opts (assoc base :colors-compute/cluster cluster)
       nodes (mapv :node_id (:nodes cluster))
       output (str (str/join "\n" (map #(str "    \"msg\": \"WRITERS_STOPPED " % " PASS independent absence of Neon containers and writer processes\"") nodes))
                   "\nPLAY RECAP\n"
                   (str/join "\n" (map #(str % " : ok=2 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0") nodes)))
       calls (atom 0)]
  (try
   (with-redefs [process/run-with-timeout
                 (fn [command run-opts _]
                  (swap! calls inc)
                  (is (= ["ansible-playbook" "-i" "inventory.json" "cleanup.yml"] command))
                  (is (.isFile (io/file (:dir run-opts) "cleanup.yml")))
                  (is (str/includes? (slurp (io/file (:dir run-opts) "cleanup.yml")) "WRITERS_STOPPED"))
                  (let [inventory (json/parse-string (slurp (io/file (:dir run-opts) "inventory.json")) true)]
                   (is (= 5 (reduce + (map #(count (:hosts %)) (vals (get-in inventory [:all :children])))))))
                  {:exit 0 :out output :err ""})]
    (let [result (tools/run-play opts "cleanup.yml" false)]
     (is (= 1 @calls))
     (is (= 0 (:green/exit result)))
     (is (= :delete (:green/event result)))
     (is (storage/writer-proof? result))
     (is (= output (slurp (io/file tmp (:profile opts) "writer-stop-evidence.txt"))))))
   (with-redefs [process/run-with-timeout (fn [& _] {:exit 0 :out "PLAY RECAP\n" :err ""})]
    (let [result (tools/run-play opts "cleanup.yml" false)]
     (is (= 1 (:green/exit result)))
     (is (= :delete (:green/event result)))
     (is (not (storage/writer-proof? result)))))
   (finally (doseq [file (reverse (file-seq tmp))] (io/delete-file file true))))))

(deftest finalized-managed-backend-routes-to-authoritative-finalizer-without-preflight-mutation
 (let [calls (atom 0)]
  (with-redefs [inspection/read-deployment (fn [& _] {:status "error"})
                managed-backend/finalize-backend! (fn [& _] (swap! calls inc) {:status "absent"})]
   (let [result (workflow/start-step (assoc (fixture) :green/event :delete :compute-prevent-destroy false) {})]
    (is (zero? @calls))
    (is (= 0 (:green/exit result)))
    (is (true? (:neon-multi-node/finalize-only result)))
    (is (nil? (:neon-multi-node/already-destroyed result)))
    (is (= 0 (:green/exit (workflow/backend-finalize-step result))))
    (is (= 1 @calls)))))
 (doseq [refusal ["access denied" "ownership mismatch" "compute must retire" "live state remains"]]
  (with-redefs [inspection/read-deployment (fn [& _] {:status "error"})
                managed-backend/finalize-backend! (fn [& _] (throw (Exception. refusal)))]
   (let [result (workflow/start-step (assoc (fixture) :green/event :delete :compute-prevent-destroy false) {})]
    (is (= 1 (:green/exit (workflow/backend-finalize-step result))))
    (is (not (:neon-multi-node/already-destroyed result))))))
 (doseq [extra [{:s3-bucket-mode "external" :green/event :delete}
               {:green/event :rehearse} {:green/event :describe}]]
  (with-redefs [inspection/read-deployment (fn [& _] {:status "error"})
                managed-backend/finalize-backend! (fn [& _] (throw (Exception. "must not finalize")))]
   (let [result (workflow/start-step (merge (fixture) {:compute-prevent-destroy false} extra) {})]
    (is (= 1 (:green/exit result)))
    (is (nil? (:neon-multi-node/finalize-only result))))))
 (with-redefs [inspection/read-deployment (fn [& _] (throw (Exception. "guard must prevent inspection")))
               managed-backend/finalize-backend! (fn [& _] (throw (Exception. "guard must prevent finalization")))]
  (is (= 2 (:green/exit (workflow/start-step (assoc (fixture) :green/event :delete) {}))))))

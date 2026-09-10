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
         '[io.github.getcolors.neon-multi-node.ssh-config :as ssh-config])
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
 (with-redefs [inspection/read-deployment (fn [& _] {:status "error"})]
 (let [r (workflow/start-step (assoc (fixture) :green/event :delete :compute-prevent-destroy false) {})]
 (is (= 1 (:green/exit r)))
 (is (nil? (:neon-multi-node/finalize-only r)))))
 (doseq [status ["absent" "destroyed"]]
 (with-redefs [inspection/read-deployment (fn [& _] {:status status})]
 (let [r (workflow/start-step (assoc (fixture) :green/event :delete :compute-prevent-destroy false) {})]
 (is (= 0 (:green/exit r)))
 (is (true? (:neon-multi-node/finalize-only r)))))))

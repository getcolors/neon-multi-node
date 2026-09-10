(ns io.github.getcolors.neon-multi-node.topology
 (:require [io.github.getcolors.compute :as library]
 [io.github.getcolors.compute-planning :as planning]
 [io.github.getcolors.compute-deployment-request :as deployment]))
(def default-compute-provider "aws")
(defn topology [_] [{:role "compute" :count 1} {:role "pageserver" :count 1} {:role "safekeeper" :count 3}])
(defn requirements [opts]
 (let [ssh {:id "ssh" :protocol "tcp" :from_port 22 :to_port 22 :sources (deployment/source-cidrs opts "ssh-sources" "ssh-sources")}
 peer (fn [id port roles] {:id id :protocol "tcp" :from_port port :to_port port :peer_roles roles})
 policy (fn [rules] {:ingress (into [ssh] rules) :egress "all" :private_filter true})]
 {:private true :entry_node_id "compute-0" :security (policy []) :roles
 {:compute {:security (policy [{:id "postgres" :protocol "tcp" :from_port 55433 :to_port 55433 :sources (deployment/source-cidrs opts "postgres-sources" "postgres-sources")} {:id "acme" :protocol "tcp" :from_port 80 :to_port 80 :sources ["0.0.0.0/0"]}])}
 :pageserver {:security (policy [(peer "pages" 6400 ["compute"]) (peer "broker" 50051 ["safekeeper" "pageserver"]) (peer "pages-api" 9898 ["compute"])])}
 :safekeeper {:security (policy [(peer "wal" 5454 ["compute" "pageserver" "safekeeper"]) (peer "wal-api" 7676 ["compute"])])}}}))
(defn hosts [opts]
 (let [cluster (or (:colors-compute/cluster opts)
 (when (or (= :build (:green/event opts)) (:green/dry-run opts)) (:cluster (planning/plan-deployment opts (topology opts) (requirements opts))))) ]
 (when-not cluster (throw (ex-info "compute cluster unavailable" {})))
 (:nodes (library/collect (mapv #(assoc % :private true) (library/expand (topology opts))) (:nodes cluster) "compute-0"))))
(defn host-of [hosts role] (first (filter #(= (name role) (:role %)) hosts)))

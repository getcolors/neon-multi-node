(ns io.github.getcolors.neon-multi-node.validate
 (:require [clojure.string :as str] [io.github.getcolors.compute-planning :as planning]
 [io.github.getcolors.compute-ssh :as ssh] [io.github.getcolors.neon-multi-node.topology :as topology]))
(def default-compute-provider topology/default-compute-provider)
(defn keygen? [opts] (= "managed" (:mode (ssh/mode opts))))
(defn env-errors [env] (when (seq (get env "COLORS_PAR_PROFILE")) ["COLORS_PAR_PROFILE is forbidden; set profile in colors.yml"]))
(def required [:profile :neon-image :neon-compute-image :neon-tenant-id :neon-timeline-id :neon-database :neon-role :neon-r2-bucket :neon-r2-region :neon-r2-endpoint :neon-r2-prefix :neon-host :cloudflare-zone])
(defn state-errors [opts]
 (vec (concat (for [k required :when (str/blank? (str (get opts k)))] (str k " is required"))
 (when-not (= "cloudflare" (:provider-dns opts)) ["provider-dns must be cloudflare"])
 (when-not (false? (:cloudflare-proxied opts)) ["PostgreSQL DNS must be unproxied"])
 (for [k [:neon-image :neon-compute-image] :when (not (re-find #"@sha256:[0-9a-f]{64}$" (str (get opts k))))] (str k " must be pinned by digest"))
 (for [k [:neon-tenant-id :neon-timeline-id] :when (not (re-matches #"[0-9a-f]{32}" (str (get opts k))))] (str k " must contain 32 lowercase hex digits"))
 (for [k [:neon-role :neon-database] :when (not (re-matches #"[a-z_][a-z0-9_]*" (str (get opts k))))] (str k " must be a SQL identifier"))
 (when-not (boolean? (:compute-prevent-destroy opts)) ["compute-prevent-destroy must be boolean"])
 (when-not (true? (:neon-storage-managed opts)) ["neon-storage-managed must be true"])
 (for [[k pattern] [[:neon-host #"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}"] [:cloudflare-zone #"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}"] [:neon-r2-bucket #"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"] [:neon-r2-region #"[a-z]{2}(?:-[a-z]+)+-[0-9]"] [:neon-r2-endpoint #"https://[a-z0-9.-]+(?::[0-9]+)?"] [:neon-r2-prefix #"[a-zA-Z0-9][a-zA-Z0-9/_-]*"]]
 :when (not (re-matches pattern (str (get opts k))))] (str k " has invalid characters or format"))
 (when (not= (:s3-region opts) (:neon-r2-region opts)) ["application storage region must match backend region"])
 (when (= (:s3-bucket opts) (:neon-r2-bucket opts)) ["state and application buckets must differ"])
 (try (planning/plan-deployment opts (topology/topology opts) (topology/requirements opts)) [] (catch Exception e [(ex-message e)])))))
(defn secret-errors [opts event]
 (when (and (= event :create) (str/blank? (str (:cloudflare-api-token opts)))) ["COLORS_PAR_CLOUDFLARE_API_TOKEN is required"]))
(defn tofu-env [_ slot] (case slot :provider-dns {:cloudflare-api-token "CLOUDFLARE_API_TOKEN"} {}))

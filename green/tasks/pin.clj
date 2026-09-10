(require '[clojure.java.shell :as sh] '[clojure.string :as str])
(defn git [& args] (let [r (apply sh/sh "git" args)] (when (zero? (:exit r)) (str/trim (:out r)))))
(let [sha (git "rev-parse" "HEAD") p "../skills/package-neon-multi-node-green/green"]
 (when (seq (git "status" "--porcelain")) (throw (ex-info "commit working tree before pinning" {})))
 (when-not (str/includes? (str (git "branch" "-r" "--contains" sha)) "origin/") (throw (ex-info "push HEAD before pinning" {})))
 (let [s (slurp p) pattern #"\(def \^:private neon-multi-node-sha (?:nil|\"[0-9a-f]{40}\")\)"]
 (when-not (re-find pattern s) (throw (ex-info "launcher pin missing" {})))
 (spit p (str/replace-first s pattern (str "(def ^:private neon-multi-node-sha \"" sha "\")")))))

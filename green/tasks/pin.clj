(ns pin (:require [clojure.java.shell :as sh] [clojure.string :as str]))
;; One SHA, three payloads. Every payload is born unpinned — no invented SHAs —
;; and `bb pin` stamps or re-stamps it after a clean, pushed HEAD. Each site
;; recognises exactly two forms, its unpinned birth shape and its pinned shape,
;; and the run fails loudly when a payload matches neither.
(defn git [& args] (let [{:keys [exit out]} (apply sh/sh "git" args)] (when (zero? exit) (str/trim out))))

(defn stamp-green [s sha]
  (when (re-find #"\(def \^:private neon-multi-node-sha (?:nil|\"[0-9a-f]{40}\")\)" s)
    (str/replace-first s #"\(def \^:private neon-multi-node-sha (?:nil|\"[0-9a-f]{40}\")\)"
                       (str "(def ^:private neon-multi-node-sha \"" sha "\")"))))

(defn stamp-red [s sha]
  (let [pinned (str "\"package-neon-multi-node-red\": \"github:getcolors/neon-multi-node#" sha "\",")]
    (cond (str/includes? s "\"package-neon-multi-node-red\": null,")
          (str/replace-first s "\"package-neon-multi-node-red\": null," pinned)
          (re-find #"\"package-neon-multi-node-red\": \"github:getcolors/neon-multi-node#[0-9a-f]{40}\"," s)
          (str/replace-first s #"\"package-neon-multi-node-red\": \"github:getcolors/neon-multi-node#[0-9a-f]{40}\"," pinned))))

(def blue-unpinned-meta "# dependencies = []\n# ///")
(defn blue-pinned-meta [sha]
  (str "# dependencies = [\"package-neon-multi-node-blue\", \"blue\", \"colors-compute-blue @ git+https://github.com/getcolors/colors-compute.git@ae28ea74962bb1897fa6365c143c1d43ac1fe095#subdirectory=blue\"]\n"
       "#\n"
       "# [tool.uv.sources]\n"
       "# package-neon-multi-node-blue = { git = \"https://github.com/getcolors/neon-multi-node.git\", rev = \"" sha "\", subdirectory = \"blue\" }\n"
       "# package-neon-blue = { git = \"https://github.com/getcolors/neon.git\", rev = \"9f8ccc18e218ea3b6ce293a470afd61b19e81639\", subdirectory = \"blue\" }\n"
       "# blue = { git = \"https://github.com/getcolors/blue.git\", rev = \"e29a7fc5a7a2895eacb882fc65520c2cdbab96c9\" }\n"
       "#\n"
       ;; package-once-blue carries its own, older blue pin; the override makes
       ;; this package's blue pin win, as it does in blue/pyproject.toml.
       "# [tool.uv]\n"
       "# override-dependencies = [\"blue @ git+https://github.com/getcolors/blue.git@e29a7fc5a7a2895eacb882fc65520c2cdbab96c9\", \"package-once-blue @ git+https://github.com/getcolors/once.git@10e525ae7c37130ab4d532b91c8d2ead94557cc8#subdirectory=blue\", \"package-neon-blue @ git+https://github.com/getcolors/neon.git@9f8ccc18e218ea3b6ce293a470afd61b19e81639#subdirectory=blue\"]\n"
       "# ///"))
(defn stamp-blue [s sha]
  ;; First stamp is structural: the metadata block gains its git sources and the
  ;; UNPINNED paragraph collapses to a pinned-state note. Re-pinning is a SHA swap.
  (cond (str/includes? s blue-unpinned-meta)
        (-> s
            (str/replace-first blue-unpinned-meta (blue-pinned-meta sha))
            (str/replace-first #"(?s)# UNPINNED:.*?NEON_MULTI_NODE_LIB_ROOT=/path/to/neon-multi-node\n"
                               "# Stamped by `bb pin`. NEON_MULTI_NODE_LIB_ROOT=/path/to/neon-multi-node still overrides the\n# pin with a working tree.\n"))
        (re-find #"neon-multi-node\.git\", rev = \"[0-9a-f]{40}\"" s)
        (str/replace-first s #"neon-multi-node\.git\", rev = \"[0-9a-f]{40}\""
                           (str "neon-multi-node.git\", rev = \"" sha "\""))))

(def sites
  [{:path "../skills/package-neon-multi-node-green/green" :stamp stamp-green}
   {:path "../skills/package-neon-multi-node-red/red" :stamp stamp-red}
   {:path "../skills/package-neon-multi-node-blue/blue" :stamp stamp-blue}])

(let [dirty (git "status" "--porcelain") sha (git "rev-parse" "HEAD") remotes (git "branch" "-r" "--contains" sha)]
  (cond (seq dirty) (do (binding [*out* *err*] (println "neon-multi-node working tree is dirty; commit before pinning")) (System/exit 2))
        (not (str/includes? (str remotes) "origin/")) (do (binding [*out* *err*] (println "neon-multi-node HEAD is not pushed")) (System/exit 2))
        :else (let [errors (atom [])]
                (doseq [{:keys [path stamp]} sites]
                  (let [s (slurp path) n (stamp s sha)]
                    (if n (spit path n) (swap! errors conj (str "could not locate a pin form in " path)))))
                (if (seq @errors)
                  (do (binding [*out* *err*] (println (str/join "\n" @errors))) (System/exit 2))
                  (println "pinned 3 launchers to" (subs sha 0 7))))))

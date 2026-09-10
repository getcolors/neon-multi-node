#!/usr/bin/env bash
# Compare native runtime output against Green and the reviewed golden fixtures.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$repo/scripts/golden.py"
parity_tmp=$(mktemp -d)
trap 'rm -rf "$parity_tmp"' EXIT
for fixture in colors colors-optout; do
  for color in green red blue; do
    sed "s#WORKDIR#$parity_tmp/$fixture/$color#" "$repo/test/fixtures/$fixture.yml" > "$parity_tmp/$fixture-$color.yml"
    env -i "PATH=$PATH" "HOME=$HOME" "NEON_MULTI_NODE_LIB_ROOT=$repo" \
      "$repo/$color/$color" build -f "$parity_tmp/$fixture-$color.yml" > "$parity_tmp/$fixture-$color.log" 2>&1 || {
        cat "$parity_tmp/$fixture-$color.log"
        exit 1
      }
  done
  diff -ru "$parity_tmp/$fixture/green" "$parity_tmp/$fixture/red"
  diff -ru "$parity_tmp/$fixture/green" "$parity_tmp/$fixture/blue"
done
# Red imports three generic configuration files from the pinned Neon package.
# Its own application templates must still match Green exactly.
while IFS= read -r -d '' resource; do
  relative=${resource#"$repo/green/src/resources/io/github/getcolors/neon_multi_node/"}
  cmp "$resource" "$repo/red/resources/$relative"
done < <(find "$repo/green/src/resources/io/github/getcolors/neon_multi_node" -type f ! -name "*.pyc" ! -path "*/__pycache__/*" -print0)
diff -ru --exclude=__pycache__ "$repo/green/src/resources/io/github/getcolors/neon_multi_node" "$repo/blue/src/package_neon_multi_node_blue/resources"
echo 'PASS Green, Red and Blue render identical trees for both SSH key modes'

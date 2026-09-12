#!/usr/bin/env bash
# Verify the copied launcher outside the checkout, including nested discovery.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fixture_dir=$(mktemp -d)
cleanup() {
  result=$?
  if [[ "$result" -ne 0 ]]; then
    for logfile in "$fixture_dir"/*.log "$fixture_dir"/nested/deeper/*.log; do
      [[ ! -f "$logfile" ]] || tail -80 "$logfile"
    done
  fi
  rm -rf "$fixture_dir"
  exit "$result"
}
trap cleanup EXIT
red_launcher="$repo/skills/package-neon-multi-node-red/red"
# colors-compute-red declares the Red SDK as a peer, so a cold launcher cache
# installs the SDK only because PINS names it. The pin must be the one
# red/package.json tests against, and a cold cache must actually resolve it:
# the working-tree builds below reuse red/node_modules and cannot see a
# missing peer.
red_sdk_sha=$(grep -oE '"red": "github:getcolors/red#[0-9a-f]{40}"' "$repo/red/package.json" | grep -oE '[0-9a-f]{40}' | head -1)
[[ -n $red_sdk_sha ]] || { echo 'red/package.json carries no Red SDK pin' >&2; exit 1; }
grep -q "\"red\": \"github:getcolors/red#$red_sdk_sha\"" "$red_launcher" || { echo 'red payload PINS the Red SDK at a different commit than red/package.json' >&2; exit 1; }
echo "PASS red payload PINS the Red SDK at the red/package.json commit"
mkdir "$fixture_dir/red-cold"
cp "$red_launcher" "$fixture_dir/red-cold/red"; chmod +x "$fixture_dir/red-cold/red"
sed "s#WORKDIR#$fixture_dir/red-cold/rendered#" "$repo/test/fixtures/colors.yml" > "$fixture_dir/red-cold/colors.yml"
# One retry: a cold install fetches three GitHub tarballs and a transient
# fetch failure is not a payload defect. Each attempt starts from empty caches.
cold_ok=0
for attempt in 1 2; do
  rm -rf "$fixture_dir/red-cold/xdg" "$fixture_dir/red-cold/bun" "$fixture_dir/red-cold/rendered"
  if (cd "$fixture_dir/red-cold" && env -i "PATH=$PATH" "HOME=$HOME" XDG_CACHE_HOME="$fixture_dir/red-cold/xdg" BUN_INSTALL_CACHE_DIR="$fixture_dir/red-cold/bun" ./red build >"$fixture_dir/red-cold.log" 2>&1); then cold_ok=1; break; fi
done
[[ $cold_ok == 1 ]] || { echo 'red payload does not build from a cold cache' >&2; exit 1; }
echo "PASS red payload builds from a cold cache with only its PINS"
for color in green red blue; do
cp "$repo/skills/package-neon-multi-node-$color/$color" "$fixture_dir/$color"
chmod +x "$fixture_dir/$color"
sed "s#WORKDIR#$fixture_dir/rendered#" "$repo/test/fixtures/colors.yml" > "$fixture_dir/colors.yml"
mkdir -p "$fixture_dir/nested/deeper"
runner_env=(env -i "PATH=$PATH" "HOME=$HOME")
if [[ "${1:-}" != "--published" ]]; then
  runner_env+=("NEON_MULTI_NODE_LIB_ROOT=$repo")
else
  runner_env+=("XDG_CACHE_HOME=$fixture_dir/cache/$color"
    "BUN_INSTALL_CACHE_DIR=$fixture_dir/bun-cache/$color"
    "UV_CACHE_DIR=$fixture_dir/uv-cache/$color")
fi
(cd "$fixture_dir" && "${runner_env[@]}" ./"$color" build > build.log 2>&1)
(cd "$fixture_dir/nested/deeper" && "${runner_env[@]}" ../../"$color" build > nested.log 2>&1)
for verb in create delete rehearse describe; do
  (cd "$fixture_dir/nested/deeper" && "${runner_env[@]}" ../../"$color" "$verb" --dry-run > "$verb.log" 2>&1)
done
cmp "$fixture_dir/$color" "$repo/skills/package-neon-multi-node-$color/$color"
set +e
(cd "$fixture_dir" && "${runner_env[@]}" COLORS_PAR_PROFILE=wrong ./"$color" build > profile-guard.log 2>&1)
profile_status=$?
(cd "$fixture_dir" && "${runner_env[@]}" ./"$color" delete > delete-guard.log 2>&1)
delete_status=$?
set -e
test "$profile_status" -eq 2
rg -q 'COLORS_PAR_PROFILE' "$fixture_dir/profile-guard.log"
test "$delete_status" -eq 2
rg -q 'destruction is protected' "$fixture_dir/delete-guard.log"
echo "PASS $color copied launcher, empty credential environment, nested discovery, build and four dry-run verbs"
done

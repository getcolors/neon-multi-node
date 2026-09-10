#!/usr/bin/env bash
# Verify the copied launcher outside the checkout, including nested discovery.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fixture_dir=$(mktemp -d)
trap 'rm -rf "$fixture_dir"' EXIT
for color in green red blue; do
cp "$repo/skills/package-neon-multi-node-$color/$color" "$fixture_dir/$color"
chmod +x "$fixture_dir/$color"
sed "s#WORKDIR#$fixture_dir/rendered#" "$repo/test/fixtures/colors.yml" > "$fixture_dir/colors.yml"
mkdir -p "$fixture_dir/nested/deeper"
runner_env=(env -i "PATH=$PATH" "HOME=$HOME")
if [[ "${1:-}" != "--published" ]]; then
  runner_env+=("NEON_MULTI_NODE_LIB_ROOT=$repo")
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

#!/usr/bin/env bash
# Verify the copied launcher outside the checkout, including nested discovery.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fixture_dir=$(mktemp -d)
trap 'rm -rf "$fixture_dir"' EXIT
cp "$repo/skills/package-neon-multi-node-green/green" "$fixture_dir/green"
chmod +x "$fixture_dir/green"
sed "s#WORKDIR#$fixture_dir/rendered#" "$repo/test/fixtures/colors.yml" > "$fixture_dir/colors.yml"
mkdir -p "$fixture_dir/nested/deeper"
runner_env=(env -i "PATH=$PATH" "HOME=$HOME")
if [[ "${1:-}" != "--published" ]]; then
  runner_env+=("NEON_MULTI_NODE_LIB_ROOT=$repo")
fi
(cd "$fixture_dir" && "${runner_env[@]}" ./green build > build.log 2>&1)
(cd "$fixture_dir/nested/deeper" && "${runner_env[@]}" ../../green build > nested.log 2>&1)
for verb in create delete rehearse describe; do
  (cd "$fixture_dir/nested/deeper" && "${runner_env[@]}" ../../green "$verb" --dry-run > "$verb.log" 2>&1)
done
cmp "$fixture_dir/green" "$repo/skills/package-neon-multi-node-green/green"
echo 'PASS copied launcher, empty credential environment, nested discovery, build and four dry-run verbs'

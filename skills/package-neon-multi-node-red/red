#!/usr/bin/env bun
// Neon Multi-Node launcher — five AWS roles, native PostgreSQL TLS and managed S3.
//
// Desired state lives in colors.yml, found by walking up from the working
// directory. Secrets and tokens are never written there: every credential key
// is supplied at runtime through a COLORS_PAR_* environment variable, which is
// overlaid onto the matching flat key.
//
// COLORS_PAR_PROFILE is the exception — neon refuses to run when it is
// set. The profile names this project's work directory, OpenTofu state key,
// machine keypair and cloud resources, and overriding it from the environment
// can only point neon at another project's state.
//
// This file is both the skill payload and the repository entry point — red/red
// in the repository is a symlink to it. It deliberately holds no logic of its
// own: validation, the graph and the steps all live in the `package-neon-multi-node-red`
// library, where the test suite reaches them. A copied payload is the one place
// in this project where code cannot be tested, so nothing that can live
// elsewhere should live here.
import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

// The commits a copied payload must resolve. Managed by `bb pin` — do not edit
// by hand, and keep exactly one occurrence of each: `pin` rewrites the first
// match and a second copy would silently go stale.
//
// "package-neon-multi-node-red" is null before this repository has been pushed and
// stamped: a launcher that cannot resolve its own library says so rather than
// inventing a SHA or silently falling back to whatever is lying around.
// `bb pin` refuses to stamp a dirty or unpushed HEAD for the same reason, and
// rewrites null to "github:getcolors/neon-multi-node#<sha>" in place.
//
// These are live code rather than a comment because the launcher resolves them
// itself (see below). They stay out of a bundled package.json in this
// directory, which would halt Bun's upward resolution of `package-neon-multi-node-red`
// and break the development symlink at red/red.
const PINS = {
  "red": "github:getcolors/red#7636bee6a7575485ebaf621f4b1834bdcea59738",
  "package-neon-multi-node-red": "github:getcolors/neon-multi-node#2a670940d8391be1ad751fffd24f358017b30427",
  "colors-compute-red": "github:getcolors/colors-compute#09ec539e75dc21c4dafb019eb8f9da276e695f6f",
};

// PINS is the only source of versions, as green's inline SHA and blue's PEP
// 723 metadata are for them. A project manifest is never consulted: it would be
// a second record of the same commit, and the two drift.
//
// A static import would fail during resolution, before any line of this file
// runs, with a bare "Cannot find package" naming no fix. The import stays
// dynamic so the failure can be answered instead of reported. The answer cannot
// live in the package for the obvious reason: the package is what is missing.
//
// Ordinary resolution still wins when it succeeds, which is what keeps a
// checkout usable — the same role green's classpath check plays before it calls
// add-deps. NEON_MULTI_NODE_LIB_ROOT overrides everything with a working tree: point
// it at the `red/` directory of a neon checkout whose dependencies are
// installed, and the copied payload runs those sources instead of any pin.

/** The nearest directory at or above `from` holding a package.json, or null. */
function manifestDir(from) {
  let dir = from;
  for (;;) {
    if (existsSync(join(dir, "package.json"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function readManifest(dir) {
  try {
    return JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  } catch {
    return null;
  }
}

/** The `red/` colour directory of the checkout this payload lives in, or null.
 *
 * The payload's canonical home is skills/package-neon-multi-node-red/ inside the
 * neon repository, whose working tree is the point: resolving a pinned
 * copy from the cache would quietly test the pinned commit instead of the edits
 * under test.
 */
function checkoutRedDir() {
  const candidate = join(import.meta.dir, "..", "..", "red");
  const manifest = readManifest(candidate);
  return manifest?.name === "package-neon-multi-node-red-dev" ? candidate : null;
}

/** Import the library from a working tree's `red/` directory. */
async function importWorkingTree(redDir, label) {
  const entry = join(redDir, "src", "index.ts");
  if (!existsSync(entry)) {
    console.error(`red: ${label} ${redDir} has no src/index.ts`);
    process.exit(2);
  }
  try {
    return await import(entry);
  } catch (err) {
    if (err?.code !== "ERR_MODULE_NOT_FOUND") throw err;
    console.error(
      `red: cannot resolve '${err.specifier}' from ${label} ${redDir}\n` +
        `dependencies are not installed; run: bun install --cwd ${redDir}`,
    );
    process.exit(2);
  }
}

/** Install `PINS` into a cache keyed by their exact specifiers.
 *
 * Keyed by content, so re-pinning lands in a new directory instead of reusing a
 * stale tree, and two projects on different pins never share one. Staged in a
 * sibling and renamed, so concurrent cold starts cannot observe a half-installed
 * tree; whichever loses the rename discards its copy and uses the winner's,
 * which is byte-identical by construction.
 */
function installToCache() {
  const home = process.env.XDG_CACHE_HOME || join(homedir(), ".cache");
  const root = join(home, "package-neon-multi-node-red");
  const key = Bun.hash(JSON.stringify(PINS)).toString(16);
  const target = join(root, key);
  if (existsSync(join(target, "node_modules"))) return { dir: target };

  // Announced only when something is actually fetched: every later run takes
  // the branch above, and a line claiming a first run on each of them would be
  // noise on the way to every command's real output.
  console.error("red: resolving dependencies (first run)");
  mkdirSync(root, { recursive: true });
  const staging = mkdtempSync(join(root, `.${key}.`));
  // Resolve immutable Git pins as GitHub commit archives. Bun 1.3.10's Git
  // resolver intermittently fails duplicate direct/transitive Git dependencies
  // even after download; archive dependencies avoid that resolver entirely.
  const archives = Object.fromEntries(Object.entries(PINS).map(([name, pin]) => {
    const match = /^github:([^#]+)#([a-f0-9]{40})$/.exec(pin);
    if (!match) throw new Error(`red: invalid immutable dependency pin for ${name}`);
    return [name, `https://codeload.github.com/${match[1]}/tar.gz/${match[2]}`];
  }));
  writeFileSync(
    join(staging, "package.json"),
    `${JSON.stringify({ name: "package-neon-multi-node-red-cache", private: true, dependencies: archives, overrides: archives }, null, 2)}\n`,
  );
  const installed = Bun.spawnSync([process.execPath, "install"], {
    cwd: staging,
    stdout: "ignore",
    stderr: "pipe",
  });
  if (installed.exitCode !== 0) {
    rmSync(staging, { recursive: true, force: true });
    return { error: installed.stderr.toString().trim() };
  }
  try {
    renameSync(staging, target);
  } catch {
    // Another cold start won the race; its tree is equivalent.
    rmSync(staging, { recursive: true, force: true });
  }
  return existsSync(join(target, "node_modules"))
    ? { dir: target }
    : { error: `nothing installed under ${target}` };
}

let neon;
const libRoot = process.env.NEON_MULTI_NODE_LIB_ROOT;
const redDir = checkoutRedDir();
if (libRoot) {
  const overrideDir = existsSync(join(libRoot, "red", "src", "index.ts")) ? join(libRoot, "red") : libRoot;
  neon = await importWorkingTree(overrideDir, "NEON_MULTI_NODE_LIB_ROOT");
} else if (redDir) {
  neon = await importWorkingTree(redDir, "checkout");
} else if (!PINS["package-neon-multi-node-red"] || process.env.RED_NO_BOOTSTRAP) {
  console.error("red: no published package pin or bootstrap disabled; use NEON_MULTI_NODE_LIB_ROOT for development");
  process.exit(2);
} else {
  const {dir,error} = installToCache();
  if(error){console.error(`red: could not resolve dependencies\n${error}`);process.exit(2);}
  neon = await import(Bun.resolveSync("package-neon-multi-node-red",dir));
}

export const run = neon.run;
if (import.meta.main) await neon.exec();

#!/usr/bin/env python3
"""Compare deterministic rendered trees; optional offline playbook syntax gate."""
import difflib, json, os, pathlib, subprocess, sys, tempfile
root = pathlib.Path(__file__).resolve().parents[1]
errors = []
with tempfile.TemporaryDirectory() as tmp:
    for fixture in ('colors', 'colors-optout'):
        work = pathlib.Path(tmp) / fixture
        config = pathlib.Path(tmp) / (fixture + '.yml')
        config.write_text((root/'test/fixtures'/ (fixture+'.yml')).read_text().replace('WORKDIR', str(work)))
        env = {k:v for k,v in os.environ.items() if not k.startswith(('COLORS_PAR_', 'AWS_', 'NEON_MULTI_NODE_LIB_ROOT'))}
        env['NEON_MULTI_NODE_LIB_ROOT'] = str(root)
        subprocess.run([str(root/'green/green'), 'build', '-f', str(config)], env=env, check=True, capture_output=True)
        tree={str(p.relative_to(work)): p.read_text().replace(str(work), 'WORKDIR') for p in sorted(work.rglob('*')) if p.is_file()}
        actual=json.dumps(tree, indent=2, sort_keys=True)+'\n'
        golden=root/'test/resources/golden'/ (fixture+'.json')
        if '--accept' in sys.argv:
            golden.parent.mkdir(parents=True, exist_ok=True); golden.write_text(actual)
        elif '--syntax' not in sys.argv and (not golden.exists() or golden.read_text()!=actual):
            errors.append(fixture)
            previous = json.loads(golden.read_text()) if golden.exists() else {}
            for name in sorted(previous.keys() | tree.keys()):
                old, new = previous.get(name, ''), tree.get(name, '')
                if old != new:
                    print(''.join(difflib.unified_diff(
                        old.splitlines(True), new.splitlines(True),
                        fromfile=f'{fixture}/golden/{name}',
                        tofile=f'{fixture}/rendered/{name}')), end='')
        if '--syntax' in sys.argv:
            stage=work/'neon-multi-node-fixture/neon-multi-node-ansible'
            for play in ('site.yml','cleanup.yml','rehearsal.yml'):
                subprocess.run(['ansible-playbook','--syntax-check','-i','inventory.json',play],cwd=stage,env=env,check=True)
        print(f'{fixture}: rendered {len(tree)} files')
if errors: raise SystemExit('Golden differences: '+', '.join(errors))

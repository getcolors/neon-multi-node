"""Acceptance failure classification must never count connectivity errors as auth proof."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
RUNTIME=Path(__file__).parents[1]/'green/src/resources/io/github/getcolors/neon_multi_node/tools/ansible/runtime.py'
spec=importlib.util.spec_from_file_location('runtime',RUNTIME)
r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
class SQLGates(unittest.TestCase):
    def setUp(self): r.C={'role':'neon','database':'neondb'}
    def result(self,code,stderr='',stdout=''):
        return patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],code,stdout,stderr))
    def test_network_failure_is_not_auth_evidence(self):
        with self.result(2,'connection refused'),self.assertRaises(RuntimeError):
            r.sql('SELECT 1',pw='wrong',expect=False,refusal=['password authentication failed'])
    def test_authentication_failure_is_evidence(self):
        with self.result(2,'FATAL: password authentication failed'):
            r.sql('SELECT 1',pw='wrong',expect=False,refusal=['password authentication failed'])
    def test_success_never_satisfies_negative_gate(self):
        with self.result(0,stdout='1'),self.assertRaises(RuntimeError):
            r.sql('SELECT 1',pw='wrong',expect=False,refusal=['password authentication failed'])
    def test_diagnostics_redact_supplied_password(self):
        with self.result(2,'error contains secret-value'):
            with self.assertRaises(RuntimeError) as caught:r.sql('SELECT 1',pw='secret-value')
            self.assertNotIn('secret-value',str(caught.exception))
    def test_clean_client_env_and_timeout(self):
        with self.result(0,stdout='1') as execute:
            self.assertEqual(r.sql('SELECT 1',pw='test'),'1')
            env=execute.call_args.kwargs['env']
            self.assertEqual(env['PGPASSFILE'],'/dev/null')
            self.assertNotIn('HOME',env)
            self.assertIn('-w',execute.call_args.args[0])
class PinnedTLSContract(unittest.TestCase):
    def test_native_tls_feature_is_enabled_for_pinned_compute(self):
        import json
        spec=json.loads((RUNTIME.parent/'compute-spec.json').read_text())
        settings={item['name']:item['value'] for item in spec['spec']['cluster']['settings']}
        self.assertEqual(settings['ssl'],'on')
        self.assertEqual(settings['ssl_cert_file'],'/etc/neon/tls/fullchain.pem')
        self.assertEqual(settings['ssl_key_file'],'/etc/neon/tls/privkey.pem')
        self.assertNotIn('tls',spec['compute_ctl_config'],
                         'pinned compute_ctl TLS copier rejects ACME ECDSA-SHA384 signatures')
class QuorumWitnesses(unittest.TestCase):
    def test_each_outage_gets_distinct_durable_witness_and_old_value_cannot_pass(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as tmp:
            rows={}
            def execute(query):
                import re
                if query.startswith('INSERT'):
                    key,value=re.findall("'([^']*)'",query)
                    rows[key]=value
                    return value
                return rows.get(re.findall("'([^']*)'",query)[0],'')
            with patch.object(r,'P',Path(tmp)),patch.object(r,'sql',side_effect=execute),patch.object(r,'write',side_effect=lambda p,b:Path(p).write_text(json.dumps(b))):
                r.quorum_write('member-1'); r.quorum_write('member-1')
                ledger=json.loads((Path(tmp)/'rehearsal-witnesses.json').read_text())
                self.assertEqual(len({x['id'] for x in ledger}),2)
                r.quorum_witness()
                rows[ledger[1]['id']]=ledger[0]['value']
                with self.assertRaises(AssertionError): r.quorum_witness()
if __name__=='__main__': unittest.main()

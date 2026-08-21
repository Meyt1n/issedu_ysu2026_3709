import assert from 'node:assert/strict'
import { fingerprint, validateControlledReleaseRecord } from './verify-controlled-release.mjs'

const record = {
  release_id: 'MOB-147-controlled-demo-20260821',
  environment: 'controlled-demo',
  server_base_url: 'https://controlled.demo.test',
  server_commit: '0123456789abcdef',
  app_commit: 'abcdef0123456789',
  api_version: 'v1',
  pwa_shell_version: 'hct-mobile-shell-v2',
  android_version: '0.1.0-demo',
  synthetic_seed_sha256: 'a'.repeat(64),
  synthetic_data: { is_real: false, label: '演示' },
  device: { target: 'PWA', os: 'test', browser_or_webview: 'test' },
  evidence: { scenarios: ['cold-start'] },
}

assert.deepEqual(validateControlledReleaseRecord(record), [])
assert.match(fingerprint(record), /^[a-f0-9]{64}$/)
assert.ok(validateControlledReleaseRecord({ ...record, server_base_url: 'http://192.168.1.2' }).some(error => error.includes('HTTPS')))
assert.ok(validateControlledReleaseRecord({ ...record, api_token: 'not-allowed' }).some(error => error.includes('敏感字段')))
assert.ok(validateControlledReleaseRecord({ ...record, synthetic_data: { is_real: true, label: '演示' } }).some(error => error.includes('synthetic_data')))
console.log('controlled release verifier tests passed')
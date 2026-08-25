import https from 'node:https'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

function readArgument(flag, fallback) {
  const index = process.argv.indexOf(flag)
  return index >= 0 ? process.argv[index + 1] : fallback
}

const keyPath = readArgument('--key')
const certPath = readArgument('--cert')
const pfxPath = readArgument('--pfx')
const password = readArgument('--password', '')
const port = Number(readArgument('--port', '18443'))

if ((!pfxPath && (!keyPath || !certPath)) || (pfxPath && (keyPath || certPath)) || !Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('用法：node scripts/controlled-https-fixture.mjs (--pfx <PKCS12> --password <密码> | --key <私钥> --cert <测试证书>) [--port 18443]')
}

const headers = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'Accept, Content-Type, X-Access-Purpose',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Cache-Control': 'no-store',
  'Content-Type': 'application/json; charset=utf-8',
}

const responses = new Map([
  ['/health', { status: 'ok', service: 'controlled-https-fixture', version: 'synthetic-237' }],
  ['/api/v1/meta/capabilities', { phase: 'controlled-demo', available: [], unavailable: ['all-live-data'] }],
  ['/api/v1/households', []],
])

const tlsOptions = pfxPath
  ? { pfx: fs.readFileSync(path.resolve(pfxPath)), passphrase: password }
  : { key: fs.readFileSync(path.resolve(keyPath)), cert: fs.readFileSync(path.resolve(certPath)) }

const server = https.createServer(tlsOptions, (request, response) => {
  if (request.method === 'OPTIONS') {
    response.writeHead(204, headers)
    response.end()
    return
  }

  const payload = responses.get(new URL(request.url ?? '/', 'https://localhost').pathname)
  if (request.method !== 'GET' || payload === undefined) {
    response.writeHead(404, headers)
    response.end(JSON.stringify({ detail: 'not found' }))
    return
  }

  response.writeHead(200, headers)
  response.end(JSON.stringify(payload))
})

server.listen(port, '127.0.0.1', () => {
  console.log(JSON.stringify({ status: 'listening', host: '127.0.0.1', port, synthetic: true }))
})

function shutdown() {
  server.close(() => process.exit(0))
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

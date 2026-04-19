import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')
const certDir = resolve(frontendRoot, 'certs')
const keyPath = resolve(certDir, 'localhost-key.pem')
const certPath = resolve(certDir, 'localhost-cert.pem')

if (existsSync(keyPath) && existsSync(certPath)) {
  console.log('HTTPS development certificate already exists.')
  console.log(`key:  ${keyPath}`)
  console.log(`cert: ${certPath}`)
  process.exit(0)
}

mkdirSync(certDir, { recursive: true })

// 证书覆盖 localhost、127.0.0.1 和当前常用局域网 IP；如 IP 变化，可重新运行脚本。
const subjectAltName = [
  'DNS:localhost',
  'IP:127.0.0.1',
  'IP:0.0.0.0',
  'IP:10.61.48.10',
].join(',')

execFileSync(
  'openssl',
  [
    'req',
    '-x509',
    '-newkey',
    'rsa:2048',
    '-nodes',
    '-sha256',
    '-days',
    '365',
    '-subj',
    '/CN=localhost',
    '-addext',
    `subjectAltName=${subjectAltName}`,
    '-keyout',
    keyPath,
    '-out',
    certPath,
  ],
  { stdio: 'inherit' },
)

console.log('Created HTTPS development certificate.')
console.log(`key:  ${keyPath}`)
console.log(`cert: ${certPath}`)
console.log('Restart Vite and open https://localhost:5173 or https://10.61.48.10:5173.')

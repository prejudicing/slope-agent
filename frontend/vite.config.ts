import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const devKeyPath = resolve(__dirname, 'certs', 'localhost-key.pem')
const devCertPath = resolve(__dirname, 'certs', 'localhost-cert.pem')

const devHttps =
  existsSync(devKeyPath) && existsSync(devCertPath)
    ? {
        key: readFileSync(devKeyPath),
        cert: readFileSync(devCertPath),
      }
    : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    target: 'es2018',
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    https: devHttps,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    https: devHttps,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})

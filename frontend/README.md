# 高切坡 Agent 前端

Vue 3 + TypeScript + Vite 前端页面，用于自然语言查询高切坡业务数据。

## 开发启动

普通 HTTP 开发服务：

```bash
npm run dev
```

需要中文语音输入时，启动 HTTPS 开发服务：

```bash
npm run dev:https
```

首次运行 `dev:https` 会自动生成本地自签名证书：

```text
frontend/certs/localhost-key.pem
frontend/certs/localhost-cert.pem
```

证书目录已加入 `.gitignore`，不会提交到仓库。

## 访问地址

HTTPS 服务启动后会输出类似地址：

```text
https://localhost:5173/
https://10.61.48.10:5173/
```

浏览器第一次访问自签名证书地址时会提示“不安全”或“证书无效”，开发环境下需要手动选择继续访问。

中文语音输入依赖浏览器 Web Speech API 和麦克风权限。通常 Chrome / Edge 支持较好；手机访问时需要连接同一局域网，并使用 HTTPS 地址。

## 构建

```bash
npm run build
```

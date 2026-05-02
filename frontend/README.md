# 高切坡 Agent 前端

Vue 3 + TypeScript + Vite 前端页面，用于自然语言查询高切坡业务数据。

当前已接入 Capacitor，可封装为 Android App。

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

## Android App

### 1. 配置后端地址

先复制一份环境变量模板：

```bash
cp .env.example .env.local
```

把后端地址改成手机能访问到的地址，例如：

```env
VITE_API_BASE_URL=http://10.61.48.10:8000
```

### 2. 构建并同步到 Android 工程

```bash
npm run android:sync
```

### 3. 打开 Android Studio

```bash
npm run android:open
```

然后在 Android Studio 中选择真机或模拟器运行。

## 说明

- Android 工程目录位于 `frontend/android/`
- 当前安卓工程已允许开发期访问 HTTP 后端，方便局域网联调
- 如果修改了前端代码或 `VITE_API_BASE_URL`，需要重新执行 `npm run android:sync`

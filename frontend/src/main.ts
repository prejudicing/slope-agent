import { createApp } from 'vue'
import App from './App.vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './style.css'

// Element Plus 提供输入框、按钮、卡片、表格等基础 UI 组件。
createApp(App).use(ElementPlus).mount('#app')

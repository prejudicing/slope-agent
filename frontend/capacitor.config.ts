import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.highcutslope.agent',
  appName: '高切坡业务问答',
  webDir: 'dist',
  server: {
    androidScheme: 'http',
  },
};

export default config;

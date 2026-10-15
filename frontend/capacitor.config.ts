import { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.visionforge.app',
  appName: 'VisionForge',
  webDir: 'dist',
  server: {
    androidScheme: 'http'
  }
};

export default config;

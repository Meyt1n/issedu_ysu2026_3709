import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.homecaretwin.companion',
  appName: '家健镜随身版',
  webDir: 'dist',
  server: {
    // WebView 以 https://localhost 为源加载本地打包资源；
    // 访问家庭服务器的明文 http 地址由 AndroidManifest 的 usesCleartextTraffic 允许（仅家庭局域网）。
    androidScheme: 'https',
  },
}

export default config

import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.homecaretwin.companion',
  appName: '家健镜随身版',
  webDir: 'dist',
  server: {
    // WebView 以 https://localhost 为源加载本地打包资源；
    // Release 只允许 HTTPS；Android Debug 配合 APP 层私网地址校验开放受控 HTTP 联调。
    androidScheme: 'https',
  },
}

export default config

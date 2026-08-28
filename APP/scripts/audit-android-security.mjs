import { readFile } from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

async function read(relativePath) {
  return readFile(path.join(appRoot, relativePath), 'utf8')
}

async function readOptional(relativePath) {
  try {
    return await read(relativePath)
  } catch (error) {
    if (error?.code === 'ENOENT') return null
    throw error
  }
}

function requireMatch(source, pattern, message) {
  if (!pattern.test(source)) throw new Error(message)
}

function forbidMatch(source, pattern, message) {
  if (pattern.test(source)) throw new Error(message)
}

const mainManifest = await read('android/app/src/main/AndroidManifest.xml')
const debugManifest = await read('android/app/src/debug/AndroidManifest.xml')
const mainActivity = await read('android/app/src/main/java/com/homecaretwin/companion/MainActivity.java')
const networkRelease = await read('android/app/src/main/res/xml/network_security_config.xml')
const networkDebug = await read('android/app/src/debug/res/xml/network_security_config_debug.xml')
const backupRules = await read('android/app/src/main/res/xml/backup_rules.xml')
const extractionRules = await read('android/app/src/main/res/xml/data_extraction_rules.xml')
const mergedReleaseManifest = await readOptional(
  'android/app/build/intermediates/merged_manifest/release/processReleaseMainManifest/AndroidManifest.xml',
)

requireMatch(mainManifest, /android:allowBackup="false"/, '主 Manifest 必须关闭 Android 自动备份。')
requireMatch(mainManifest, /android:usesCleartextTraffic="false"/, '主/Release Manifest 必须拒绝明文流量。')
requireMatch(mainManifest, /android:fullBackupContent="@xml\/backup_rules"/, '主 Manifest 缺少 Android 11 及以下备份规则。')
requireMatch(mainManifest, /android:dataExtractionRules="@xml\/data_extraction_rules"/, '主 Manifest 缺少 Android 12+ 数据提取规则。')
requireMatch(mainManifest, /android:networkSecurityConfig="@xml\/network_security_config"/, '主 Manifest 缺少 Release 网络安全配置。')
requireMatch(networkRelease, /cleartextTrafficPermitted="false"/, 'Release 网络安全配置必须拒绝明文流量。')

requireMatch(debugManifest, /android:usesCleartextTraffic="true"/, 'Debug Manifest 应显式声明受控明文联调覆盖。')
requireMatch(debugManifest, /@xml\/network_security_config_debug/, 'Debug Manifest 缺少独立网络安全配置。')
requireMatch(networkDebug, /cleartextTrafficPermitted="true"/, 'Debug 网络安全配置未启用局域网联调所需明文能力。')
requireMatch(networkDebug, /@raw\/controlled_https_ca/, 'Debug 网络安全配置缺少受控 HTTPS 测试 CA。')
forbidMatch(networkRelease, /controlled_https_ca/, 'Release 网络安全配置不得信任受控 Debug 测试 CA。')
requireMatch(
  mainActivity,
  /if\s*\(\s*BuildConfig\.DEBUG\s*&&[\s\S]*?setMixedContentMode\(WebSettings\.MIXED_CONTENT_ALWAYS_ALLOW\)/,
  'Android WebView 明文联调放行必须由 BuildConfig.DEBUG 守卫。',
)
requireMatch(mainActivity, /import\s+android\.webkit\.WebSettings\s*;/, 'MainActivity 缺少 WebSettings 导入。')

for (const domain of ['root', 'file', 'database', 'sharedpref', 'external']) {
  const excluded = new RegExp(`<exclude\\s+domain="${domain}"\\s+path="\\."\\s*\\/>`)
  requireMatch(backupRules, excluded, `旧版备份规则未排除 ${domain}。`)
  requireMatch(extractionRules, excluded, `Android 12+ 提取规则未排除 ${domain}。`)
}
for (const domain of ['device_root', 'device_file', 'device_database', 'device_sharedpref']) {
  requireMatch(
    extractionRules,
    new RegExp(`<exclude\\s+domain="${domain}"\\s+path="\\."\\s*\\/>`),
    `Android 12+ 提取规则未排除 ${domain}。`,
  )
}
requireMatch(extractionRules, /<cloud-backup>/, '缺少云备份排除段。')
requireMatch(extractionRules, /<device-transfer>/, '缺少设备迁移排除段。')

const declaredPermissions = [...mainManifest.matchAll(/<uses-permission\s+android:name="([^"]+)"/g)]
  .map(match => match[1])
requireMatch(mainManifest, /android\.permission\.INTERNET/, '应用缺少联机所需 INTERNET 权限。')
for (const permission of declaredPermissions) {
  if (permission !== 'android.permission.INTERNET') {
    throw new Error(`发现未列入最小权限基线的 Android 权限：${permission}`)
  }
}
forbidMatch(mainManifest, /android\.permission\.(CAMERA|CALL_PHONE|READ_|WRITE_)/, '主 Manifest 声明了当前实现不需要的敏感权限。')

const mergedPermissions = mergedReleaseManifest
  ? [...mergedReleaseManifest.matchAll(/<uses-permission\s+android:name="([^"]+)"/g)].map(match => match[1])
  : []
if (mergedReleaseManifest) {
  const allowedMergedPermissions = new Set([
    'android.permission.INTERNET',
    'android.permission.RECEIVE_BOOT_COMPLETED',
    'android.permission.WAKE_LOCK',
    'android.permission.POST_NOTIFICATIONS',
    'android.permission.SCHEDULE_EXACT_ALARM',
  ])
  for (const permission of mergedPermissions) {
    if (!allowedMergedPermissions.has(permission) && !permission.endsWith('.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION')) {
      throw new Error(`Release 合并 Manifest 发现未列入最小权限基线的 Android 权限：${permission}`)
    }
  }
  requireMatch(mergedReleaseManifest, /android:allowBackup="false"/, 'Release 合并 Manifest 必须关闭 Android 自动备份。')
  requireMatch(mergedReleaseManifest, /android:usesCleartextTraffic="false"/, 'Release 合并 Manifest 必须拒绝明文流量。')
  forbidMatch(mergedReleaseManifest, /android\.permission\.(CAMERA|CALL_PHONE|READ_|WRITE_)/, 'Release 合并 Manifest 声明了未使用的敏感权限。')
}

console.log(JSON.stringify({
  status: 'passed',
  releaseCleartext: false,
  debugCleartext: true,
  debugMixedContent: 'BuildConfig.DEBUG only',
  backupAndDeviceTransfer: 'excluded',
  declaredPermissions,
  mergedReleaseManifestChecked: Boolean(mergedReleaseManifest),
  mergedReleasePermissions: mergedPermissions,
}, null, 2))

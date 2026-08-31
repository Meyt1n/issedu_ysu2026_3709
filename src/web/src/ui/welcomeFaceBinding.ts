export type WelcomeCredentialMode = 'password' | 'pin' | 'face'

export interface FaceBindingSummary {
  /** 只有人脸 tab 需要本机家庭绑定卡片；密码登录不依赖设备绑定，必须隐藏。 */
  visible: boolean
  bound: boolean
  title: string
  detail: string
  /** 未绑定时的唯一回退动作文案；已绑定或不可见时为空字符串。 */
  fallbackLabel: string
}

const HIDDEN: FaceBindingSummary = {
  visible: false,
  bound: false,
  title: '',
  detail: '',
  fallbackLabel: '',
}

/**
 * 欢迎页本机人脸登录家庭卡片（HCT-425 / HCT-510）。
 *
 * 家庭人脸 1:N 只在本机绑定的家庭内匹配。账号密码与已下线的 PIN 登录
 * 都不依赖设备绑定，任何情况下都不显示该卡片。
 */
export function faceBindingSummary(
  credentialMode: WelcomeCredentialMode,
  boundHouseholdId: string,
  boundHouseholdName = '',
): FaceBindingSummary {
  if (credentialMode !== 'face') return HIDDEN
  if (!boundHouseholdId.trim()) {
    return {
      visible: true,
      bound: false,
      title: '本机尚未开启刷脸',
      detail: '请改用账号密码。',
      fallbackLabel: '用账号密码登录',
    }
  }
  return {
    visible: true,
    bound: true,
    title: boundHouseholdName.trim() || '已绑定本机家庭',
    detail: '',
    fallbackLabel: '',
  }
}

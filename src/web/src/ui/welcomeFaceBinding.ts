export type WelcomeCredentialMode = 'password' | 'pin' | 'face'

export interface FaceBindingSummary {
  /** 只有人脸 tab 需要本机家庭绑定卡片；密码 / PIN 登录不依赖设备绑定，必须隐藏。 */
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
 * 欢迎页“本机人脸登录家庭”卡片的展示决策（HCT-425）。
 *
 * 家庭人脸 1:N 登录只在本机绑定的家庭内匹配、不跨家庭搜索，因此人脸 tab
 * 需要展示绑定状态；账号密码和家庭 PIN 登录与设备绑定无关，任何情况下
 * 都不显示该卡片。
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
      title: '本机还没有开启人脸登录',
      detail: '先用账号密码进入，再到「人脸凭证」页绑定本机家庭。',
      fallbackLabel: '改用账号密码登录',
    }
  }
  return {
    visible: true,
    bound: true,
    title: boundHouseholdName.trim() || '当前绑定家庭（仅在本机使用）',
    detail: '只在这个家庭里认人，不会跨家搜索。',
    fallbackLabel: '',
  }
}

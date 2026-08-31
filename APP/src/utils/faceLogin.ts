/**
 * 返回移动端刷脸登录在当前环境下不可用的原因。
 *
 * 这是一个纯门控函数：它只负责把未满足的前置条件解释给用户，
 * 不会请求摄像头、上传图像，也不会在本地保存任何生物特征。
 */
export function faceLoginDisabledReason(input: {
  thresholdCalibrated: boolean
  cameraSupported?: boolean
  cameraPermission?: 'granted' | 'denied' | 'prompt'
}): string {
  if (!input.thresholdCalibrated) {
    return '教学演示级阈值尚未完成现场标定，刷脸登录暂未开放。'
  }
  if (input.cameraSupported === false) {
    return '当前设备不支持摄像头刷脸，请改用账号密码或家庭 PIN。'
  }
  if (input.cameraPermission === 'denied') {
    return '摄像头权限未授权，已停止刷脸流程；请改用账号密码或家庭 PIN。'
  }
  return ''
}

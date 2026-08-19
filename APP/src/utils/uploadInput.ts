export const MAX_MEDICINE_IMAGE_BYTES = 10 * 1024 * 1024

export type LocalFileValidation =
  | { ok: true }
  | { ok: false; message: string }

/** Validates input before any health-image request leaves the device. */
export function validateMedicineImage(file: File): LocalFileValidation {
  if (!file.type.startsWith('image/')) {
    return { ok: false, message: '请选择图片文件，当前文件格式不支持识别。' }
  }
  if (file.size <= 0) {
    return { ok: false, message: '所选图片为空，请重新拍摄或从相册选择。' }
  }
  if (file.size > MAX_MEDICINE_IMAGE_BYTES) {
    return { ok: false, message: '图片超过 10 MiB，未上传。请压缩图片或重新拍摄后再试。' }
  }
  return { ok: true }
}

export function imageInputUnavailableMessage(): string {
  return '当前设备无法直接调用相机。你仍可从相册或文件中选择图片，页面不会提交空请求。'
}

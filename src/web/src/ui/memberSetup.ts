export const MEMBER_ACTOR_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/

export function memberSetupValidationMessage(displayName: string, actorId: string): string {
  if (!displayName.trim()) return '请填写家人称呼。'
  if (!MEMBER_ACTOR_ID_PATTERN.test(actorId.trim())) {
    return '请填写由字母、数字、点、下划线、冒号或短横线组成的登录名。'
  }
  return ''
}

export function canSubmitMemberSetup(
  displayName: string,
  actorId: string,
  saving: boolean,
): boolean {
  return !saving && memberSetupValidationMessage(displayName, actorId) === ''
}

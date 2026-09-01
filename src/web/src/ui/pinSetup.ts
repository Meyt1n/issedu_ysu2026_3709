/** 登录设置页：每位家人第一次保存 PIN 后锁定，之后只能点「修改」再提交。 */

export type PinRowState = {
  pin: string
  confirm: string
  error: string
  saved: boolean
  editing: boolean
}

export function emptyPinRow(): PinRowState {
  return { pin: '', confirm: '', error: '', saved: false, editing: false }
}

export function pinRowIsLocked(row: PinRowState | undefined): boolean {
  return Boolean(row?.saved && !row.editing)
}

export function pinRowCanSubmit(row: PinRowState | undefined): boolean {
  if (!row || pinRowIsLocked(row)) return false
  return /^\d{6}$/.test(row.pin) && row.pin === row.confirm
}

export function pinRowSubmitLabel(row: PinRowState | undefined, saving: boolean): string {
  if (saving) return row?.saved ? '正在保存修改' : '正在保存'
  return row?.saved ? '保存修改' : '保存'
}

export function beginPinEdit(row: PinRowState): void {
  row.editing = true
  row.pin = ''
  row.confirm = ''
  row.error = ''
}

export function cancelPinEdit(row: PinRowState): void {
  row.editing = false
  row.pin = ''
  row.confirm = ''
  row.error = ''
}

export function markPinSaved(row: PinRowState): void {
  row.saved = true
  row.editing = false
  row.pin = ''
  row.confirm = ''
  row.error = ''
}

/** 用服务端「已配置」名单标记行；正在修改的行不打断输入。永不回填 PIN。 */
export function markConfiguredPinRows(
  rows: Record<string, PinRowState>,
  configuredActorIds: readonly string[],
): void {
  for (const actorId of configuredActorIds) {
    const row = rows[actorId] ?? (rows[actorId] = emptyPinRow())
    if (row.editing) continue
    row.saved = true
    row.pin = ''
    row.confirm = ''
  }
}

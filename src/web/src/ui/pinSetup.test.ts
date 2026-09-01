import { describe, expect, it } from 'vitest'

import {
  beginPinEdit,
  cancelPinEdit,
  emptyPinRow,
  markConfiguredPinRows,
  markPinSaved,
  pinRowCanSubmit,
  pinRowIsLocked,
  pinRowSubmitLabel,
} from './pinSetup'

describe('pin setup row state (HCT-511)', () => {
  it('locks the row after the first save so a second save is not offered', () => {
    const row = emptyPinRow()
    row.pin = '123456'
    row.confirm = '123456'
    expect(pinRowCanSubmit(row)).toBe(true)
    expect(pinRowSubmitLabel(row, false)).toBe('保存')

    markPinSaved(row)

    expect(row.pin).toBe('')
    expect(row.confirm).toBe('')
    expect(pinRowIsLocked(row)).toBe(true)
    expect(pinRowCanSubmit(row)).toBe(false)
    expect(pinRowSubmitLabel(row, false)).toBe('保存修改')
  })

  it('allows a later change only after 修改, and cancel returns to locked', () => {
    const row = emptyPinRow()
    markPinSaved(row)
    beginPinEdit(row)

    expect(pinRowIsLocked(row)).toBe(false)
    expect(pinRowCanSubmit(row)).toBe(false)
    row.pin = '654321'
    row.confirm = '654321'
    expect(pinRowCanSubmit(row)).toBe(true)
    expect(pinRowSubmitLabel(row, false)).toBe('保存修改')

    cancelPinEdit(row)
    expect(pinRowIsLocked(row)).toBe(true)
    expect(row.pin).toBe('')
  })

  it('marks server-configured actors as already set without echoing a PIN', () => {
    const rows: Record<string, ReturnType<typeof emptyPinRow>> = { grandpa: emptyPinRow() }
    rows.grandpa.pin = '111111'
    markConfiguredPinRows(rows, ['grandpa', 'grandma'])

    expect(rows.grandpa.saved).toBe(true)
    expect(rows.grandpa.pin).toBe('')
    expect(rows.grandma?.saved).toBe(true)
    expect(rows.grandma?.pin).toBe('')
    expect(pinRowIsLocked(rows.grandpa)).toBe(true)
  })

  it('does not wipe an in-progress edit when refreshing configured status', () => {
    const rows = { grandpa: emptyPinRow() }
    markPinSaved(rows.grandpa)
    beginPinEdit(rows.grandpa)
    rows.grandpa.pin = '222222'
    rows.grandpa.confirm = '222222'
    markConfiguredPinRows(rows, ['grandpa'])

    expect(rows.grandpa.editing).toBe(true)
    expect(rows.grandpa.pin).toBe('222222')
  })
})

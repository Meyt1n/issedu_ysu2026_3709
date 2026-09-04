import { describe, expect, it } from 'vitest'

import { resolvePetMenuPlacement } from './petMenuPlacement'

const viewport = { width: 1280, height: 720 }
const menu = { width: 246, height: 350 }

describe('resolvePetMenuPlacement', () => {
  it('places the menu below a pet near the top', () => {
    expect(resolvePetMenuPlacement(
      { top: 20, right: 120, bottom: 116, left: 20 },
      viewport,
      menu,
    )).toEqual({ vertical: 'below', horizontal: 'left' })
  })

  it('places the menu above a pet near the bottom', () => {
    expect(resolvePetMenuPlacement(
      { top: 600, right: 1260, bottom: 696, left: 1160 },
      viewport,
      menu,
    )).toEqual({ vertical: 'above', horizontal: 'right' })
  })

  it('chooses the larger vertical space when neither side fully fits', () => {
    expect(resolvePetMenuPlacement(
      { top: 180, right: 710, bottom: 276, left: 610 },
      { width: 900, height: 430 },
      menu,
    ).vertical).toBe('above')
  })
})

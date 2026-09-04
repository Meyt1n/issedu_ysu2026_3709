export type PetMenuVertical = 'above' | 'below'
export type PetMenuHorizontal = 'left' | 'right'

export interface PetMenuRect {
  top: number
  right: number
  bottom: number
  left: number
}

export interface PetMenuViewport {
  width: number
  height: number
}

export interface PetMenuSize {
  width: number
  height: number
}

export interface PetMenuPlacement {
  vertical: PetMenuVertical
  horizontal: PetMenuHorizontal
}

const EDGE_GAP = 10
const PET_GAP = 12

/**
 * 让桌宠快捷栏优先完整出现在视口内；上下都放不下时选择空间较大的一侧，
 * 菜单本身再通过 max-height 滚动，避免越出页面。
 */
export function resolvePetMenuPlacement(
  rect: PetMenuRect,
  viewport: PetMenuViewport,
  menu: PetMenuSize,
): PetMenuPlacement {
  const spaceAbove = rect.top - PET_GAP
  const spaceBelow = viewport.height - rect.bottom - PET_GAP
  const vertical: PetMenuVertical = (
    spaceBelow >= menu.height || (spaceBelow > spaceAbove && spaceAbove < menu.height)
  ) ? 'below' : 'above'

  const fitsFromLeft = rect.left + menu.width <= viewport.width - EDGE_GAP
  const fitsFromRight = rect.right - menu.width >= EDGE_GAP
  const horizontal: PetMenuHorizontal = fitsFromLeft || !fitsFromRight ? 'left' : 'right'

  return { vertical, horizontal }
}

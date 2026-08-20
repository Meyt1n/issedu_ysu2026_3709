export function focusRouteMain(title: string, root: ParentNode = document): boolean {
  const main = root.querySelector<HTMLElement>('main#main')
  if (!main) return false

  main.tabIndex = -1
  main.setAttribute('aria-label', `${title}页面`)
  main.focus({ preventScroll: true })
  return true
}

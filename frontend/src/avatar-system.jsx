const avatarClasses = {
  父亲: 'avatar-elder-man',
  母亲: 'avatar-elder-woman',
  我: 'avatar-young-woman',
  孩子: 'avatar-child',
  father: 'avatar-elder-man',
  mother: 'avatar-elder-woman',
  self: 'avatar-young-woman',
  child: 'avatar-child',
}

export function avatarKeyFor(member) {
  return avatarClasses[member] ? member : '父亲'
}

export function FamilyAvatar({ memberKey = '父亲', name, className = '' }) {
  const avatarClass = avatarClasses[memberKey] || avatarClasses.父亲
  return <span className={`family-avatar ${avatarClass} ${className}`.trim()} role="img" aria-label={name || memberKey} />
}

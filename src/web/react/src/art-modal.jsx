import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export function ArtModal({ open, onClose, title, eyebrow, description, icon: Icon, children, actions, accent = 'blue', size = 'regular' }) {
  const cardRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const previousOverflow = document.body.style.overflow
    const handleKeyDown = event => {
      if (event.key === 'Escape') onClose()
    }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)
    const focusTimer = window.setTimeout(() => cardRef.current?.focus(), 20)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
      window.clearTimeout(focusTimer)
    }
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div className="art-modal-layer" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <section ref={cardRef} className={`art-modal-card ${accent} ${size}`} role="dialog" aria-modal="true" aria-labelledby="art-modal-title" tabIndex={-1}>
        <span className="art-modal-orbit orbit-a" />
        <span className="art-modal-orbit orbit-b" />
        <button className="art-modal-close" type="button" onClick={onClose} aria-label="关闭弹窗"><X size={18} /></button>
        <div className="art-modal-heading">
          <span className="art-modal-icon">{Icon ? <Icon size={22} /> : <span className="art-modal-spark" />}</span>
          <div>
            {eyebrow && <p className="art-modal-eyebrow">{eyebrow}</p>}
            <h2 id="art-modal-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
        </div>
        {children && <div className="art-modal-content">{children}</div>}
        {actions && <div className="art-modal-actions">{actions}</div>}
      </section>
    </div>,
    document.body,
  )
}

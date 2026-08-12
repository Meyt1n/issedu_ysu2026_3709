import { motion, useInView } from 'framer-motion'
import { useRef, type ReactNode } from 'react'

type BlurInProps = { children: ReactNode; className?: string }

export function BlurIn({ children, className = '' }: BlurInProps) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true })
  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ filter: 'blur(20px)', opacity: 0 }}
      animate={inView ? { filter: 'blur(0px)', opacity: 1 } : { filter: 'blur(20px)', opacity: 0 }}
      transition={{ duration: 1.2, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  )
}

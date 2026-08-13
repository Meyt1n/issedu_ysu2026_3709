import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './dashboard-color-overrides.css'
import './core-pages.css'
import './avatar-system.css'
import './motion-theme.css'
import './art-modal.css'
import './page-art.css'
import './component-elements.css'
import App from './App'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

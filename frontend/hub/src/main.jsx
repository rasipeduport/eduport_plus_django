import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ThemeProvider } from 'next-themes'
import './index.css'
import App from './App.jsx'
import { installLeaveGuard } from './hooks/use-leave-guard'

// Before <BrowserRouter> adds its own listener, so a page can hold Back and Forward (hooks/use-leave-guard).
installLeaveGuard()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <App />
    </ThemeProvider>
  </StrictMode>,
)

import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import './dashboard.css'
import './leads.css'
import './outreach.css'
import './analytics.css'
import './brand.css'
import './module2.css'
import './landing.css'
import './workspace.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>,
)

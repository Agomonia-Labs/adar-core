import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// Note: StrictMode removed — it causes double API calls in development
// which results in duplicate chat responses and double usage increments
ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
)
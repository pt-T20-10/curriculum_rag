import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute } from './components/ProtectedRoute'
import { TextbookDetailPage } from './pages/TextbookDetailPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { DashboardPage } from './pages/DashboardPage'
import { CreateTextbookPage } from './pages/CreateTextbookPage'

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          
          {/* ⭐ NEW - Create new textbook */}
          <Route
            path="/create"
            element={
              <ProtectedRoute>
                <CreateTextbookPage />
              </ProtectedRoute>
            }
          />
          
          {/* ⭐ NEW - Resume existing textbook */}
          <Route
            path="/create/:textbookId"
            element={
              <ProtectedRoute>
                <CreateTextbookPage />
              </ProtectedRoute>
            }
          />
          
          {/* ⭐ View completed textbook PDF */}
          <Route
            path="/textbooks/:id"
            element={
              <ProtectedRoute>
                <TextbookDetailPage />
              </ProtectedRoute>
            }
          />
            
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
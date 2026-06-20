import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AdminRoute } from './components/AdminRoute'
import { TextbookDetailPage } from './pages/TextbookDetailPage'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'
import { DashboardPage } from './pages/DashboardPage'
import { CreateTextbookPage } from './pages/CreateTextbookPage'
import { AdminDashboardPage } from './pages/admin/AdminDashboardPage'
import { AdminUsersPage } from './pages/admin/AdminUsersPage'
import { AdminTextbooksPage } from './pages/admin/AdminTextbooksPage'
import { AdminLandingPage } from './pages/admin/AdminLandingPage'
import { AdminPlansPage } from './pages/admin/AdminPlansPage'
import { AdminPaymentsPage } from './pages/admin/AdminPaymentsPage'
import { AdminSystemConfigPage } from './pages/admin/AdminSystemConfigPage'
import { GoogleCallbackPage } from './pages/GoogleCallbackPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { LandingPage } from './pages/LandingPage'
import { ProfilePage } from './pages/ProfilePage'
import { PublicInfoPage } from './pages/PublicInfoPage'
import { SiteFooter } from './components/layout/SiteFooter'

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <div className="min-h-full flex flex-col">
          <div className="flex-1">
            <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          
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
            
          {/* Admin routes */}
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminDashboardPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/users"
            element={
              <AdminRoute>
                <AdminUsersPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/textbooks"
            element={
              <AdminRoute>
                <AdminTextbooksPage />
              </AdminRoute>
            }
          />

          <Route
            path="/admin/landing"
            element={
              <AdminRoute>
                <AdminLandingPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/plans"
            element={
              <AdminRoute>
                <AdminPlansPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/payments"
            element={
              <AdminRoute>
                <AdminPaymentsPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/config"
            element={
              <AdminRoute>
                <AdminSystemConfigPage />
              </AdminRoute>
            }
          />

          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <ProfilePage />
              </ProtectedRoute>
            }
          />

          {/* Google OAuth callback — no auth guard, handles its own token flow */}
          <Route path="/auth/callback" element={<GoogleCallbackPage />} />

          {/* Public landing page — no auth guard */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/privacy-policy" element={<PublicInfoPage type="privacy" />} />
          <Route path="/terms-of-service" element={<PublicInfoPage type="terms" />} />
          <Route path="/data-deletion" element={<PublicInfoPage type="deletion" />} />
          <Route path="/support" element={<PublicInfoPage type="support" />} />
          <Route path="/contact" element={<PublicInfoPage type="contact" />} />
            </Routes>
          </div>
          <SiteFooter />
        </div>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App

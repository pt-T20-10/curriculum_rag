import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { Button } from '../common/Button'

export function Navbar() {
  const { user, logout } = useAuth()

  return (
    <nav className="bg-white shadow-sm border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <Link to="/dashboard" className="flex items-center">
            <h1 className="text-xl font-bold text-primary">
              Hệ Thống Tạo Giáo Trình AI
            </h1>
          </Link>

          {/* Right side */}
          <div className="flex items-center gap-4">
            {/* User info - clickable → dashboard */}
            <Link to="/dashboard" className="hidden sm:block text-sm text-gray-600 hover:text-primary transition-colors">
              {user?.email}
            </Link>

            {/* Credits badge */}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-primary/10 rounded-full">
              <svg 
                className="w-5 h-5 text-primary" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
              >
                <path 
                  strokeLinecap="round" 
                  strokeLinejoin="round" 
                  strokeWidth={2} 
                  d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" 
                />
              </svg>
              <span className="font-semibold text-primary">
                {user?.credits || 0}
              </span>
            </div>

            {/* Logout button */}
            <Button
              variant="secondary"
              onClick={logout}
              className="text-sm"
            >
              Đăng xuất
            </Button>
          </div>
        </div>
      </div>
    </nav>
  )
}
import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { authAPI } from '../api/auth'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // ⭐ Load user function
  const loadUser = useCallback(async () => {
    const token = localStorage.getItem('token')
    
    if (!token) {
      setLoading(false)
      return
    }

    try {
      const response = await authAPI.me()
      setUser(response.data)
    } catch (error) {
      console.error('Failed to load user:', error)
      localStorage.removeItem('token')
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])


  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUser()
  }, [loadUser])

const login = async (identifier, password, rememberMe = false) => {
  console.log('🔵 AuthContext.login called')

  // Step 1: Login to get token
  const response = await authAPI.login(identifier, password, rememberMe)
  console.log('🔍 Login response:', response.data)
  
  const { access_token } = response.data
  
  if (!access_token) {
    throw new Error('No token received')
  }
  
  console.log('🔑 Token received')
  
  // Step 2: Save token FIRST
  localStorage.setItem('token', access_token)
  
  // Step 3: Load user info with token
  console.log('📡 Loading user info...')
  const userResponse = await authAPI.me()
  console.log('👤 User loaded:', userResponse.data)
  
  // Step 4: Set user in context
  setUser(userResponse.data)
  
  console.log('✅ Login complete')
  return userResponse.data
}

const register = async (email, password, fullName, username) => {
  console.log('🔵 AuthContext.register called')

  // Step 1: Register to get token
  const response = await authAPI.register(email, password, fullName, username)
  console.log('🔍 Register response:', response.data)
  
  const { access_token } = response.data
  
  if (!access_token) {
    throw new Error('No token received')
  }
  
  // Step 2: Save token
  localStorage.setItem('token', access_token)
  
  // Step 3: Load user info
  console.log('📡 Loading user info...')
  const userResponse = await authAPI.me()
  console.log('👤 User loaded:', userResponse.data)
  
  // Step 4: Set user
  setUser(userResponse.data)
  
  console.log('✅ Register complete')
  return userResponse.data
}

  const loginWithToken = async (token) => {
    localStorage.setItem('token', token)
    const userResponse = await authAPI.me()
    setUser(userResponse.data)
    return userResponse.data
  }

  const logout = () => {
    localStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, loginWithToken, logout, loadUser }}>
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
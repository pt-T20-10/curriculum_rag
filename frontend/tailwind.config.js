/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#3B82F6',
        secondary: '#10B981',
        danger: '#EF4444',
        warning: '#F59E0B',
        
        // Content type colors
        scholarly: '#8B5CF6',
        technical: '#3B82F6',
        practical: '#10B981',
        lifestyle: '#F59E0B',
        
        // Status colors
        pending: '#6B7280',
        generating: '#3B82F6',
        completed: '#10B981',
        failed: '#EF4444',
      },
    },
  },
  plugins: [],
}
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Light Mode Palette -- warm, friendly palette
        light: {
          bg: '#FFFBF5',
          card: '#FFFFFF',
          border: '#F0E4D4',
          primary: '#F97316',
          accent: '#10B981',
          success: '#10B981',
          warning: '#F59E0B',
          danger: '#EF4444',
          text: '#292524',
          muted: '#78716C',
        },
        // Dark Mode Palette -- warm, friendly palette
        dark: {
          bg: '#1C1917',
          card: '#292524',
          border: '#44403C',
          primary: '#FB923C',
          accent: '#34D399',
          success: '#34D399',
          warning: '#FBBF24',
          danger: '#F87171',
          text: '#FAFAF9',
          muted: '#A8A29E',
        }
      },
      borderRadius: {
        'xl': '16px',
        '2xl': '20px',
      }
    },
  },
  plugins: [],
}

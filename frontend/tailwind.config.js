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
        // Light Mode Palette
        light: {
          bg: '#F8FAFC',
          card: '#FFFFFF',
          border: '#E2E8F0',
          primary: '#2563EB',
          accent: '#6366F1',
          success: '#22C55E',
          warning: '#F59E0B',
          danger: '#EF4444',
          text: '#0F172A',
          muted: '#64748B',
        },
        // Dark Mode Palette
        dark: {
          bg: '#09090B',
          card: '#18181B',
          border: '#27272A',
          primary: '#60A5FA',
          accent: '#818CF8',
          success: '#22C55E',
          warning: '#F59E0B',
          danger: '#EF4444',
          text: '#FAFAFA',
          muted: '#A1A1AA',
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

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          base: 'var(--surface-base)',
          'gray-1': 'var(--surface-gray-1)',
          'gray-2': 'var(--surface-gray-2)',
          'gray-3': 'var(--surface-gray-3)',
          red: 'var(--surface-red-1)',
          scrim: 'var(--surface-scrim)',
        },
        ink: {
          white: 'var(--ink-white)',
          'gray-3': 'var(--ink-gray-3)',
          'gray-4': 'var(--ink-gray-4)',
          'gray-5': 'var(--ink-gray-5)',
          'gray-6': 'var(--ink-gray-6)',
          'gray-7': 'var(--ink-gray-7)',
          'gray-8': 'var(--ink-gray-8)',
          'gray-9': 'var(--ink-gray-9)',
          red: 'var(--ink-red-6)',
          green: 'var(--ink-green-7)',
          amber: 'var(--ink-amber-7)',
        },
        outline: {
          'gray-1': 'var(--outline-gray-1)',
          'gray-2': 'var(--outline-gray-2)',
          'gray-3': 'var(--outline-gray-3)',
          'gray-4': 'var(--outline-gray-4)',
          red: 'var(--outline-red-2)',
        },
        primary: {
          DEFAULT: 'var(--primary-6)',
          1: 'var(--primary-1)',
          2: 'var(--primary-2)',
          3: 'var(--primary-3)',
          5: 'var(--primary-5)',
          6: 'var(--primary-6)',
          7: 'var(--primary-7)',
        },
      },
      borderColor: {
        DEFAULT: 'var(--outline-gray-1)',
      },
      borderRadius: {
        1: 'var(--radius-1)',
        2: 'var(--radius-2)',
        3: 'var(--radius-3)',
        4: 'var(--radius-4)',
        5: 'var(--radius-5)',
        6: 'var(--radius-6)',
        7: 'var(--radius-7)',
      },
      boxShadow: {
        sm: 'var(--elevation-sm)',
        DEFAULT: 'var(--elevation-base)',
        md: 'var(--elevation-md)',
      },
      fontFamily: {
        sans: ['"Geist"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        }
      },
      animation: {
        'fade-in-up': 'fade-in-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        'fade-in': 'fade-in 0.3s ease-out forwards',
        'scale-in': 'scale-in 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards',
      }
    },
  },
  plugins: [],
}

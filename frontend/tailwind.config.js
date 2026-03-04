/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    darkMode: 'class', // We will force dark mode globally in index.html, but this enables the class strategy
    theme: {
        extend: {
            colors: {
                background: '#0B0F19', // Obsidian Navy Base
                surface: '#121A2F',    // Slightly lighter for cards
                surfaceHover: '#1A2542',
                border: '#1F2937',     // Subtle borders
                primary: {
                    DEFAULT: '#3B82F6',  // Blue primary
                    light: '#60A5FA',
                    dark: '#2563EB',
                },
                success: {
                    DEFAULT: '#10B981',  // Emerald Green
                    light: '#34D399',
                    dark: '#059669',
                },
                danger: {
                    DEFAULT: '#EF4444',  // Crimson Red
                    light: '#F87171',
                    dark: '#DC2626',
                },
                warning: {
                    DEFAULT: '#F59E0B',  // Amber
                    light: '#FBBF24',
                    dark: '#D97706',
                }
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', 'sans-serif'],
                mono: ['JetBrains Mono', 'Menlo', 'monospace'],
            },
            animation: {
                'fade-in': 'fadeIn 0.3s ease-out',
                'slide-up': 'slideUp 0.4s ease-out',
                'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            },
            keyframes: {
                fadeIn: {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
                slideUp: {
                    '0%': { opacity: '0', transform: 'translateY(10px)' },
                    '100%': { opacity: '1', transform: 'translateY(0)' },
                }
            }
        },
    },
    plugins: [],
}

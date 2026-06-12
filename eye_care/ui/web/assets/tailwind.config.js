/** @type {import('tailwindcss').Config} */

module.exports = {
  content: {
    relative: true,
    files: [
      '../index.html',
      '../rest/index.html',
      '../notify/index.html',
      './app.js',
      './scripts/*.js',
      './rest/*.js',
    ],
  },
  safelist: [
    // All possible bg-dark shades used dynamically
    { pattern: /bg-dark-(100|200|300|400)/ },
    { pattern: /bg-dark-(200)\/95/ },
    { pattern: /bg-dark-(300)\/50/ },
    // Border patterns
    { pattern: /border-(white|red-500|slate-900|dark)/ },
    { pattern: /border-(white|red-500)\/\d+/ },
    // Text colors
    { pattern: /text-(white|gray-300|gray-400|gray-500|primary)/ },
    // Dashboard
    'dashboard-card', 'dashboard-card--kpi', 'dashboard-card--row',
    'dashboard-card-cell', 'dashboard-card-label', 'dashboard-card-label-sm',
    'dashboard-card-value', 'dashboard-card-value-sm', 'dashboard-action-bar',
    // Panels
    'panel-gradient', 'panel-gradient-left', 'panel-inner',
    // Calendar
    'calendar-grid', 'calendar-month-box', 'calendar-picker-panel',
    'calendar-hint-nowrap',
    // Charts
    'app-chart-row',
    // Modals
    'animate-slide-up',
    // Scrollbar
    'scrollbar-theme',
    // Inputs
    'input-primary',
    // Tabs
    'tab-active', 'tab-inactive',
    // Title bar
    'titlebar-btn', 'titlebar-btn-close',
    // Pie
    'pie-top-lines', 'pie-top-line', 'pie-dot', 'pie-line-text',
    // Data badges
    'data-badge', 'data-badge-paused',
    // View tabs
    'view-tabs',
    // Drag
    'pywebview-drag-region',
  ],
  theme: {
    extend: {
      colors: {
        primary: '#3B82F6',
        secondary: '#1E40AF',
        dark: {
          100: '#1E293B',
          200: '#0F172A',
          300: '#0B1120',
          400: '#070D19',
        },
        accent: '#60A5FA',
        success: '#10B981',
        warning: '#F59E0B',
        danger: '#EF4444',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      boxShadow: {
        'inner-light': 'inset 0 2px 4px 0 rgba(255, 255, 255, 0.05)',
        'glow': '0 0 15px rgba(59, 130, 246, 0.5)',
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.2), 0 2px 4px -1px rgba(0, 0, 0, 0.1)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-down': 'slideDown 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'slide-in-left': 'slideInLeft 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(20px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideInLeft: {
          '0%': { transform: 'translateX(-20px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
      },
    },
  },
  corePlugins: {
    preflight: false,
  },
}

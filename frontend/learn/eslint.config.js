import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      { plugins: { 'react-hooks': reactHooks }, rules: reactHooks.configs.recommended.rules },
      { plugins: { 'react-refresh': reactRefresh }, rules: { 'react-refresh/only-export-components': ['warn', { allowConstantExport: true }] } },
    ],
    rules: { 'no-unused-vars': ['error', { varsIgnorePattern: '^(?:[A-Z_]|motion$)', argsIgnorePattern: '^(?:[A-Z_]|motion$)' }] },
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
])

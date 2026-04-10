import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

export default [
  {
    ignores: [
      "services/frontend/dist/**",
      "services/frontend/node_modules/**",
      "services/backend/**",
      ".venv/**"
    ]
  },
  js.configs.recommended,
  {
    files: ["services/frontend/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: {
          jsx: true
        }
      },
      globals: {
        ...globals.browser,
        ...globals.node
      }
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-unused-vars": ["warn", { "argsIgnorePattern": "^_" }],
      "react-refresh/only-export-components": ["warn", { "allowConstantExport": true }]
    }
  }
];

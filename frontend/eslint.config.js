import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "playwright-report", "test-results"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Privacy (DESIGN §8.5): no browser persistence of profile data in either mode.
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "No browser storage of user data (DESIGN §8.5)." },
        { name: "sessionStorage", message: "No browser storage of user data (DESIGN §8.5)." },
        { name: "indexedDB", message: "No browser storage of user data (DESIGN §8.5)." },
      ],
    },
  },
);

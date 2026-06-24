import nextConfig from "eslint-config-next";

/** @type {import('eslint').Linter.Config[]} */
const eslintConfig = [
  ...nextConfig,
  {
    rules: {
      // Async data-fetching functions inside useEffect are standard React pattern.
      // The rule fires a false positive when calling an async wrapper (not setState directly).
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default eslintConfig;

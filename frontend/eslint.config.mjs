import next from "eslint-config-next";

export default [
  ...next,
  { ignores: [".next/**", "src/lib/api-types.ts"] },
  // Loading persisted state (localStorage/session) in an effect is intentional here.
  { rules: { "react-hooks/set-state-in-effect": "off" } },
];

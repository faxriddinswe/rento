import next from "eslint-config-next";

export default [...next, { ignores: [".next/**", "src/lib/api-types.ts"] }];

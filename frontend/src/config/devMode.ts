export const isDevEnvironment = Boolean(
  import.meta.env.DEV || import.meta.env.MODE === 'test'
)

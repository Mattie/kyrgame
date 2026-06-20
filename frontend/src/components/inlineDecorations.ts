export type InlineDecorationPolicy = {
  players?: boolean
  creatures?: boolean
  transformations?: boolean
  groundObjects?: boolean
  gemstones?: boolean
}

export type ResolvedInlineDecorationPolicy = Required<InlineDecorationPolicy>

export const INLINE_DECORATION_ALL: ResolvedInlineDecorationPolicy = {
  players: true,
  creatures: true,
  transformations: true,
  groundObjects: true,
  gemstones: true,
}

export const INLINE_DECORATION_NONE: ResolvedInlineDecorationPolicy = {
  players: false,
  creatures: false,
  transformations: false,
  groundObjects: false,
  gemstones: false,
}

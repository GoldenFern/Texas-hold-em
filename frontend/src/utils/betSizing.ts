export interface BetSizingContext {
  currentBet: number
  toCall: number
  potTotal: number
  minBet: number
  maxBet: number
}

/** 金额是本街下注总额；加注比例按跟注后的底池计算。 */
export function potFractionAmount(context: BetSizingContext, fraction: number): number {
  const target = context.currentBet + context.toCall
    + Math.round((context.potTotal + context.toCall) * fraction)
  return Math.min(context.maxBet, Math.max(context.minBet, target))
}

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { potFractionAmount } from '../src/utils/betSizing.ts'

const context = { currentBet: 5, toCall: 15, potTotal: 45, minBet: 30, maxBet: 1000 }

test('half-pot raise includes the call and chips already committed', () => {
  assert.equal(potFractionAmount(context, .5), 50)
})

test('three-quarter and pot raises use the pot after calling', () => {
  assert.equal(potFractionAmount(context, .75), 65)
  assert.equal(potFractionAmount(context, 1), 80)
})

test('opening bet sizes use the current pot without adding a call', () => {
  assert.equal(potFractionAmount({ ...context, currentBet: 0, toCall: 0, potTotal: 120 }, .5), 60)
})

test('short stacks and pot-limit bounds cap the requested size', () => {
  assert.equal(potFractionAmount({ ...context, maxBet: 45 }, 1), 45)
})

test('minimum and fixed-limit sizes stay legal', () => {
  assert.equal(potFractionAmount({ ...context, minBet: 100 }, .5), 100)
  assert.equal(potFractionAmount({ ...context, minBet: 30, maxBet: 30 }, 1), 30)
})

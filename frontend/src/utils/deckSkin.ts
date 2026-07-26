/** 牌组皮肤注册表与本地偏好（承接 CONTEXT.md 域语言,替代旧 deck.js）。 */

export interface DeckSkin {
  id: string
  label: string
  ext: string
  back: string
  faceStyle: 'prefix2' | 'suffix2'
}

export const DECK_SKINS: readonly DeckSkin[] = [
  { id: 'aguilar', label: '经典 PNG', ext: 'png', back: 'back.png', faceStyle: 'prefix2' },
  { id: 'aguilar_old', label: '矢量 SVG', ext: 'svg', back: 'back.png', faceStyle: 'suffix2' },
]

export const DECK_STORAGE_KEY = 'thp_card_deck'

const RANK_FILE: Record<string, string> = {
  A: 'ace', '2': '2', '3': '3', '4': '4', '5': '5', '6': '6',
  '7': '7', '8': '8', '9': '9', T: '10',
  J: 'jack2', Q: 'queen2', K: 'king2',
}

const SUIT_FILE: Record<string, string> = {
  '♠': 'spades', '♥': 'hearts', '♦': 'diamonds', '♣': 'clubs',
  s: 'spades', h: 'hearts', d: 'diamonds', c: 'clubs',
}

export function loadPreferredSkin(): DeckSkin {
  const saved = localStorage.getItem(DECK_STORAGE_KEY)
  return DECK_SKINS.find((d) => d.id === saved) ?? DECK_SKINS[0]
}

export function savePreferredSkin(id: string): void {
  localStorage.setItem(DECK_STORAGE_KEY, id)
}

/** 服务器牌串（如 "A♠"、"T♥"）→ 当前皮肤的图片路径;"??"/空 → null。 */
export function cardImagePath(cardStr: string | null | undefined, skin: DeckSkin): string | null {
  if (!cardStr || cardStr === '??') return null
  let rank = cardStr[0]
  const suitChar = cardStr[cardStr.length - 1]
  if (rank === '1' && cardStr.length >= 3) rank = 'T'
  const fileRank = RANK_FILE[rank]
  const fileSuit = SUIT_FILE[suitChar]
  if (!fileRank || !fileSuit) return null
  const isFace = rank === 'J' || rank === 'Q' || rank === 'K'
  const stem = isFace && skin.faceStyle === 'suffix2'
    ? `${fileRank.replace(/2$/, '')}_of_${fileSuit}2`
    : `${fileRank}_of_${fileSuit}`
  return `/static/img/cards/${skin.id}/${stem}.${skin.ext}`
}

export function cardBackPath(skin: DeckSkin): string {
  return `/static/img/cards/${skin.id}/${skin.back}`
}

/** 花色是否为红色（文本渲染回退用）。 */
export function isRedSuit(cardStr: string): boolean {
  const suit = cardStr[cardStr.length - 1]
  return suit === '♥' || suit === '♦' || suit === 'h' || suit === 'd'
}

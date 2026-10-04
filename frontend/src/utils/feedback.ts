/** Optional audio/haptic feedback. Defaults are off and respect reduced motion. */

const SOUND_KEY = 'thp_sound_enabled'
const HAPTICS_KEY = 'thp_haptics_enabled'

export function loadFeedbackPreference(key: string): boolean {
  return localStorage.getItem(key) === '1'
}

export function saveFeedbackPreference(key: string, enabled: boolean): void {
  localStorage.setItem(key, enabled ? '1' : '0')
}

function reducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

export function playActionCue(enabled: boolean): void {
  if (!enabled || reducedMotion()) return
  try {
    const AudioContextClass = window.AudioContext
      || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextClass) return
    const context = new AudioContextClass()
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.frequency.value = 560
    gain.gain.setValueAtTime(.04, context.currentTime)
    gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + .08)
    oscillator.connect(gain).connect(context.destination)
    oscillator.start()
    oscillator.stop(context.currentTime + .08)
    oscillator.addEventListener('ended', () => { void context.close() }, { once: true })
  } catch {
    // Feedback is optional and must never block an action.
  }
}

export function triggerActionHaptic(enabled: boolean): void {
  if (!enabled || reducedMotion() || !('vibrate' in navigator)) return
  try {
    navigator.vibrate(12)
  } catch {
    // Some browsers expose vibrate but reject it outside a user gesture.
  }
}

export { SOUND_KEY, HAPTICS_KEY }

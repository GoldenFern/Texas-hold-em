# Frontend interaction research and reuse boundary

This project reimplements interaction patterns in the existing Vue 3 and CSS
stack. It does not copy React, Next.js, Framer Motion components, card art,
textures, sounds, models, or screenshots.

## References

- [Pip Web](https://github.com/playpip/pip-web) is MIT licensed. We use its
  product patterns as inspiration for bet sizing presets, stable action areas,
  replay transport, visible-state coaching, and optional sound/haptics. Any
  copied source code would require preserving its copyright and license.
- [Texas Hold'em Agents](https://github.com/Pangolin112/Texas_Holdem_Agents) is
  MIT licensed. We use its immediate arithmetic advice followed by asynchronous
  LLM coaching model as a product reference.
- [HoldemSolver](https://github.com/kmurf1999/HoldemSolver) is MIT licensed.
  Its range matrix and equity heatmap are deferred to the advanced strategy
  panel.
- [OddSlingers](https://github.com/Monadical-SAS/oddslingers.poker) is licensed
  under LGPL-2.1. Its action timeline, server-time timer, and play-by-play are
  architectural references only. No OddSlingers source is copied here without
  a separate license review.
- [Poker IO](https://github.com/itaylayzer/Poker) is a visual reference for a
  possible future 3D mode. Its third-party assets are not reused.

All new implementation in this repository uses native Vue transitions,
`requestAnimationFrame`/browser timers, and the existing protocol. Review this
file before importing any third-party implementation or media asset.

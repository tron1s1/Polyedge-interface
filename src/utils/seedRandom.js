// Simple seeded PRNG (mulberry32)
export function createRng(seed) {
  let s = seed | 0
  return function () {
    s = (s + 0x6D2B79F5) | 0
    let t = Math.imul(s ^ (s >>> 15), 1 | s)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Generate random number in range
export function randRange(rng, min, max) {
  return min + rng() * (max - min)
}

// Pick random element
export function randPick(rng, arr) {
  return arr[Math.floor(rng() * arr.length)]
}

// Generate random date within range
export function randDate(rng, startDaysAgo, endDaysAgo = 0) {
  const now = Date.now()
  const start = now - startDaysAgo * 86400000
  const end = now - endDaysAgo * 86400000
  return new Date(start + rng() * (end - start))
}

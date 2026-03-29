import { createRng, randRange } from '../utils/seedRandom'

export function getTaxSummary() {
  return {
    financialYear: '2025-26',
    totalGains: 184200,
    totalLosses: 12400,
    netTaxable: 171800,
    tax30pct: 51540,
    tdsAutoDeducted: 8420,
    remainingTax: 43120,
    taxReserveBalance: 52400,
    covered: true,
  }
}

export function getAdvanceTaxSchedule() {
  return [
    { quarter: 'Q1', dueDate: '15 June 2025',  pct: 15, amount: 7731,  cumAmount: 7731,  status: 'paid' },
    { quarter: 'Q2', dueDate: '15 Sep 2025',   pct: 45, amount: 15462, cumAmount: 23193, status: 'due', remaining: 15462 },
    { quarter: 'Q3', dueDate: '15 Dec 2025',   pct: 75, amount: 15462, cumAmount: 38655, status: 'upcoming' },
    { quarter: 'Q4', dueDate: '15 Mar 2026',   pct: 100, amount: 12885, cumAmount: 51540, status: 'upcoming' },
  ]
}

export function getTodayTaxEvents() {
  const rng = createRng(9901)
  return [
    { source: 'Flash loan profit',  usd: 84.20,  inr: 7073,  tax: 2122,  reinvestedUsd: 56 },
    { source: 'Triangular arb',     usd: 15.20,  inr: 1277,  tax: 383,   reinvestedUsd: 10 },
    { source: 'Funding rate',       usd: 18.40,  inr: 1546,  tax: 464,   reinvestedUsd: 12 },
    { source: 'NSE options',        usd: null,    inr: 2340,  tax: 702,   reinvestedInr: 1638 },
  ]
}

export function getDubaiMilestone() {
  return {
    targetUsdc: 50000,
    currentUsdc: 5240,
    pct: 10.5,
    dailyGeneration: 108,
    estimatedMonths: 8.4,
    description: 'Dubai freelance visa + 6 months expenses',
    benefit: '0% crypto tax, flash loans scale 10x',
  }
}

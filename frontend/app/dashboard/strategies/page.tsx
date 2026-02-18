'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { AllocationManager } from '@/components/strategies/AllocationManager'
import { StrategyXPBar } from '@/components/strategies/StrategyXPBar'
import { StrategyBadges } from '@/components/strategies/StrategyBadges'
import { Card } from '@/components/ui/Card'

interface Strategy {
  code: string
  name: string
  status: 'active' | 'paused' | 'stopped'
  allocation_pct: number
  auto_allocation?: boolean
  win_rate: number
  profit_factor: number
  total_trades: number
  total_profit: number
}

interface XPData {
  code: string
  name: string
  total_xp: number
  level: number
  level_name: string
  level_color: string
  xp_to_next_level: number
  xp_current_level: number
  xp_needed_for_level: number
  progress_pct: number
  total_trades: number
  wins: number
  win_rate: number
  best_streak: number
  current_streak: number
  current_streak_type: string
  skills_unlocked?: string[]
  xp_history?: Array<{ xp: number; total_xp: number; level: number; won: boolean }>
  badges: any[]
}

interface RLStats {
  total_trades_analyzed: number
  exploration_rate: number
  active_strategies: number
  last_update?: string
}

export default function StrategiesPage() {
  const router = useRouter()
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [xpData, setXpData] = useState<Record<string, XPData>>({})
  const [rlStats, setRlStats] = useState<RLStats | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setIsLoading(true)
        setError(null)
        const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
        const headers: Record<string, string> = { 'Accept': 'application/json' }
        if (token) headers['Authorization'] = `Bearer ${token}`

        // Fetch strategies, XP data, and RL stats in parallel
        const [stratRes, xpRes, rlRes] = await Promise.allSettled([
          fetch('/api/strategies', { headers }),
          fetch('/api/brain/strategy-xp', { headers }),
          fetch('/api/brain/rl-stats', { headers }),
        ])

        // Process strategies
        if (stratRes.status === 'fulfilled') {
          if (!stratRes.value.ok) {
            if (stratRes.value.status === 401) {
              localStorage.removeItem('auth_token')
              window.location.href = '/login'
              return
            }
            throw new Error(`Failed to fetch strategies: ${stratRes.value.statusText}`)
          }
          const data = await stratRes.value.json()
          const normalized = (data || []).map((s: any) => ({
            ...s,
            status: (s.status || '').toLowerCase() as Strategy['status'],
          }))
          setStrategies(normalized)
        } else {
          throw new Error('Failed to fetch strategies')
        }

        // Process XP data
        if (xpRes.status === 'fulfilled' && xpRes.value.ok) {
          const data = await xpRes.value.json()
          setXpData(data || {})
        }

        // Process RL stats
        if (rlRes.status === 'fulfilled' && rlRes.value.ok) {
          const data = await rlRes.value.json()
          setRlStats(data || null)
        }
      } catch (err) {
        console.error('Error fetching strategies:', err)
        setError(err instanceof Error ? err.message : 'Failed to load strategies')
        setStrategies([])
      } finally {
        setIsLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleAllocationSave = (allocations: Record<string, number>) => {
    setStrategies(strategies.map(s => ({
      ...s,
      allocation_pct: allocations[s.code] || s.allocation_pct,
    })))
  }

  // Rank strategies by performance (profit, then win rate)
  const rankedStrategies = useMemo(() => {
    const sorted = [...strategies].sort((a, b) => {
      const profitDiff = (b.total_profit || 0) - (a.total_profit || 0)
      if (profitDiff !== 0) return profitDiff
      return (b.win_rate || 0) - (a.win_rate || 0)
    })
    const rankMap: Record<string, number> = {}
    sorted.forEach((s, i) => { rankMap[s.code] = i + 1 })
    return { sorted, rankMap }
  }, [strategies])

  const totalAllocation = strategies.reduce((sum, s) => sum + (s.allocation_pct || 0), 0)
  const activeCount = strategies.filter(s => s.status === 'active').length
  const totalWinRate = strategies.length > 0
    ? strategies.reduce((sum, s) => sum + (s.win_rate || 0), 0) / strategies.length
    : 0
  const totalProfit = strategies.reduce((sum, s) => sum + (s.total_profit || 0), 0)
  const hasAutoAllocation = strategies.some(s => s.auto_allocation)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-gray-400">Loading strategies...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-red-400">Error: {error}</div>
      </div>
    )
  }

  const hasStrategies = strategies && strategies.length > 0

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-100">Strategies</h1>
        <p className="text-gray-400 mt-2">Manage and monitor your trading strategies</p>
      </div>

      {!hasStrategies ? (
        /* Empty State */
        <Card className="p-8 text-center">
          <div className="text-gray-400">
            <p className="text-lg">No strategies loaded yet.</p>
            <p className="text-sm mt-2">The engine will register strategies as they run.</p>
          </div>
        </Card>
      ) : (
        <>
          {/* Summary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="p-4">
              <div className="text-sm text-gray-400">Active Strategies</div>
              <div className="text-2xl font-bold text-brand-accent-green mt-2">{activeCount}/{strategies.length}</div>
            </Card>
            <Card className="p-4">
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-400">Total Allocation</span>
                {/* Auto-allocation indicator */}
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                    hasAutoAllocation
                      ? 'bg-blue-500/15 text-blue-400 border border-blue-500/30'
                      : 'bg-gray-700/50 text-gray-500 border border-gray-600/30'
                  }`}
                >
                  {hasAutoAllocation ? 'AUTO' : 'MANUAL'}
                </span>
              </div>
              <div className={`text-2xl font-bold mt-2 ${totalAllocation <= 100 ? 'text-brand-accent-green' : 'text-brand-accent-red'}`}>
                {totalAllocation.toFixed(0)}%
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-sm text-gray-400">Avg Win Rate</div>
              <div className="text-2xl font-bold text-blue-400 mt-2">{(totalWinRate * 100).toFixed(1)}%</div>
            </Card>
            <Card className="p-4">
              <div className="text-sm text-gray-400">Total Profit (30d)</div>
              <div className={`text-2xl font-bold mt-2 ${totalProfit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${totalProfit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
            </Card>
          </div>

          {/* Brain Activity Card */}
          {rlStats && (
            <Card className="p-4">
              <div className="flex items-center gap-3">
                <span className="text-lg animate-brain-pulse">🧠</span>
                <div>
                  <div className="text-sm font-semibold text-gray-200">Brain Activity</div>
                  <div className="text-xs text-gray-500">Reinforcement learning engine</div>
                </div>
                <div className="ml-auto flex items-center gap-6">
                  <div className="text-right">
                    <div className="text-xs text-gray-500">Trades Analyzed</div>
                    <div className="text-sm font-bold text-purple-400">
                      {rlStats.total_trades_analyzed.toLocaleString()}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-gray-500">Exploration Rate</div>
                    <div className="text-sm font-bold text-cyan-400">
                      {(rlStats.exploration_rate * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-gray-500">Active Learners</div>
                    <div className="text-sm font-bold text-green-400">
                      {rlStats.active_strategies}
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Strategy Cards - Sorted by rank */}
          <div className="grid gap-4">
            {rankedStrategies.sorted.map(strategy => {
              const stratXP = xpData[strategy.code]
              const rank = rankedStrategies.rankMap[strategy.code]
              return (
                <Card
                  key={strategy.code}
                  className="p-6 cursor-pointer hover:border-gray-500 transition-all"
                >
                  <div
                    onClick={() => router.push(`/dashboard/strategies/${strategy.code}`)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          {/* Level Badge */}
                          {stratXP && (
                            <div
                              className="flex items-center justify-center w-9 h-9 rounded-full text-xs font-bold text-white shrink-0 relative"
                              style={{
                                backgroundColor: stratXP.level_color,
                                boxShadow: `0 0 8px ${stratXP.level_color}40`,
                              }}
                            >
                              {stratXP.level}
                              {/* Rank overlay */}
                              <div className="absolute -top-1 -right-1 flex items-center justify-center w-4 h-4 rounded-full text-[8px] font-bold text-white bg-gray-800 border border-gray-600">
                                #{rank}
                              </div>
                            </div>
                          )}
                          {/* If no XP data, still show rank */}
                          {!stratXP && (
                            <div className="flex items-center justify-center w-9 h-9 rounded-full text-xs font-bold text-gray-400 bg-gray-700 shrink-0">
                              #{rank}
                            </div>
                          )}
                          <div>
                            <h3 className="text-lg font-bold text-gray-100">{strategy.name}</h3>
                            {stratXP && (
                              <span
                                className="text-xs font-medium"
                                style={{ color: stratXP.level_color }}
                              >
                                {stratXP.level_name}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* XP Bar */}
                        {stratXP && (
                          <div className="mt-3">
                            <StrategyXPBar
                              data={stratXP}
                              compact
                              rank={rank}
                              rlActive={rlStats ? rlStats.active_strategies > 0 : false}
                              tradesAnalyzed={rlStats?.total_trades_analyzed}
                            />
                          </div>
                        )}

                        <div className="flex flex-wrap gap-4 mt-4">
                          <div>
                            <span className="text-xs text-gray-500">Status</span>
                            <p className="text-sm font-semibold mt-1 capitalize">
                              {strategy.status === 'active' && <span className="text-green-400">Active</span>}
                              {strategy.status === 'paused' && <span className="text-yellow-400">Paused</span>}
                              {strategy.status === 'stopped' && <span className="text-red-400">Stopped</span>}
                            </p>
                          </div>
                          <div>
                            <span className="text-xs text-gray-500">Allocation</span>
                            <div className="flex items-center gap-1.5 mt-1">
                              <p className="text-sm font-semibold text-brand-accent-green">{strategy.allocation_pct ?? '\u2014'}%</p>
                              {strategy.auto_allocation && (
                                <span className="text-[9px] font-bold px-1 py-px rounded bg-blue-500/15 text-blue-400 border border-blue-500/30">
                                  AUTO
                                </span>
                              )}
                            </div>
                          </div>
                          <div>
                            <span className="text-xs text-gray-500">Win Rate</span>
                            <p className="text-sm font-semibold text-blue-400 mt-1">
                              {strategy.win_rate !== undefined ? `${(strategy.win_rate * 100).toFixed(1)}%` : '\u2014'}
                            </p>
                          </div>
                          <div>
                            <span className="text-xs text-gray-500">Profit Factor</span>
                            <p className="text-sm font-semibold text-purple-400 mt-1">
                              {strategy.profit_factor !== undefined ? strategy.profit_factor.toFixed(2) : '\u2014'}
                            </p>
                          </div>
                          <div>
                            <span className="text-xs text-gray-500">Trades</span>
                            <p className="text-sm font-semibold text-gray-300 mt-1">{strategy.total_trades ?? '\u2014'}</p>
                          </div>
                        </div>

                        {/* Compact Badges */}
                        {stratXP && stratXP.badges && stratXP.badges.length > 0 && (
                          <div className="mt-3">
                            <StrategyBadges badges={stratXP.badges} compact />
                          </div>
                        )}
                      </div>
                      <div className="text-right ml-4 flex flex-col items-end gap-2">
                        <div>
                          <div className="text-xs text-gray-500">30d Profit</div>
                          <p className={`text-xl font-bold mt-1 ${(strategy.total_profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {strategy.total_profit !== undefined ? `$${strategy.total_profit.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '\u2014'}
                          </p>
                        </div>
                        {/* Arrow indicator for clickability */}
                        <div className="text-gray-500 mt-2">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                          </svg>
                        </div>
                      </div>
                    </div>
                  </div>
                </Card>
              )
            })}
          </div>

          {/* Allocation Manager */}
          <AllocationManager strategies={strategies} onSave={handleAllocationSave} />
        </>
      )}
    </div>
  )
}

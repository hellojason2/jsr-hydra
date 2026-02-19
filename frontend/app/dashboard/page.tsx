'use client'

import React, { useEffect, useState } from 'react'
import { AccountCard } from '@/components/dashboard/AccountCard'
import { EquityChart } from '@/components/dashboard/EquityChart'
import { RegimeCard } from '@/components/dashboard/RegimeCard'
import { StrategyCards } from '@/components/dashboard/StrategyCards'
import { RecentTrades } from '@/components/dashboard/RecentTrades'
import { SystemStatus } from '@/components/dashboard/SystemStatus'
import { SkeletonGrid } from '@/components/ui/Skeleton'

// Use relative URLs so requests go through Caddy reverse proxy (same origin)
// Do NOT use NEXT_PUBLIC_API_URL here -- it gets baked at build time as
// "http://localhost:8000" which resolves to the user's machine, not the VPS.

export default function DashboardPage() {
  const [dashboardData, setDashboardData] = useState<any>(null)
  const [healthData, setHealthData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  const fetchData = async () => {
    try {
      setError(null)

      // Fetch dashboard (requires auth) and health (public) in parallel
      const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
      const authHeaders: Record<string, string> = token
        ? { 'Authorization': `Bearer ${token}`, 'Accept': 'application/json' }
        : { 'Accept': 'application/json' }

      const [dashRes, healthRes] = await Promise.allSettled([
        fetch('/api/system/dashboard', { headers: authHeaders }),
        fetch('/api/system/health', { headers: { 'Accept': 'application/json' } }),
      ])

      if (dashRes.status === 'fulfilled') {
        if (dashRes.value.ok) {
          const data = await dashRes.value.json()
          setDashboardData(data)
        } else if (dashRes.value.status === 401 || dashRes.value.status === 403) {
          // Clear stale auth state and redirect to login
          localStorage.removeItem('auth_token')
          localStorage.removeItem('app-store')
          window.location.href = '/login'
          return
        } else if (!dashboardData) {
          // Only set error if we have no previous data (avoid overwriting good data on transient errors)
          setError(`Dashboard API returned ${dashRes.value.status}`)
        }
      } else if (!dashboardData) {
        setError('Failed to connect to dashboard API')
      }

      if (healthRes.status === 'fulfilled' && healthRes.value.ok) {
        const data = await healthRes.value.json()
        setHealthData(data)
      }

      setLastUpdate(new Date())
    } catch (err) {
      console.error('Error fetching data:', err)
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000) // Refresh every 10 seconds
    return () => clearInterval(interval)
  }, [])

  const handleRefresh = async () => {
    setLoading(true)
    await fetchData()
  }

  // Transform backend data to component props
  const accountProps = dashboardData?.account ? {
    balance: dashboardData.account.balance || 0,
    equity: dashboardData.account.equity || 0,
    freeMargin: dashboardData.account.free_margin || 0,
    marginLevel: dashboardData.account.margin_level || 0,
    drawdownPct: dashboardData.account.drawdown_pct || 0,
    profit: dashboardData.account.profit || 0,
    leverage: dashboardData.account.leverage || 0,
    currency: dashboardData.account.currency || 'USD',
    login: dashboardData.account.login,
    server: dashboardData.account.server,
  } : null

  const strategyProps = (dashboardData?.strategies || []).map((s: any) => ({
    name: s.name || `Strategy ${s.code}`,
    code: s.code,
    status: s.status || 'active',
    allocation: s.allocation_pct || 0,
    winRate: s.win_rate || 0,
    pnl: s.total_profit || 0,
    totalTrades: s.total_trades || 0,
    profitFactor: s.profit_factor || 0,
  }))

  const tradeProps = (dashboardData?.recent_trades || []).map((t: any) => ({
    id: t.id,
    time: t.opened_at || t.closed_at || '',
    symbol: t.symbol,
    direction: t.direction,
    lots: t.lots,
    entry: t.entry_price || 0,
    exit: t.exit_price || 0,
    pnl: t.net_profit ?? t.profit ?? 0,
    status: t.status,
  }))

  // Build system status from health check
  const systemProps = healthData ? {
    services: Object.entries(healthData.services || {}).map(([name, info]: [string, any]) => ({
      name: name.charAt(0).toUpperCase() + name.slice(1),
      status: info.status === 'connected' ? 'up' as const : 'down' as const,
    })),
    uptime: healthData.uptime_seconds || 0,
    version: healthData.version || '1.0.0',
    overallStatus: healthData.status,
    dryRun: healthData.trading?.dry_run,
    openPositions: healthData.trading?.open_positions || 0,
  } : null

  return (
    <div className="min-h-screen bg-brand-dark p-4 md:p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold text-gray-100">Dashboard</h1>
            <p className="text-gray-400 text-sm mt-1">
              {lastUpdate ? `Last updated: ${lastUpdate.toLocaleTimeString()}` : 'Loading...'}
              {dashboardData?.dry_run === false && (
                <span className="ml-2 text-brand-accent-green font-semibold">LIVE</span>
              )}
              {dashboardData?.dry_run === true && (
                <span className="ml-2 text-yellow-400 font-semibold">DRY RUN</span>
              )}
            </p>
          </div>
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="px-4 py-2 bg-brand-accent-green text-brand-dark rounded-lg font-semibold hover:bg-opacity-90 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {/* Error State */}
        {error && (
          <div className="mb-6 p-4 bg-red-900/20 border border-red-700/50 rounded-lg text-red-400">
            <p className="text-sm">{error}</p>
            <button
              onClick={handleRefresh}
              className="mt-2 text-xs text-red-300 hover:text-red-200 underline"
            >
              Try again
            </button>
          </div>
        )}

        {/* Loading State */}
        {loading && !dashboardData && !healthData ? (
          <SkeletonGrid />
        ) : (
          <>
            {/* Top Row: Account & Regime */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6 mb-6">
              <div className="lg:col-span-2">
                <AccountCard data={accountProps} />
              </div>
              <RegimeCard data={dashboardData?.regime} />
            </div>

            {/* Open Positions */}
            {(dashboardData?.positions?.length > 0) && (
              <div className="mb-6 p-4 bg-brand-panel border border-gray-700 rounded-lg">
                <h3 className="text-lg font-semibold text-gray-100 mb-3">Open Positions ({dashboardData.positions.length})</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-700">
                        <th className="px-3 py-2 text-left text-xs text-gray-400">Ticket</th>
                        <th className="px-3 py-2 text-left text-xs text-gray-400">Symbol</th>
                        <th className="px-3 py-2 text-left text-xs text-gray-400">Type</th>
                        <th className="px-3 py-2 text-right text-xs text-gray-400">Lots</th>
                        <th className="px-3 py-2 text-right text-xs text-gray-400">Open Price</th>
                        <th className="px-3 py-2 text-right text-xs text-gray-400">Current</th>
                        <th className="px-3 py-2 text-right text-xs text-gray-400">Profit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboardData.positions.map((pos: any) => (
                        <tr key={pos.ticket} className="border-b border-gray-800">
                          <td className="px-3 py-2 text-gray-300">{pos.ticket}</td>
                          <td className="px-3 py-2 font-semibold text-gray-100">{pos.symbol}</td>
                          <td className={`px-3 py-2 ${pos.type === 'BUY' ? 'text-brand-accent-green' : 'text-brand-accent-red'}`}>{pos.type}</td>
                          <td className="px-3 py-2 text-right text-gray-300">{pos.lots}</td>
                          <td className="px-3 py-2 text-right text-gray-400">{pos.price_open}</td>
                          <td className="px-3 py-2 text-right text-gray-400">{pos.price_current}</td>
                          <td className={`px-3 py-2 text-right font-semibold ${pos.profit >= 0 ? 'text-brand-accent-green' : 'text-brand-accent-red'}`}>
                            {pos.profit >= 0 ? '+' : ''}{pos.profit?.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Equity Chart */}
            <div className="mb-6">
              <EquityChart data={dashboardData?.equity_curve} />
            </div>

            {/* Strategies & System Status */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6 mb-6">
              <StrategyCards strategies={strategyProps.length > 0 ? strategyProps : undefined} />
              <SystemStatus data={systemProps} />
            </div>

            {/* Recent Trades */}
            <div>
              <RecentTrades trades={tradeProps.length > 0 ? tradeProps : undefined} />
            </div>

            {/* Footer Info */}
            <div className="mt-8 p-4 bg-brand-panel border border-gray-700 rounded-lg text-center text-gray-400 text-xs">
              <p>
                JSR Hydra v{dashboardData?.version || healthData?.version || '1.0.0'}
                {' '}&bull;{' '}Auto-refresh every 10 seconds
                {dashboardData?.system_status && ` \u2022 Status: ${dashboardData.system_status}`}
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

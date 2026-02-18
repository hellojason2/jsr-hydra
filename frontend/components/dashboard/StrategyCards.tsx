'use client'

import React from 'react'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'

interface Strategy {
  name: string
  code: string
  status: string
  allocation: number
  winRate: number
  pnl: number
  totalTrades?: number
  profitFactor?: number
}

interface StrategyCardsProps {
  strategies?: Strategy[]
  loading?: boolean
}

interface StrategyItemProps {
  strategy: Strategy
}

function StrategyItem({ strategy }: StrategyItemProps) {
  const statusMap: Record<string, 'success' | 'warning' | 'danger'> = {
    active: 'success',
    paused: 'warning',
    error: 'danger',
    stopped: 'danger',
  }
  const variant = statusMap[strategy.status] || 'warning'
  const isPnLPositive = strategy.pnl >= 0
  const winRatePercent = strategy.winRate > 1
    ? strategy.winRate.toFixed(1)
    : (strategy.winRate * 100).toFixed(1)

  return (
    <div className="bg-black/30 border border-gray-700 rounded-lg p-4 hover:border-gray-600 transition-all">
      <div className="flex justify-between items-start mb-3">
        <div>
          <p className="text-sm font-semibold text-gray-200">Strategy {strategy.code}</p>
          <p className="text-xs text-gray-400 mt-1">{strategy.name}</p>
        </div>
        <Badge variant={variant} dot>
          {strategy.status.charAt(0).toUpperCase() + strategy.status.slice(1)}
        </Badge>
      </div>

      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Allocation</span>
          <span className="font-semibold text-gray-100">{strategy.allocation}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">Win Rate</span>
          <span className="font-semibold text-gray-100">{winRatePercent}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-400">P&L</span>
          <span className={`font-semibold ${isPnLPositive ? 'text-brand-accent-green' : 'text-brand-accent-red'}`}>
            {isPnLPositive ? '+' : ''}{strategy.pnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        {strategy.totalTrades !== undefined && (
          <div className="flex justify-between">
            <span className="text-gray-400">Trades</span>
            <span className="font-semibold text-gray-100">{strategy.totalTrades}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export function StrategyCards({ strategies, loading = false }: StrategyCardsProps) {
  if (loading) {
    return (
      <Card title="Strategies">
        <div className="grid grid-cols-2 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 bg-gray-700/50 rounded animate-pulse" />
          ))}
        </div>
      </Card>
    )
  }

  if (!strategies || strategies.length === 0) {
    return (
      <Card title="Strategies">
        <p className="text-gray-400 text-sm">No strategies loaded yet.</p>
      </Card>
    )
  }

  return (
    <Card title="Strategies">
      <div className="grid grid-cols-2 gap-4">
        {strategies.map((strategy) => (
          <StrategyItem key={strategy.code} strategy={strategy} />
        ))}
      </div>
    </Card>
  )
}

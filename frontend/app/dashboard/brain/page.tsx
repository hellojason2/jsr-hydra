'use client'

import React, { useEffect, useState, useCallback } from 'react'
import { Brain, RefreshCw } from 'lucide-react'
import { ThoughtStream } from '@/components/brain/ThoughtStream'
import { MarketAnalysis } from '@/components/brain/MarketAnalysis'
import { StrategyScores } from '@/components/brain/StrategyScores'
import { NextMoves } from '@/components/brain/NextMoves'
import { LLMInsights } from '@/components/brain/LLMInsights'

interface BrainState {
  thoughts: Array<{
    timestamp: string
    type: 'ANALYSIS' | 'DECISION' | 'LEARNING' | 'PLAN'
    content: string
    confidence: number
    metadata: Record<string, any>
  }>
  market_analysis: {
    trend: string
    momentum: string
    volatility: string
    regime: string
    regime_confidence: number
    key_levels: { [key: string]: number }
    summary: string
  } | null
  next_moves: Array<{
    strategy: string
    action: string
    condition: string
    timeframe: string
    probability: number
  }>
  strategy_scores: Record<
    string,
    { confidence: number; reason: string; status: 'IDLE' | 'WATCHING' | 'WARMING_UP' | 'READY' | 'ACTIVE' }
  > | null
  last_updated: string
}

export default function BrainPage() {
  const [brainState, setBrainState] = useState<BrainState | null>(null)
  const [llmInsights, setLlmInsights] = useState<any[]>([])
  const [llmStats, setLlmStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<Date | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const fetchBrainState = useCallback(async (isManual = false) => {
    try {
      if (isManual) setRefreshing(true)
      setError(null)

      const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
      const headers: Record<string, string> = token
        ? { Authorization: `Bearer ${token}`, Accept: 'application/json' }
        : { Accept: 'application/json' }

      const res = await fetch('/api/brain/state', { headers })

      if (!res.ok) {
        throw new Error(`Brain API returned ${res.status}`)
      }

      const data = await res.json()
      setBrainState(data)
      setLastFetch(new Date())

      // Fetch LLM insights in parallel (non-blocking)
      try {
        const llmRes = await fetch('/api/brain/llm-insights', { headers })
        if (llmRes.ok) {
          const llmData = await llmRes.json()
          setLlmInsights(llmData.insights || [])
          setLlmStats(llmData.stats || null)
        }
      } catch {
        // LLM insights are optional -- don't block on failure
      }
    } catch (err) {
      console.error('Error fetching brain state:', err)
      setError(err instanceof Error ? err.message : 'Failed to connect to Brain')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchBrainState()
    const interval = setInterval(() => fetchBrainState(), 5000)
    return () => clearInterval(interval)
  }, [fetchBrainState])

  const thoughtCount = brainState?.thoughts?.length || 0
  const lastUpdated = brainState?.last_updated
    ? new Date(brainState.last_updated).toLocaleTimeString()
    : null

  return (
    <div className="min-h-screen bg-brand-dark p-4 md:p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-purple-500/15 border border-purple-500/20">
              <Brain size={24} className="text-purple-400" />
            </div>
            <div>
              <h1 className="text-2xl md:text-3xl font-bold text-gray-100">Brain</h1>
              <p className="text-gray-400 text-sm mt-0.5">
                {lastFetch ? `Synced ${lastFetch.toLocaleTimeString()}` : 'Connecting...'}
                <span className="ml-2 text-gray-600">&bull;</span>
                <span className="ml-2">Auto-refresh 5s</span>
              </p>
            </div>
          </div>
          <button
            onClick={() => fetchBrainState(true)}
            disabled={refreshing}
            className="flex items-center gap-2 px-4 py-2 bg-purple-500/15 text-purple-300 border border-purple-500/20 rounded-lg font-medium text-sm hover:bg-purple-500/25 transition-all duration-200 disabled:opacity-50"
          >
            <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
            {refreshing ? 'Syncing...' : 'Refresh'}
          </button>
        </div>

        {/* Error State */}
        {error && (
          <div className="mb-6 p-4 bg-red-900/20 border border-red-700/50 rounded-lg text-red-400">
            <p className="text-sm">{error}</p>
            <button
              onClick={() => fetchBrainState(true)}
              className="mt-2 text-xs text-red-300 hover:text-red-200 underline"
            >
              Try again
            </button>
          </div>
        )}

        {/* Top Section: Market Analysis */}
        <div className="mb-6">
          <MarketAnalysis data={brainState?.market_analysis || null} loading={loading} />
        </div>

        {/* Middle Section: Two Columns */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 mb-6">
          {/* Left Column (60%): Thought Stream */}
          <div className="lg:col-span-3">
            <div className="bg-brand-panel border border-gray-700 rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-700 flex items-center justify-between">
                <h3 className="text-lg font-semibold text-gray-100">Thought Stream</h3>
                <span className="text-xs text-gray-500 font-mono">{thoughtCount} thoughts</span>
              </div>
              <div className="px-6 py-4">
                <ThoughtStream
                  thoughts={brainState?.thoughts || []}
                  loading={loading}
                />
              </div>
            </div>
          </div>

          {/* Right Column (40%): Strategy Scores + Next Moves */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-brand-panel border border-gray-700 rounded-lg p-4">
              <StrategyScores
                scores={brainState?.strategy_scores || null}
                loading={loading}
              />
            </div>
            <div className="bg-brand-panel border border-gray-700 rounded-lg p-4">
              <NextMoves
                moves={brainState?.next_moves || null}
                loading={loading}
              />
            </div>
          </div>
        </div>

        {/* AI Insights Section */}
        <div className="mb-6">
          <div className="bg-brand-panel border border-indigo-500/20 rounded-lg overflow-hidden"
            style={{ boxShadow: '0 0 20px rgba(99, 102, 241, 0.06)' }}
          >
            <div className="px-6 py-4">
              <LLMInsights
                insights={llmInsights}
                stats={llmStats}
                loading={loading}
              />
            </div>
          </div>
        </div>

        {/* Bottom Section: Brain Activity Indicator */}
        <div className="bg-brand-panel border border-gray-700 rounded-lg px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {/* Animated pulse line */}
              <div className="flex items-center gap-1">
                {Array.from({ length: 12 }).map((_, i) => (
                  <div
                    key={i}
                    className="w-1 bg-purple-500/60 rounded-full"
                    style={{
                      height: `${8 + Math.sin((i / 12) * Math.PI * 2) * 6}px`,
                      animation: 'pulse 2s ease-in-out infinite',
                      animationDelay: `${i * 100}ms`,
                    }}
                  />
                ))}
              </div>
              <span className="text-xs text-gray-400">
                Brain {brainState ? 'active' : 'connecting...'}
              </span>
            </div>

            <div className="flex items-center gap-4 text-xs text-gray-500">
              <span>
                {thoughtCount} thought{thoughtCount !== 1 ? 's' : ''} recorded
              </span>
              {lastUpdated && (
                <>
                  <span className="text-gray-700">&bull;</span>
                  <span>Last update: {lastUpdated}</span>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Global animation styles */}
      <style jsx global>{`
        @keyframes fade-in {
          from {
            opacity: 0;
            transform: translateY(-8px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        .animate-fade-in {
          animation: fade-in 0.4s ease-out;
        }
        .scrollbar-thin::-webkit-scrollbar {
          width: 4px;
        }
        .scrollbar-thin::-webkit-scrollbar-track {
          background: transparent;
        }
        .scrollbar-thin::-webkit-scrollbar-thumb {
          background: #374151;
          border-radius: 2px;
        }
        .scrollbar-thin::-webkit-scrollbar-thumb:hover {
          background: #4b5563;
        }
      `}</style>
    </div>
  )
}

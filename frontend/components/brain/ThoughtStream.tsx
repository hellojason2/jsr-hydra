'use client'

import React, { useEffect, useRef } from 'react'

interface Thought {
  timestamp: string
  type: 'ANALYSIS' | 'DECISION' | 'LEARNING' | 'PLAN' | 'AI_INSIGHT'
  content: string
  confidence: number
  metadata: Record<string, any>
}

interface ThoughtStreamProps {
  thoughts: Thought[]
  loading?: boolean
}

const typeConfig: Record<string, { icon: string; color: string; bg: string; glow?: string }> = {
  ANALYSIS: { icon: '\u{1F9E0}', color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
  DECISION: { icon: '\u26A1', color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
  LEARNING: { icon: '\u{1F4DA}', color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
  PLAN: { icon: '\u{1F3AF}', color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
  AI_INSIGHT: { icon: '\u2728', color: 'text-indigo-300', bg: 'bg-gradient-to-r from-indigo-950/40 via-purple-950/20 to-transparent border-indigo-500/30', glow: '0 0 12px rgba(99, 102, 241, 0.15), 0 0 24px rgba(139, 92, 246, 0.08)' },
}

function getRelativeTime(timestamp: string): string {
  const now = new Date()
  const then = new Date(timestamp)
  const diffMs = now.getTime() - then.getTime()
  const diffSeconds = Math.floor(diffMs / 1000)

  if (diffSeconds < 10) return 'just now'
  if (diffSeconds < 60) return `${diffSeconds}s ago`

  const diffMinutes = Math.floor(diffSeconds / 60)
  if (diffMinutes < 60) return `${diffMinutes}m ago`

  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`

  return `${Math.floor(diffHours / 24)}d ago`
}

export function ThoughtStream({ thoughts, loading = false }: ThoughtStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevCountRef = useRef(thoughts.length)

  useEffect(() => {
    if (thoughts.length > prevCountRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
    prevCountRef.current = thoughts.length
  }, [thoughts.length])

  if (loading && thoughts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" />
          <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" style={{ animationDelay: '150ms' }} />
          <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" style={{ animationDelay: '300ms' }} />
        </div>
        <span className="text-sm">Brain is thinking...</span>
      </div>
    )
  }

  if (thoughts.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
        No thoughts yet. Brain is warming up...
      </div>
    )
  }

  return (
    <div
      ref={scrollRef}
      className="space-y-3 max-h-[500px] overflow-y-auto pr-2 scrollbar-thin"
      style={{ scrollBehavior: 'smooth' }}
    >
      {thoughts.map((thought, index) => {
        const config = typeConfig[thought.type] || typeConfig.ANALYSIS
        const isNew = index === 0

        return (
          <div
            key={`${thought.timestamp}-${index}`}
            className={`relative border rounded-lg p-3 transition-all duration-500 ${config.bg} ${
              isNew ? 'animate-fade-in' : ''
            }`}
            style={config.glow ? { boxShadow: config.glow } : undefined}
          >
            {/* Type icon + timestamp row */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className="text-base">{config.icon}</span>
                <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                  {thought.type}
                </span>
              </div>
              <span className="text-xs text-gray-500 font-mono">
                {getRelativeTime(thought.timestamp)}
              </span>
            </div>

            {/* Content */}
            <p className="text-sm text-gray-200 leading-relaxed">{thought.content}</p>

            {/* Confidence bar */}
            <div className="mt-2 flex items-center gap-2">
              <span className="text-xs text-gray-500">Confidence</span>
              <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${
                    thought.confidence >= 0.7
                      ? 'bg-green-500'
                      : thought.confidence >= 0.4
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                  }`}
                  style={{ width: `${thought.confidence * 100}%` }}
                />
              </div>
              <span className="text-xs text-gray-400 font-mono w-10 text-right">
                {(thought.confidence * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

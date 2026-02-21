'use client'

import { TradingPairSelector } from '@/components/settings/TradingPairSelector'
import { LLMModelSelector } from '@/components/settings/LLMModelSelector'
import { Settings } from 'lucide-react'

export default function SettingsPage() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-8">
        <Settings className="w-8 h-8 text-[#00d97e]" />
        <h1 className="text-3xl font-bold">Settings</h1>
      </div>
      <div className="space-y-8">
        <TradingPairSelector />
        <LLMModelSelector />
      </div>
    </div>
  )
}

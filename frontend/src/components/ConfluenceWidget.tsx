import type { QuantReport } from '../api/client';
import { Zap, Shield, AlertTriangle } from 'lucide-react';
import clsx from 'clsx';

interface Props {
    confluence: QuantReport['confluence'];
    td: QuantReport['td_status'];
    trend: QuantReport['trend_regime'];
}

export default function ConfluenceWidget({ confluence, td, trend }: Props) {
    const isStrong = confluence.strength === 'STRONG';
    const isWeak = confluence.strength === 'WEAK';



    return (
        <div className="glass-card p-6 flex flex-col border-t-4 border-t-primary/50">
            <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-bold flex items-center space-x-2">
                    <Zap className="w-5 h-5 text-primary" />
                    <span>Confluence Engine</span>
                </h3>
                <div className={clsx(
                    "px-3 py-1 rounded-full text-xs font-bold border",
                    isStrong ? "bg-success/20 text-success-light border-success/30" :
                        isWeak ? "bg-danger/20 text-danger-light border-danger/30" :
                            "bg-warning/20 text-warning border-warning/30"
                )}>
                    {confluence.strength}
                </div>
            </div>

            {/* Main Score Display */}
            <div className="flex flex-col items-center justify-center py-6 mb-6 rounded-xl bg-surfaceHover/50 border border-white/5">
                <span className="text-sm font-medium text-slate-400 mb-1">Total Algorithmic Score</span>
                <div className="text-5xl font-black text-gradient tracking-tighter">
                    {confluence.total_score.toFixed(1)}<span className="text-2xl text-slate-500">/100</span>
                </div>
            </div>

            {/* Breakdown Scores */}
            <div className="space-y-4">
                <h4 className="text-sm font-semibold text-slate-300 border-b border-white/5 pb-2">Score Breakdown</h4>

                <ScoreItem label="Pivot Proximity" score={confluence.details.pivot_proximity} max={25} />
                <ScoreItem label="TD Sequential" score={confluence.details.td} max={25} />
                <ScoreItem label="Market Regime" score={confluence.details.regime} max={25} />
                <ScoreItem label="Cluster Zone" score={confluence.details.cluster_zone} max={25} />
            </div>

            {/* TD Status Summary Mini-Card */}
            <div className="mt-8 pt-6 border-t border-white/5 space-y-3">
                <h4 className="text-sm font-semibold text-slate-300 mb-2 flex items-center space-x-2">
                    <Shield className="w-4 h-4 text-primary-light" />
                    <span>Regime & TD Status</span>
                </h4>

                <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="bg-black/20 rounded p-2 border border-white/5">
                        <span className="block text-xs text-slate-500 mb-1">Regime</span>
                        <span className="font-mono text-primary-light">{trend.regime.replace('_', ' ')}</span>
                    </div>
                    <div className="bg-black/20 rounded p-2 border border-white/5">
                        <span className="block text-xs text-slate-500 mb-1">TD Phase</span>
                        <span className="font-mono text-white">{td.phase}</span>
                    </div>
                </div>

                {td.perfect_setup && (
                    <div className="flex items-center space-x-2 text-xs font-medium text-warning-light bg-warning/10 p-2 rounded border border-warning/20">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>Perfect Setup detected (exhaustion risk)</span>
                    </div>
                )}
            </div>
        </div>
    );
}

function ScoreItem({ label, score, max }: { label: string, score: number, max: number }) {
    const percentage = Math.min(100, Math.max(0, (score / max) * 100));

    return (
        <div className="flex flex-col space-y-1.5">
            <div className="flex justify-between text-sm">
                <span className="text-slate-400">{label}</span>
                <span className="font-mono font-medium">{score.toFixed(1)}</span>
            </div>
            <div className="w-full bg-black/40 h-1.5 rounded-full overflow-hidden">
                <div
                    className="h-full bg-primary-light rounded-full transition-all duration-1000 ease-out"
                    style={{ width: `${percentage}%` }}
                />
            </div>
        </div>
    );
}

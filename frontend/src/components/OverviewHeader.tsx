import type { QuantReport } from '../api/client';
import { TrendingUp, TrendingDown, Minus, Activity, Target } from 'lucide-react';

interface Props {
    report: QuantReport;
}

export default function OverviewHeader({ report }: Props) {
    const { meta, trend_regime, context } = report;

    const TrendIcon = trend_regime.trend === 'UP' ? TrendingUp :
        trend_regime.trend === 'DOWN' ? TrendingDown : Minus;

    const trendColor = trend_regime.trend === 'UP' ? 'text-success-light' :
        trend_regime.trend === 'DOWN' ? 'text-danger-light' : 'text-slate-400';

    return (
        <div className="glass-card p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
            {/* Left side: Symbol & Price */}
            <div>
                <div className="flex items-center space-x-3 mb-1">
                    <h2 className="text-3xl font-bold tracking-tight">{meta.symbol}</h2>
                    <span className="px-2.5 py-1 text-xs font-semibold bg-white/5 border border-white/10 rounded-md">
                        H4
                    </span>
                </div>
                <div className="text-4xl font-mono font-bold text-gradient tracking-tight">
                    {meta.current_price.toFixed(2)}
                </div>
                <p className="text-xs text-slate-500 mt-2 font-mono">
                    Last updated: {new Date(meta.timestamp).toLocaleString()}
                </p>
            </div>

            {/* Right side: Key Metrics Grid */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 w-full md:w-auto">
                {/* Trend */}
                <div className="glass-panel p-4 flex flex-col">
                    <span className="text-xs text-slate-400 font-medium mb-2 uppercase tracking-wider flex items-center space-x-1.5">
                        <Activity className="w-3.5 h-3.5" />
                        <span>Trend (H4)</span>
                    </span>
                    <div className={`flex items-center space-x-2 font-semibold ${trendColor}`}>
                        <TrendIcon className="w-5 h-5" />
                        <span>{trend_regime.trend}</span>
                    </div>
                </div>

                {/* Context */}
                <div className="glass-panel p-4 flex flex-col">
                    <span className="text-xs text-slate-400 font-medium mb-2 uppercase tracking-wider flex items-center space-x-1.5">
                        <Target className="w-3.5 h-3.5" />
                        <span>Context</span>
                    </span>
                    <div className="font-semibold text-white truncate" title={context.zone}>
                        {context.zone}
                    </div>
                    <div className="text-xs text-primary-light mt-1 truncate" title={context.bias}>
                        {context.bias}
                    </div>
                </div>

                {/* Prob(H/L) */}
                <div className="glass-panel p-4 flex flex-col">
                    <span className="text-xs text-slate-400 font-medium mb-2 uppercase tracking-wider">
                        Prob (H / L)
                    </span>
                    <div className="flex items-end justify-between h-full pb-1">
                        <span className="font-bold text-success-light">{context.prob_h}%</span>
                        <span className="text-slate-500 mx-1">/</span>
                        <span className="font-bold text-danger-light">{context.prob_l}%</span>
                    </div>
                    {/* Mini progress bar representing ratio */}
                    <div className="mt-2 h-1.5 w-full bg-danger/20 rounded-full overflow-hidden flex">
                        <div className="h-full bg-success" style={{ width: `${context.prob_h}%` }}></div>
                        <div className="h-full bg-danger" style={{ width: `${context.prob_l}%` }}></div>
                    </div>
                </div>

                {/* Volatility / Reach */}
                <div className="glass-panel p-4 flex flex-col">
                    <span className="text-xs text-slate-400 font-medium mb-2 uppercase tracking-wider">
                        Vol (VR / Reach)
                    </span>
                    <div className="font-mono text-sm space-y-1">
                        <div className="flex justify-between">
                            <span className="text-slate-400">VR:</span>
                            <span className={context.vr > 1.0 ? 'text-warning-light' : 'text-slate-200'}>
                                {context.vr.toFixed(2)}
                            </span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">Reach:</span>
                            <span className={context.reach_cl > 100 ? 'text-danger-light' : 'text-slate-200'}>
                                {context.reach_cl.toFixed(1)}%
                            </span>
                        </div>
                    </div>
                </div>

            </div>
        </div>
    );
}

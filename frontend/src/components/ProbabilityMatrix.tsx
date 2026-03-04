import type { QuantReport } from '../api/client';
import { ArrowLeftRight, Activity, Percent } from 'lucide-react';
import clsx from 'clsx';

interface Props {
    probabilities: QuantReport['probabilities'];
    currentPrice: number;
}

export default function ProbabilityMatrix({ probabilities, currentPrice }: Props) {
    return (
        <div className="glass-card p-6 border-t-4 border-t-primary/30">
            <div className="flex items-center justify-between border-b border-white/5 pb-4 mb-6">
                <h3 className="text-lg font-bold flex items-center space-x-2">
                    <Activity className="w-5 h-5 text-primary" />
                    <span>Probability Matrix & Step Extension</span>
                </h3>
                <p className="text-xs text-slate-400">P(Touch | Current Context)</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Upside Probabilities */}
                <div>
                    <h4 className="flex justify-between text-sm font-semibold text-danger-light mb-4 pb-2 border-b border-white/5">
                        <span>Upside (Resistance)</span>
                        <span className="text-slate-500 font-mono text-xs hidden sm:block">Touch %</span>
                    </h4>
                    <div className="space-y-4">
                        {probabilities.upside.length === 0 ? (
                            <p className="text-sm text-slate-500 py-4 text-center border border-dashed border-white/10 rounded-lg">No valid upside targets found.</p>
                        ) : (
                            probabilities.upside.map((band, idx) => (
                                <ProbBar
                                    key={`up-${band.label}`}
                                    label={band.label}
                                    level={band.level}
                                    prob={band.point_estimate}
                                    colorClass="bg-danger"
                                    textColorClass="text-danger-light"
                                    currentPrice={currentPrice}
                                    isFirst={idx === 0}
                                />
                            ))
                        )}
                    </div>
                </div>

                {/* Downside Probabilities */}
                <div>
                    <h4 className="flex justify-between text-sm font-semibold text-success-light mb-4 pb-2 border-b border-white/5">
                        <span>Downside (Support)</span>
                        <span className="text-slate-500 font-mono text-xs hidden sm:block">Touch %</span>
                    </h4>
                    <div className="space-y-4">
                        {probabilities.downside.length === 0 ? (
                            <p className="text-sm text-slate-500 py-4 text-center border border-dashed border-white/10 rounded-lg">No valid downside targets found.</p>
                        ) : (
                            probabilities.downside.map((band, idx) => (
                                <ProbBar
                                    key={`dn-${band.label}`}
                                    label={band.label}
                                    level={band.level}
                                    prob={band.point_estimate}
                                    colorClass="bg-success"
                                    textColorClass="text-success-light"
                                    currentPrice={currentPrice}
                                    isFirst={idx === 0}
                                />
                            ))
                        )}
                    </div>
                </div>
            </div>

            {/* Step Extensions Matrix */}
            {(probabilities.step_extension.length > 0 || probabilities.step_breakdown.length > 0) && (
                <div className="mt-8 pt-6 border-t border-white/5">
                    <h4 className="text-sm font-semibold text-slate-300 mb-4 flex items-center space-x-2">
                        <ArrowLeftRight className="w-4 h-4 text-primary" />
                        <span>Conditional Step Probabilities <span className="font-normal text-xs text-slate-500">P(Next | Current touched)</span></span>
                    </h4>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Upside Steps */}
                        <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-2">
                            <span className="text-xs uppercase text-slate-500 font-semibold mb-2 block">Step Extension (Up)</span>
                            {probabilities.step_extension.map((step, i) => (
                                <StepRow key={`su-${i}`} step={step} color="text-danger-light" />
                            ))}
                            {probabilities.step_extension.length === 0 && <span className="text-xs text-slate-600 font-mono">Insufficient data</span>}
                        </div>

                        {/* Downside Steps */}
                        <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-2">
                            <span className="text-xs uppercase text-slate-500 font-semibold mb-2 block">Step Breakdown (Down)</span>
                            {probabilities.step_breakdown.map((step, i) => (
                                <StepRow key={`sd-${i}`} step={step} color="text-success-light" />
                            ))}
                            {probabilities.step_breakdown.length === 0 && <span className="text-xs text-slate-600 font-mono">Insufficient data</span>}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

// Sub-components

function ProbBar({ label, level, prob, colorClass, textColorClass, currentPrice, isFirst }: {
    label: string, level: number, prob: number, colorClass: string, textColorClass: string, currentPrice: number, isFirst: boolean
}) {
    const distPct = ((Math.abs(level - currentPrice) / currentPrice) * 100).toFixed(2);
    const isHighProb = prob >= 50;

    return (
        <div className="flex flex-col space-y-1.5 relative group">
            <div className="flex justify-between items-baseline">
                <div className="flex items-center space-x-2">
                    <span className={clsx("font-semibold font-mono", textColorClass, isFirst && "text-base")}>{label}</span>
                    <span className="text-xs text-slate-400 font-mono">{level.toFixed(2)}</span>
                    <span className="text-[10px] text-slate-500 font-mono bg-white/5 px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity">
                        {distPct}% dist
                    </span>
                </div>
                <div className="flex flex-col items-end">
                    <span className={clsx("font-bold font-mono tracking-tight", isHighProb ? "text-white" : "text-slate-300")}>
                        {prob.toFixed(1)}%
                    </span>
                </div>
            </div>

            {/* Background track */}
            <div className="w-full bg-black/40 h-2.5 rounded-full overflow-hidden border border-white/5">
                {/* Fill bar */}
                <div
                    className={clsx("h-full rounded-full transition-all duration-1000 ease-out", colorClass, isHighProb ? "opacity-100" : "opacity-60")}
                    style={{ width: `${Math.min(100, Math.max(0, prob))}%` }}
                />
            </div>
        </div>
    );
}

interface StepData {
    from_label: string;
    to_label: string;
    from_level: number;
    to_level: number;
    conditional_prob: number;
}

function StepRow({ step, color }: { step: StepData, color: string }) {
    const isHighProb = step.conditional_prob >= 40;

    return (
        <div className="flex items-center justify-between text-sm py-1 border-b border-white/5 last:border-0 hover:bg-white/5 px-2 -mx-2 rounded transition-colors">
            <div className="flex items-center space-x-2 font-mono">
                <span className="text-slate-300">{step.from_label}</span>
                <span className="text-slate-600">→</span>
                <span className="text-slate-100 font-semibold">{step.to_label}</span>
            </div>
            <div className={clsx("font-mono font-medium flex items-center space-x-1", isHighProb ? color : "text-slate-400")}>
                <span>{step.conditional_prob.toFixed(1)}</span>
                <Percent className="w-3 h-3 opacity-60" />
            </div>
        </div>
    );
}

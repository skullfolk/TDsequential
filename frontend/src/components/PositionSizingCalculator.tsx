import { useState } from 'react';
import { Calculator, DollarSign, Target, TrendingDown } from 'lucide-react';
import clsx from 'clsx';

interface CalcResult {
    riskAmount: number;
    rewardAmount: number;
    rrRatio: number;
    lots: number;
    pipRisk: number;
}

function computeSize(
    balance: number,
    riskPct: number,
    entry: number,
    stop: number,
    target: number,
    pipValuePerLot: number,
    minLots: number,
    maxLotsCap: number,
): CalcResult {
    const dollarRisk = (balance * riskPct) / 100;
    const pipRisk = Math.abs(entry - stop);
    const pipReward = Math.abs(target - entry);
    const lots = pipRisk > 0 ? Math.max(minLots, Math.min(maxLotsCap, dollarRisk / (pipRisk * pipValuePerLot))) : 0;
    return {
        riskAmount: dollarRisk,
        rewardAmount: lots * pipReward * pipValuePerLot,
        rrRatio: pipRisk > 0 ? pipReward / pipRisk : 0,
        lots: Math.round(lots * 100) / 100,
        pipRisk,
    };
}

export default function PositionSizingCalculator({ currentPrice }: { currentPrice: number }) {
    const [balance, setBalance] = useState(10000);
    const [riskPct, setRiskPct] = useState(1.0);
    const [entry, setEntry] = useState(currentPrice);
    const [stop, setStop] = useState(currentPrice - 30);
    const [target, setTarget] = useState(currentPrice + 75);
    const [pipValue, setPipValue] = useState(1.0);

    const result = computeSize(balance, riskPct, entry, stop, target, pipValue, 0.01, 50);
    const isLong = target > entry;
    const rrColor = result.rrRatio >= 2.0 ? 'text-success-light' : result.rrRatio >= 1.5 ? 'text-warning' : 'text-danger-light';

    const inputClass = "w-full bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/30 transition-all";

    return (
        <div className="glass-card p-6">
            <h3 className="text-lg font-bold mb-5 flex items-center space-x-2">
                <Calculator className="w-5 h-5 text-primary" />
                <span>Position Sizing Calculator</span>
                <span className={clsx(
                    "ml-2 text-xs px-2 py-0.5 rounded-full border",
                    isLong ? "text-success-light bg-success/10 border-success/20" : "text-danger-light bg-danger/10 border-danger/20"
                )}>{isLong ? 'LONG' : 'SHORT'}</span>
            </h3>

            <div className="grid grid-cols-2 gap-4 mb-6">
                {/* Account Settings */}
                <div className="col-span-2">
                    <p className="text-xs text-slate-500 uppercase tracking-wider mb-3">Account</p>
                    <div className="grid grid-cols-2 gap-3">
                        <label className="flex flex-col space-y-1.5">
                            <span className="text-xs text-slate-400 flex items-center space-x-1">
                                <DollarSign className="w-3 h-3" />
                                <span>Balance (USD)</span>
                            </span>
                            <input type="number" value={balance} onChange={e => setBalance(+e.target.value)} className={inputClass} step={1000} />
                        </label>
                        <label className="flex flex-col space-y-1.5">
                            <span className="text-xs text-slate-400">Risk %</span>
                            <input type="number" value={riskPct} onChange={e => setRiskPct(+e.target.value)} className={inputClass} step={0.5} min={0.1} max={10} />
                        </label>
                    </div>
                </div>

                {/* Trade Parameters */}
                <div className="col-span-2">
                    <p className="text-xs text-slate-500 uppercase tracking-wider mb-3">Trade Levels</p>
                    <div className="grid grid-cols-3 gap-3">
                        <label className="flex flex-col space-y-1.5">
                            <span className="text-xs text-slate-400">Entry</span>
                            <input type="number" value={entry} onChange={e => setEntry(+e.target.value)} className={inputClass} step={0.5} />
                        </label>
                        <label className="flex flex-col space-y-1.5">
                            <span className="text-xs text-slate-400 flex items-center space-x-1">
                                <TrendingDown className="w-3 h-3 text-danger-light" />
                                <span>Stop Loss</span>
                            </span>
                            <input type="number" value={stop} onChange={e => setStop(+e.target.value)} className={clsx(inputClass, 'border-danger/30')} step={0.5} />
                        </label>
                        <label className="flex flex-col space-y-1.5">
                            <span className="text-xs text-slate-400 flex items-center space-x-1">
                                <Target className="w-3 h-3 text-success-light" />
                                <span>Target</span>
                            </span>
                            <input type="number" value={target} onChange={e => setTarget(+e.target.value)} className={clsx(inputClass, 'border-success/30')} step={0.5} />
                        </label>
                    </div>
                </div>
            </div>

            {/* Results Block */}
            <div className="bg-black/30 border border-white/5 rounded-xl p-5 grid grid-cols-2 gap-4">
                <div className="flex flex-col">
                    <span className="text-xs text-slate-500 mb-1.5">Lot Size</span>
                    <span className="text-3xl font-black font-mono text-gradient">{result.lots.toFixed(2)}</span>
                    <span className="text-xs text-slate-500 mt-1">lots</span>
                </div>
                <div className="flex flex-col">
                    <span className="text-xs text-slate-500 mb-1.5">Risk / Reward</span>
                    <span className={clsx("text-3xl font-black font-mono", rrColor)}>
                        1:{result.rrRatio.toFixed(2)}
                    </span>
                    <span className="text-xs text-slate-500 mt-1">
                        Risk: ${result.riskAmount.toFixed(0)} | Reward: ${result.rewardAmount.toFixed(0)}
                    </span>
                </div>
                <div className="col-span-2 pt-3 border-t border-white/5 flex items-center justify-between text-xs text-slate-400 font-mono">
                    <span>Pip Risk: {result.pipRisk.toFixed(2)}</span>
                    <span>Dollar Risk: ${result.riskAmount.toFixed(2)}</span>
                    <span>Pip Value/Lot: $<input className="bg-transparent border-b border-white/20 w-12 text-center" type="number" value={pipValue} onChange={e => setPipValue(+e.target.value)} step={0.5} /></span>
                </div>
            </div>
        </div>
    );
}

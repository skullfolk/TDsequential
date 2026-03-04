import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { BarChart2 } from 'lucide-react';
import clsx from 'clsx';

interface HistoryRow {
    timestamp: string;
    current_price: number;
    trend: string;
    regime: string;
    context_zone: string;
    td_phase: string;
    confluence_score: number;
    signal_strength: string;
    vr: number;
    reach_cl: number;
}

const fetchHistory = async (symbol: string): Promise<HistoryRow[]> => {
    const { data } = await apiClient.get<{ status: string; data: HistoryRow[] }>(
        `/history/${symbol}?limit=24`
    );
    return data.data;
};

const strengthColor: Record<string, string> = {
    STRONG: 'bg-success',
    MODERATE: 'bg-warning',
    WEAK: 'bg-danger',
};

const trendColor: Record<string, string> = {
    UP: 'text-success-light',
    DOWN: 'text-danger-light',
    SIDEWAYS: 'text-slate-400',
};

export default function HistoryChart({ symbol = 'XAUUSD' }: { symbol?: string }) {
    const { data: history, isLoading } = useQuery({
        queryKey: ['history', symbol],
        queryFn: () => fetchHistory(symbol),
        enabled: true,
        staleTime: 5 * 60_000,
    });

    const rows = history ?? [];
    const maxScore = Math.max(...rows.map(r => r.confluence_score), 1);

    return (
        <div className="glass-card p-6">
            <h3 className="text-lg font-bold mb-5 flex items-center space-x-2">
                <BarChart2 className="w-5 h-5 text-primary" />
                <span>Historical Confluence <span className="text-xs text-slate-500 font-normal">(last 24 bars)</span></span>
            </h3>

            {isLoading ? (
                <div className="h-28 flex items-center justify-center">
                    <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                </div>
            ) : rows.length === 0 ? (
                <div className="h-28 flex flex-col items-center justify-center text-sm text-slate-500 border border-dashed border-white/10 rounded-xl">
                    <BarChart2 className="w-8 h-8 mb-2 opacity-30" />
                    <span>No history yet — data appears after first 4H cycle</span>
                </div>
            ) : (
                <>
                    {/* Micro Bar Chart */}
                    <div className="flex items-end space-x-1 h-24 mb-3">
                        {[...rows].reverse().map((row, i) => {
                            const pct = Math.max(4, (row.confluence_score / maxScore) * 100);
                            const color = strengthColor[row.signal_strength] ?? 'bg-slate-600';
                            return (
                                <div key={i} className="flex-1 flex flex-col justify-end group relative">
                                    <div
                                        className={clsx('rounded-t transition-all duration-300', color, 'opacity-70 group-hover:opacity-100')}
                                        style={{ height: `${pct}%` }}
                                        title={`${row.timestamp}: ${row.confluence_score.toFixed(1)} | ${row.signal_strength}`}
                                    />
                                    {/* Tooltip */}
                                    <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 hidden group-hover:flex flex-col items-center z-50">
                                        <div className="bg-surface border border-white/10 rounded-lg px-2 py-1.5 text-[10px] text-slate-200 whitespace-nowrap shadow-xl font-mono">
                                            {new Date(row.timestamp).toLocaleDateString('en-GB', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}<br />
                                            <span className={trendColor[row.trend] ?? ''}>{row.trend}</span>
                                            {' · '}{row.confluence_score.toFixed(1)}
                                        </div>
                                        <div className="w-2 h-2 bg-surface border-b border-r border-white/10 rotate-45 -mt-1" />
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Legend */}
                    <div className="flex items-center space-x-4 text-xs text-slate-500 mt-1">
                        <span className="flex items-center space-x-1.5">
                            <span className="w-2.5 h-2.5 rounded-sm bg-success inline-block" />
                            <span>Strong</span>
                        </span>
                        <span className="flex items-center space-x-1.5">
                            <span className="w-2.5 h-2.5 rounded-sm bg-warning inline-block" />
                            <span>Moderate</span>
                        </span>
                        <span className="flex items-center space-x-1.5">
                            <span className="w-2.5 h-2.5 rounded-sm bg-danger inline-block" />
                            <span>Weak</span>
                        </span>
                    </div>

                    {/* Recent Rows Table */}
                    <div className="mt-5 overflow-x-auto">
                        <table className="w-full text-xs font-mono border-collapse">
                            <thead>
                                <tr className="border-b border-white/5 text-slate-500">
                                    <th className="text-left pb-2 pr-3 font-medium">Time</th>
                                    <th className="text-right pb-2 pr-3 font-medium">Price</th>
                                    <th className="text-left pb-2 pr-3 font-medium">Trend</th>
                                    <th className="text-left pb-2 pr-3 font-medium">Zone</th>
                                    <th className="text-right pb-2 font-medium">Score</th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows.slice(0, 6).map((row, i) => (
                                    <tr key={i} className="border-b border-white/5 hover:bg-white/3 transition-colors">
                                        <td className="py-1.5 pr-3 text-slate-400">
                                            {new Date(row.timestamp).toLocaleString('en-GB', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                                        </td>
                                        <td className="py-1.5 pr-3 text-right">{row.current_price.toFixed(2)}</td>
                                        <td className={clsx('py-1.5 pr-3 font-semibold', trendColor[row.trend] ?? '')}>
                                            {row.trend}
                                        </td>
                                        <td className="py-1.5 pr-3 text-slate-300">{row.context_zone}</td>
                                        <td className="py-1.5 text-right font-semibold text-white">{row.confluence_score.toFixed(1)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    );
}

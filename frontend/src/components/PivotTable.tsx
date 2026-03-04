import type { QuantReport } from '../api/client';
import { AlignJustify } from 'lucide-react';
import clsx from 'clsx';

interface Props {
    pivots: QuantReport['levels']['pivots']['D'];
    title: string;
}

export default function PivotTable({ pivots, title }: Props) {
    // Ordered from R3 down to S3
    const levels = [
        { label: 'R3', val: pivots.R3, kind: 'res' },
        { label: 'MR3', val: pivots.MR3, kind: 'res-mid' },
        { label: 'R2', val: pivots.R2, kind: 'res' },
        { label: 'MR2', val: pivots.MR2, kind: 'res-mid' },
        { label: 'R1', val: pivots.R1, kind: 'res' },
        { label: 'MR1', val: pivots.MR1, kind: 'res-mid' },
        { label: 'P', val: pivots.P, kind: 'pivot' },
        { label: 'MS1', val: pivots.MS1, kind: 'sup-mid' },
        { label: 'S1', val: pivots.S1, kind: 'sup' },
        { label: 'MS2', val: pivots.MS2, kind: 'sup-mid' },
        { label: 'S2', val: pivots.S2, kind: 'sup' },
        { label: 'MS3', val: pivots.MS3, kind: 'sup-mid' },
        { label: 'S3', val: pivots.S3, kind: 'sup' },
    ];

    return (
        <div className="glass-card p-5">
            <h3 className="text-sm font-bold flex items-center mb-4 space-x-2 text-slate-300">
                <AlignJustify className="w-4 h-4 text-primary" />
                <span>{title} <span className="font-normal text-xs text-slate-500">(Camarilla + Classic)</span></span>
            </h3>

            <div className="w-full text-sm font-mono flex flex-col space-y-px">
                {levels.map(({ label, val, kind }) => (
                    <div
                        key={label}
                        className={clsx(
                            "flex justify-between items-center px-3 py-1.5 rounded-sm transition-colors cursor-default hover:bg-white/5",
                            kind === 'res' && "text-danger-light",
                            kind === 'res-mid' && "text-danger-light/60",
                            kind === 'pivot' && "text-white font-bold bg-white/5 border border-white/10",
                            kind === 'sup-mid' && "text-success-light/60",
                            kind === 'sup' && "text-success-light"
                        )}
                    >
                        <span className="w-10">{label}</span>
                        <span>{val.toFixed(2)}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

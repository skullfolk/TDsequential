import axios from 'axios';

const API_BASE_URL = '/api';

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

export interface QuantReport {
    meta: {
        symbol: string;
        timestamp: string;
        current_price: number;
        adr_14: number;
    };
    trend_regime: {
        trend: string;
        regime: string;
        is_td_favorable: boolean;
    };
    context: {
        zone: string;
        bias: string;
        focus: string;
        prob_h: number;
        prob_l: number;
        vr: number;
        reach_cl: number;
    };
    td_status: {
        phase: string;
        setup_count: number;
        countdown_count: number;
        tdst: number;
        perfect_setup: boolean;
        perfect_countdown: boolean;
    };
    levels: {
        pivots: Record<string, {
            P: number; R1: number; R2: number; R3: number;
            S1: number; S2: number; S3: number;
            MR1: number; MR2: number; MR3: number;
            MS1: number; MS2: number; MS3: number;
        }>;
        cluster_zones: Array<{
            name: string; low: number; high: number; strength: number;
        }>;
    };
    probabilities: {
        upside: Array<{
            level: number; label: string; point_estimate: number; ci_low: number; ci_high: number; regime_bucket: string;
        }>;
        downside: Array<{
            level: number; label: string; point_estimate: number; ci_low: number; ci_high: number; regime_bucket: string;
        }>;
        step_extension: Array<{
            from_label: string; to_label: string; from_level: number; to_level: number; conditional_prob: number;
        }>;
        step_breakdown: Array<{
            from_label: string; to_label: string; from_level: number; to_level: number; conditional_prob: number;
        }>;
    };
    confluence: {
        total_score: number;
        strength: string;
        details: Record<string, number>;
    };
}

export const fetchLatestAnalysis = async (symbol: string = 'XAUUSD'): Promise<QuantReport> => {
    const { data } = await apiClient.get<{ status: string; source: string; data: QuantReport }>(
        `/analyze/latest?symbol=${symbol}`
    );
    return data.data;
};

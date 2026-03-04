import { useQuery } from '@tanstack/react-query';
import { Activity, RefreshCw } from 'lucide-react';
import { fetchLatestAnalysis } from './api/client';

// Dashboard components
import OverviewHeader from './components/OverviewHeader';
import ProbabilityMatrix from './components/ProbabilityMatrix';
import ConfluenceWidget from './components/ConfluenceWidget';
import PivotTable from './components/PivotTable';
import PositionSizingCalculator from './components/PositionSizingCalculator';
import HistoryChart from './components/HistoryChart';

function App() {
  const { data: report, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['latestAnalysis', 'XAUUSD'],
    queryFn: () => fetchLatestAnalysis('XAUUSD'),
  });

  return (
    <div className="min-h-screen bg-background text-slate-200">
      {/* Top Navbar */}
      <nav className="border-b border-white/5 bg-surface/50 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="bg-primary/20 p-2 rounded-lg ring-1 ring-primary/30">
              <Activity className="w-5 h-5 text-primary" />
            </div>
            <h1 className="font-bold text-lg tracking-tight">
              Quant <span className="text-primary-light">Edge</span>
            </h1>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center space-x-2 bg-white/5 hover:bg-white/10 px-4 py-2 rounded-lg border border-white/10 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            <span className="text-sm font-medium">Refresh</span>
          </button>
        </div>
      </nav>

      {/* Main Dashboard Layout */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center h-64 space-y-4">
            <div className="w-10 h-10 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"></div>
            <p className="text-blue-200 font-medium text-lg">Loading quant parameters...</p>
            <p className="text-slate-500 text-sm">Connecting to backend engine...</p>
          </div>
        ) : isError ? (
          <div className="max-w-lg mx-auto mt-20 glass-card p-8 border border-red-500/30 bg-red-900/20 flex flex-col items-center text-center space-y-5">
            <div className="w-16 h-16 bg-red-500/20 border border-red-500/30 rounded-full flex items-center justify-center">
              <Activity className="w-8 h-8 text-red-400" />
            </div>
            <div>
              <p className="text-red-300 font-bold text-xl mb-2">No Analysis Data Found</p>
              <p className="text-slate-400 text-sm">
                The Quant Engine hasn't run yet — analysis runs automatically every 4 hours.<br />
                Click below to trigger the first run now (takes ~10–30s).
              </p>
            </div>
            <button
              onClick={async () => {
                await import('./api/client').then(m => m.apiClient.post('/analyze/refresh', {
                  symbol_yf: 'XAUUSD=X', display_name: 'XAUUSD'
                }));
                setTimeout(() => refetch(), 15000);
              }}
              className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-3 rounded-xl transition-colors flex items-center space-x-2"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Trigger First Analysis</span>
            </button>
            <p className="text-xs text-slate-600 font-mono">
              Backend: <span className="text-green-400">✓ Online (port 8001)</span>
            </p>
          </div>

        ) : report ? (
          <div className="animate-fade-in space-y-6">
            {/* Main 2-col grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Column */}
              <div className="lg:col-span-2 space-y-6">
                <OverviewHeader report={report} />
                <ProbabilityMatrix probabilities={report.probabilities} currentPrice={report.meta.current_price} />
                <PositionSizingCalculator currentPrice={report.meta.current_price} />
              </div>

              {/* Right Column */}
              <div className="space-y-6">
                <ConfluenceWidget confluence={report.confluence} td={report.td_status} trend={report.trend_regime} />
                <PivotTable pivots={report.levels.pivots.D} title="Daily Pivots" />
                <PivotTable pivots={report.levels.pivots.W} title="Weekly Pivots" />
              </div>
            </div>

            {/* Full-width history bar */}
            <div className="w-full mt-6">
              <HistoryChart symbol="XAUUSD" />
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}

export default App;

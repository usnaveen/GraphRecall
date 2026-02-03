/**
 * Backend Status Panel
 * Slide-in diagnostic panel showing health of all backend services.
 * Opened by clicking the WiFi icon in TopBar.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Server, Database, Share2, Rss, Globe,
  MessageCircle, Upload, RefreshCw, Loader2,
  CheckCircle2, XCircle, Circle,
} from 'lucide-react';
import {
  Sheet, SheetContent, SheetHeader,
  SheetTitle, SheetDescription, SheetFooter,
} from './ui/sheet';
import { getAuthToken } from '../store/useAuthStore';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CheckStatus = 'idle' | 'checking' | 'ok' | 'error';

interface CheckResult {
  status: CheckStatus;
  responseTimeMs: number | null;
  error: string | null;
  detail: string | null;
}

const IDLE_RESULT: CheckResult = {
  status: 'idle',
  responseTimeMs: null,
  error: null,
  detail: null,
};

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
const BASE_URL = API_BASE.replace(/\/api\/?$/, '');

// ---------------------------------------------------------------------------
// Timed fetch with 10 s timeout
// ---------------------------------------------------------------------------

async function runTimedFetch(
  url: string,
  options?: RequestInit,
): Promise<{ response: Response; elapsed: number }> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  const start = performance.now();
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const elapsed = Math.round(performance.now() - start);
    return { response, elapsed };
  } finally {
    clearTimeout(timeout);
  }
}

// ---------------------------------------------------------------------------
// Individual service check helpers
// ---------------------------------------------------------------------------

interface HealthPayload {
  server: CheckResult;
  pg: CheckResult;
  neo4j: CheckResult;
}

async function checkHealthEndpoint(): Promise<HealthPayload> {
  try {
    const { response, elapsed } = await runTimedFetch(`${BASE_URL}/health`);
    if (!response.ok) {
      const err = `HTTP ${response.status}`;
      return {
        server: { status: 'error', responseTimeMs: elapsed, error: err, detail: response.statusText },
        pg: { status: 'error', responseTimeMs: null, error: err, detail: null },
        neo4j: { status: 'error', responseTimeMs: null, error: err, detail: null },
      };
    }
    const data = await response.json();
    const pgStatus = data.postgres?.status === 'healthy' ? 'ok' : 'error';
    const neo4jStatus = data.neo4j?.status === 'healthy' ? 'ok' : 'error';
    return {
      server: { status: 'ok', responseTimeMs: elapsed, error: null, detail: `Status: ${data.status}` },
      pg: {
        status: pgStatus,
        responseTimeMs: null,
        error: pgStatus === 'error' ? (data.postgres?.error || 'Unhealthy') : null,
        detail: pgStatus === 'ok' ? 'Connected' : (data.postgres?.error || 'Disconnected'),
      },
      neo4j: {
        status: neo4jStatus,
        responseTimeMs: null,
        error: neo4jStatus === 'error' ? (data.neo4j?.error || 'Unhealthy') : null,
        detail: neo4jStatus === 'ok' ? 'Connected' : (data.neo4j?.error || 'Disconnected'),
      },
    };
  } catch (err: unknown) {
    const msg = err instanceof Error
      ? (err.name === 'AbortError' ? 'Timeout (10 s)' : err.message)
      : 'Network error';
    const result: CheckResult = { status: 'error', responseTimeMs: null, error: msg, detail: 'Unreachable' };
    return { server: result, pg: { ...result, detail: null }, neo4j: { ...result, detail: null } };
  }
}

async function checkAuthEndpoint(path: string): Promise<CheckResult> {
  const token = getAuthToken();
  if (!token) {
    return { status: 'error', responseTimeMs: null, error: 'No auth token', detail: 'Not authenticated' };
  }
  try {
    const { response, elapsed } = await runTimedFetch(`${API_BASE}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      return {
        status: 'error',
        responseTimeMs: elapsed,
        error: `HTTP ${response.status}`,
        detail: response.status === 401 ? 'Token expired / invalid' : response.statusText,
      };
    }
    return { status: 'ok', responseTimeMs: elapsed, error: null, detail: 'Responding' };
  } catch (err: unknown) {
    const msg = err instanceof Error
      ? (err.name === 'AbortError' ? 'Timeout (10 s)' : err.message)
      : 'Network error';
    return { status: 'error', responseTimeMs: null, error: msg, detail: 'Unreachable' };
  }
}

async function checkV2Health(): Promise<CheckResult> {
  try {
    const { response, elapsed } = await runTimedFetch(`${BASE_URL}/api/v2/health`);
    if (!response.ok) {
      return { status: 'error', responseTimeMs: elapsed, error: `HTTP ${response.status}`, detail: response.statusText };
    }
    return { status: 'ok', responseTimeMs: elapsed, error: null, detail: 'Responding' };
  } catch (err: unknown) {
    const msg = err instanceof Error
      ? (err.name === 'AbortError' ? 'Timeout (10 s)' : err.message)
      : 'Network error';
    return { status: 'error', responseTimeMs: null, error: msg, detail: 'Unreachable' };
  }
}

// ---------------------------------------------------------------------------
// Service definitions (display order)
// ---------------------------------------------------------------------------

interface ServiceDef {
  id: string;
  name: string;
  icon: React.ElementType;
  group: 'infra' | 'api';
}

const SERVICES: ServiceDef[] = [
  { id: 'backend-server', name: 'Backend Server', icon: Server, group: 'infra' },
  { id: 'postgresql', name: 'PostgreSQL', icon: Database, group: 'infra' },
  { id: 'neo4j', name: 'Neo4j', icon: Share2, group: 'infra' },
  { id: 'feed-api', name: 'Feed API', icon: Rss, group: 'api' },
  { id: 'graph-api', name: 'Knowledge Graph', icon: Globe, group: 'api' },
  { id: 'chat-api', name: 'Chat API', icon: MessageCircle, group: 'api' },
  { id: 'ingestion-api', name: 'Ingestion API', icon: Upload, group: 'api' },
];

// ---------------------------------------------------------------------------
// StatusRow sub-component
// ---------------------------------------------------------------------------

function StatusRow({ service, result }: { service: ServiceDef; result: CheckResult }) {
  const Icon = service.icon;

  const statusColor =
    result.status === 'ok' ? '#4ADE80' :
    result.status === 'error' ? '#F87171' :
    result.status === 'checking' ? '#EAB308' :
    'rgba(255,255,255,0.2)';

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl glass-surface mb-1.5">
      {/* Service icon */}
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
        style={{ backgroundColor: `${statusColor}20` }}
      >
        <Icon className="w-4 h-4" style={{ color: statusColor }} />
      </div>

      {/* Name + detail */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white truncate">{service.name}</p>
        {(result.detail || result.error) && (
          <p className="text-xs text-white/40 truncate">
            {result.status === 'error' ? result.error : result.detail}
          </p>
        )}
      </div>

      {/* Response time + status icon */}
      <div className="flex items-center gap-2 shrink-0">
        {result.responseTimeMs !== null && (
          <span className="text-xs font-mono text-white/30">{result.responseTimeMs}ms</span>
        )}
        {result.status === 'ok' && <CheckCircle2 className="w-4 h-4 text-green-400" />}
        {result.status === 'error' && <XCircle className="w-4 h-4 text-red-400" />}
        {result.status === 'checking' && <Loader2 className="w-4 h-4 text-yellow-400 animate-spin" />}
        {result.status === 'idle' && <Circle className="w-4 h-4 text-white/20" />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface BackendStatusPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function BackendStatusPanel({ open, onOpenChange }: BackendStatusPanelProps) {
  const [results, setResults] = useState<Record<string, CheckResult>>({});
  const [isRunning, setIsRunning] = useState(false);
  const [lastRunAt, setLastRunAt] = useState<Date | null>(null);

  const runAllChecks = useCallback(async () => {
    setIsRunning(true);

    // Set all to "checking"
    const checking: Record<string, CheckResult> = {};
    for (const s of SERVICES) {
      checking[s.id] = { status: 'checking', responseTimeMs: null, error: null, detail: null };
    }
    setResults(checking);

    // Infrastructure: single /health call → 3 results
    const healthPromise = checkHealthEndpoint().then((h) => {
      setResults((prev) => ({
        ...prev,
        'backend-server': h.server,
        'postgresql': h.pg,
        'neo4j': h.neo4j,
      }));
    });

    // Auth-protected API checks (parallel)
    const feedPromise = checkAuthEndpoint('/feed/due-count').then((r) =>
      setResults((prev) => ({ ...prev, 'feed-api': r })),
    );
    const graphPromise = checkAuthEndpoint('/graph3d').then((r) =>
      setResults((prev) => ({ ...prev, 'graph-api': r })),
    );
    const chatPromise = checkAuthEndpoint('/chat/suggestions').then((r) =>
      setResults((prev) => ({ ...prev, 'chat-api': r })),
    );

    // V2 health (no auth)
    const v2Promise = checkV2Health().then((r) =>
      setResults((prev) => ({ ...prev, 'ingestion-api': r })),
    );

    await Promise.allSettled([healthPromise, feedPromise, graphPromise, chatPromise, v2Promise]);
    setIsRunning(false);
    setLastRunAt(new Date());
  }, []);

  // Auto-run checks when panel opens
  useEffect(() => {
    if (open) {
      runAllChecks();
    }
  }, [open, runAllChecks]);

  const infraServices = SERVICES.filter((s) => s.group === 'infra');
  const apiServices = SERVICES.filter((s) => s.group === 'api');

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="!bg-[#0A0A0F]/95 !backdrop-blur-xl !border-l-white/10 w-[340px] sm:w-[380px] sm:!max-w-[380px] flex flex-col"
      >
        <SheetHeader>
          <SheetTitle className="font-heading text-white text-lg">Backend Status</SheetTitle>
          <SheetDescription className="text-white/40 text-xs">
            Diagnostic health checks for all services
          </SheetDescription>

          {/* API URL badge */}
          <div className="mt-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10">
            <p className="text-[10px] text-white/30 uppercase tracking-wider mb-0.5">API Endpoint</p>
            <p className="font-mono text-xs text-white/60 break-all">{API_BASE}</p>
          </div>
        </SheetHeader>

        {/* Scrollable check list */}
        <div className="flex-1 overflow-y-auto px-4 pb-2 -mx-0">
          {/* Infrastructure */}
          <h3 className="font-heading text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-2 px-1">
            Infrastructure
          </h3>
          {infraServices.map((s) => (
            <StatusRow key={s.id} service={s} result={results[s.id] || IDLE_RESULT} />
          ))}

          {/* API Services */}
          <h3 className="font-heading text-[10px] font-semibold text-white/30 uppercase tracking-wider mb-2 mt-4 px-1">
            API Services
          </h3>
          {apiServices.map((s) => (
            <StatusRow key={s.id} service={s} result={results[s.id] || IDLE_RESULT} />
          ))}
        </div>

        <SheetFooter>
          <button
            onClick={runAllChecks}
            disabled={isRunning}
            className="w-full py-2.5 rounded-xl font-heading font-semibold text-sm bg-white/10 hover:bg-white/15 text-white border border-white/10 hover:border-white/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {isRunning ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Running Checks...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                Run All Checks
              </>
            )}
          </button>
          {lastRunAt && (
            <p className="text-center text-[10px] text-white/25 mt-1">
              Last checked: {lastRunAt.toLocaleTimeString()}
            </p>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

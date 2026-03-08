import React from 'react';
import { AlertCircle, CheckCircle2, Clock3, Loader2, Play, RefreshCcw, RotateCcw, Square } from 'lucide-react';

const statusClasses = {
    completed: 'bg-green-500/10 border-green-500/20 text-green-400',
    partial: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
    failed: 'bg-red-500/10 border-red-500/20 text-red-400',
    cancelled: 'bg-orange-500/10 border-orange-500/20 text-orange-300',
    processing: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
    queued: 'bg-zinc-500/10 border-zinc-500/20 text-zinc-300',
};

const formatTimestamp = (value) => {
    if (!value) return 'Unknown';
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(new Date(value * 1000));
};

export default function JobHistory({ jobs, loading, error, currentJobId, cancelingJobId, onRefresh, onOpenJob, onResumeJob, onCancelJob }) {
    return (
        <div className="h-full overflow-y-auto touch-scroll p-5 md:p-8 max-w-5xl mx-auto animate-[fadeIn_0.3s_ease-out]">
            <div className="flex items-center justify-between mb-8 gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-white">Job History</h1>
                    <p className="text-sm text-zinc-500 mt-1">
                        Resume failed or partial runs without retranscribing and recutting everything from zero.
                    </p>
                </div>
                <button
                    onClick={onRefresh}
                    disabled={loading}
                    className="px-4 py-2 rounded-xl border border-white/10 text-sm text-zinc-300 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-2 disabled:opacity-50"
                >
                    {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
                    Refresh
                </button>
            </div>

            {loading && jobs.length === 0 && (
                <div className="glass-panel p-10 flex items-center justify-center text-zinc-400 gap-3">
                    <Loader2 size={18} className="animate-spin" />
                    Loading jobs...
                </div>
            )}

            {error && !loading && (
                <div className="glass-panel p-6 border border-red-500/20 text-red-400 flex items-center gap-3">
                    <AlertCircle size={18} />
                    {error}
                </div>
            )}

            {!loading && !error && jobs.length === 0 && (
                <div className="glass-panel p-10 text-center text-zinc-500">
                    No jobs found yet.
                </div>
            )}

            <div className="space-y-4">
                {jobs.map((job) => {
                    const clipCount = Number.isFinite(job.clip_count) ? Number(job.clip_count) : (job.result?.clips?.length || 0);
                    const provider = job.provider?.name || 'gemini';
                    const statusClass = statusClasses[job.status] || statusClasses.failed;
                    const isCurrentJob = currentJobId === job.job_id;
                    const isStopping = cancelingJobId === job.job_id;
                    const canCancel = job.status === 'queued' || job.status === 'processing';
                    const lastLog = job.error || job.logs?.[job.logs.length - 1];

                    return (
                        <div
                            key={job.job_id}
                            className={`glass-panel p-5 border transition-colors ${isCurrentJob ? 'border-primary/40' : 'border-white/5'}`}
                        >
                            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                                <div className="min-w-0">
                                    <div className="flex flex-wrap items-center gap-2 mb-3">
                                        <span className={`px-2 py-1 rounded-full border text-[10px] font-bold uppercase tracking-wider ${statusClass}`}>
                                            {job.status}
                                        </span>
                                        <span className="px-2 py-1 rounded-full border border-white/10 bg-white/5 text-[10px] uppercase tracking-wider text-zinc-400">
                                            {provider}
                                        </span>
                                        {job.generation_mode && (
                                            <span className="px-2 py-1 rounded-full border border-white/10 bg-white/5 text-[10px] uppercase tracking-wider text-zinc-500">
                                                {job.generation_mode}
                                            </span>
                                        )}
                                        {job.can_resume && (
                                            <span className="px-2 py-1 rounded-full border border-amber-500/20 bg-amber-500/10 text-[10px] uppercase tracking-wider text-amber-400">
                                                resumable
                                            </span>
                                        )}
                                    </div>

                                    <h2 className="text-base font-semibold text-white break-words">
                                        {job.source_label}
                                    </h2>
                                    <div className="mt-3 grid gap-2 text-xs text-zinc-500 sm:grid-cols-2">
                                        <div className="flex items-center gap-2">
                                            <Clock3 size={12} />
                                            Updated {formatTimestamp(job.updated_at)}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <CheckCircle2 size={12} />
                                            {clipCount} output{clipCount === 1 ? '' : 's'}
                                        </div>
                                    </div>
                                    {lastLog && (
                                        <p className="mt-4 text-xs text-zinc-400 bg-black/20 border border-white/5 rounded-lg px-3 py-2 break-words">
                                            {lastLog}
                                        </p>
                                    )}
                                </div>

                                <div className="flex flex-col gap-2 lg:min-w-[180px]">
                                    <button
                                        onClick={() => onOpenJob(job)}
                                        className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-sm text-white transition-colors flex items-center justify-center gap-2"
                                    >
                                        <Play size={16} />
                                        {isCurrentJob ? 'Open Current Job' : 'Open Job'}
                                    </button>
                                    {job.can_resume && (
                                        <button
                                            onClick={() => onResumeJob(job)}
                                            className="px-4 py-2 rounded-xl bg-primary hover:bg-blue-600 text-sm text-white transition-colors flex items-center justify-center gap-2"
                                        >
                                            <RotateCcw size={16} />
                                            Resume Job
                                        </button>
                                    )}
                                    {canCancel && (
                                        <button
                                            onClick={() => onCancelJob(job)}
                                            disabled={isStopping}
                                            className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-sm text-red-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {isStopping ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
                                            Stop Job
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

import React from 'react';
import { AlertCircle, CalendarDays, CheckCircle2, Clock3, EyeOff, Film, Loader2, Pause, Play, RefreshCcw, RotateCcw, Square, Trash2 } from 'lucide-react';

const statusClasses = {
    completed: 'bg-green-500/10 border-green-500/20 text-green-400',
    partial: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
    failed: 'bg-red-500/10 border-red-500/20 text-red-400',
    cancelled: 'bg-orange-500/10 border-orange-500/20 text-orange-300',
    processing: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
    queued: 'bg-zinc-500/10 border-zinc-500/20 text-zinc-300',
};

const formatTimestamp = (value) => {
    if (!value) return 'Unbekannt';
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(new Date(value * 1000));
};

const bulkProgressLabel = (operation) => {
    const phase = String(operation?.current_phase || '').toLowerCase();
    const total = Number(operation?.total_count || 0);
    if (phase === 'render') return `${Number(operation?.render_completed_count || 0)}/${total} gerendert`;
    if (phase === 'post') return `${Number(operation?.post_completed_count || 0)}/${total} gepostet/eingeplant`;
    return `${Number(operation?.completed_count || 0)}/${total} fertig`;
};

const normalizeBulkMode = (value) => String(value || '').trim().toLowerCase().replaceAll('_', '-');

export default function JobHistory({
    jobs,
    queueOverview,
    loading,
    error,
    currentJobId,
    cancelingJobId,
    deletingJobId,
    onRefresh,
    onOpenJob,
    onOpenJobWithoutPreviews,
    onResumeJob,
    onReanalyzeJobWithMinimax,
    reanalyzingJobId,
    onCancelJob,
    onPauseBulkOperation,
    onResumeBulkOperation,
    onStopBulkOperation,
    bulkControlBusy,
    onDeleteJob,
    onOpenGlobalCalendar,
    globalCalendarLoading,
    uploadProfiles = [],
    activeUploadProfile = '',
    onAssignUploadProfile,
    showUnassignedJobs = false,
    onToggleUnassignedJobs,
}) {
    const bulkRunningStates = new Set(['running', 'pause_requested', 'stop_requested']);
    const bulkResumableStates = new Set(['paused', 'partial', 'failed']);
    const runningCount = Number(queueOverview?.running_count || 0);
    const queuedCount = Number(queueOverview?.queued_count || 0);
    const maxConcurrentJobs = Number(queueOverview?.max_concurrent_jobs || 1);
    const activeRenderQueues = jobs
        .filter((job) => {
            const operation = job.bulk_operation;
            const status = String(operation?.status || '').toLowerCase();
            return operation && normalizeBulkMode(operation.mode) !== 'post-only' && (bulkRunningStates.has(status) || bulkResumableStates.has(status));
        })
        .map((job) => {
            const operation = job.bulk_operation;
            const currentIndex = Number(operation.current_item_index);
            const currentItem = Number.isInteger(currentIndex) ? operation.items?.[currentIndex] : null;
            const pendingItems = (operation.items || []).filter((item) => !['completed', 'skipped'].includes(item.render_status));
            return { job, operation, currentItem, pendingItems };
        });
    const postRetryQueues = jobs
        .filter((job) => {
            const operation = job.bulk_operation;
            const status = String(operation?.status || '').toLowerCase();
            return operation && normalizeBulkMode(operation.mode) === 'post-only' && bulkResumableStates.has(status);
        })
        .map((job) => ({
            job,
            operation: job.bulk_operation,
            failedItems: (job.bulk_operation?.items || []).filter((item) => item.post_status === 'failed'),
        }))
        .filter((entry) => entry.failedItems.length > 0);

    return (
        <div className="h-full overflow-y-auto touch-scroll p-5 md:p-8 animate-[fadeIn_0.3s_ease-out]">
            <div className="flex items-center justify-between mb-8 gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-white">Job-Verlauf</h1>
                    <p className="text-sm text-zinc-500 mt-1">
                        Fehlgeschlagene oder teilweise fertige Jobs fortsetzen, ohne alles neu zu transkribieren und zu schneiden.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <button
                        onClick={onToggleUnassignedJobs}
                        className={`px-4 py-2 rounded-xl border text-sm transition-colors ${showUnassignedJobs ? 'border-amber-500/30 bg-amber-500/10 text-amber-100' : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10'}`}
                    >
                        {showUnassignedJobs ? `Zurueck zu ${activeUploadProfile || 'Profil-Jobs'}` : 'Unzugeordnete Jobs'}
                    </button>
                    <button
                        onClick={onOpenGlobalCalendar}
                        disabled={globalCalendarLoading}
                        className="px-4 py-2 rounded-xl border border-cyan-500/20 bg-cyan-500/10 text-sm text-cyan-100 hover:bg-cyan-500/20 transition-colors flex items-center gap-2 disabled:opacity-50"
                    >
                        {globalCalendarLoading ? <Loader2 size={16} className="animate-spin" /> : <CalendarDays size={16} />}
                        Kalender
                    </button>
                    <button
                        onClick={onRefresh}
                        disabled={loading}
                        className="px-4 py-2 rounded-xl border border-white/10 text-sm text-zinc-300 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-2 disabled:opacity-50"
                    >
                        {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCcw size={16} />}
                        Aktualisieren
                    </button>
                </div>
            </div>

            {(runningCount > 0 || queuedCount > 0) && (
                <div className="mb-6 rounded-2xl border border-cyan-500/15 bg-cyan-500/5 p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                            <h2 className="text-sm font-semibold text-cyan-100">Job-Queue aktiv</h2>
                            <p className="mt-1 text-xs text-zinc-500">
                                {runningCount}/{maxConcurrentJobs} Worker belegt, {queuedCount} Job{queuedCount === 1 ? '' : 's'} warten. Neue Jobs starten automatisch nacheinander.
                            </p>
                        </div>
                        <span className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1.5 text-xs text-cyan-100">
                            <Clock3 size={13} />
                            Serielle Nacht-Queue
                        </span>
                    </div>
                </div>
            )}

            <div className="mb-6 rounded-2xl border border-fuchsia-500/15 bg-fuchsia-500/5 p-4">
                <div className="flex items-center justify-between gap-3">
                    <div>
                        <h2 className="flex items-center gap-2 text-sm font-semibold text-fuchsia-100">
                            <Film size={15} /> Render-Queue
                        </h2>
                        <p className="mt-1 text-xs text-zinc-500">Aktive Multi-Render-Jobs und die nächsten wartenden Clips.</p>
                    </div>
                    <span className="rounded-full border border-fuchsia-500/20 bg-fuchsia-500/10 px-3 py-1 text-xs text-fuchsia-100">
                        {activeRenderQueues.length} Job{activeRenderQueues.length === 1 ? '' : 's'}
                    </span>
                </div>
                {activeRenderQueues.length === 0 ? (
                    <p className="mt-3 rounded-xl border border-white/5 bg-black/20 px-3 py-2 text-xs text-zinc-500">Aktuell läuft keine Multi-Render-Queue.</p>
                ) : (
                    <div className="mt-3 space-y-2">
                        {activeRenderQueues.map(({ job, operation, currentItem, pendingItems }) => (
                            <div key={job.job_id} className="rounded-xl border border-white/10 bg-black/25 px-3 py-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <span className="truncate text-sm font-medium text-white">{job.source_label}</span>
                                    <span className="text-xs font-semibold text-fuchsia-200">{bulkProgressLabel(operation)}</span>
                                </div>
                                <p className="mt-1 text-xs text-zinc-400">
                                    {String(operation.current_phase || '').toLowerCase() === 'render' && currentItem
                                        ? `Rendert jetzt: ${currentItem.clip_label || `Clip ${Number(currentItem.clip_index || 0) + 1}`}`
                                        : operation.message || 'Wartet auf Fortsetzung.'}
                                </p>
                                {pendingItems.length > 0 && (
                                    <p className="mt-1 text-[11px] text-zinc-500">
                                        Danach: {pendingItems.slice(currentItem ? 1 : 0, currentItem ? 4 : 3).map((item) => item.clip_label || `Clip ${Number(item.clip_index || 0) + 1}`).join(' · ') || 'keine weiteren Clips'}
                                        {pendingItems.length > 4 ? ` · +${pendingItems.length - 4}` : ''}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {postRetryQueues.length > 0 && (
                <div className="mb-6 rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-100">
                                <RefreshCcw size={15} /> Post-Retries erforderlich
                            </h2>
                            <p className="mt-1 text-xs text-zinc-500">
                                Diese Jobs sind beendet. Nur fehlgeschlagene Posts werden bei „Fortsetzen“ erneut verarbeitet.
                            </p>
                        </div>
                        <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1 text-xs text-amber-100">
                            {postRetryQueues.reduce((sum, entry) => sum + entry.failedItems.length, 0)} Clips in {postRetryQueues.length} Jobs
                        </span>
                    </div>
                    <div className="mt-3 space-y-2">
                        {postRetryQueues.map(({ job, operation, failedItems }) => (
                            <div key={job.job_id} className="rounded-xl border border-white/10 bg-black/25 px-3 py-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="min-w-0">
                                        <div className="truncate text-sm font-medium text-white">{job.source_label}</div>
                                        <div className="mt-1 text-xs text-amber-100/80">
                                            {failedItems.length} von {Number(operation.total_count || 0)} Posts brauchen einen Retry
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => onResumeBulkOperation(job)}
                                        disabled={bulkControlBusy === `history-resume:${job.job_id}`}
                                        className="inline-flex items-center gap-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs font-medium text-amber-100 hover:bg-amber-400/15 disabled:opacity-50"
                                    >
                                        {bulkControlBusy === `history-resume:${job.job_id}` ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
                                        Fehlerclips erneut versuchen
                                    </button>
                                </div>
                                <div className="mt-2 space-y-1 text-[11px] text-zinc-400">
                                    {failedItems.map((item) => (
                                        <div key={item.id || item.clip_index}>
                                            <span className="text-zinc-200">{item.clip_label || `Clip ${Number(item.clip_index || 0) + 1}`}:</span>{' '}
                                            {item.last_error || 'Unbekannter Upload-Fehler'}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {loading && jobs.length === 0 && (
                <div className="glass-panel p-10 flex items-center justify-center text-zinc-400 gap-3">
                    <Loader2 size={18} className="animate-spin" />
                    Lade Jobs...
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
                    Noch keine Jobs gefunden.
                </div>
            )}

            <div className="space-y-4">
                {jobs.map((job) => {
                    const clipCount = Number.isFinite(job.clip_count) ? Number(job.clip_count) : (job.result?.clips?.length || 0);
                    const provider = job.provider?.name || 'gemini';
                    const statusClass = statusClasses[job.status] || statusClasses.failed;
                    const isCurrentJob = currentJobId === job.job_id;
                    const isStopping = cancelingJobId === job.job_id;
                    const isDeleting = deletingJobId === job.job_id;
                    const isReanalyzing = reanalyzingJobId === job.job_id;
                    const canCancel = job.status === 'queued' || job.status === 'processing';
                    const bulkOperation = job.bulk_operation || null;
                    const bulkStatus = String(bulkOperation?.status || '').toLowerCase();
                    const hasBulkOperation = !!bulkOperation && (bulkRunningStates.has(bulkStatus) || bulkResumableStates.has(bulkStatus));
                    const canDelete = !canCancel && !hasBulkOperation;
                    const lastLog = job.error || job.logs?.[job.logs.length - 1];
                    const bulkSummary = hasBulkOperation
                        ? `${bulkProgressLabel(bulkOperation)}${bulkOperation.message ? ` · ${bulkOperation.message}` : ''}`
                        : '';

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
                                        <span className="px-2 py-1 rounded-full border border-cyan-500/20 bg-cyan-500/10 text-[10px] text-cyan-100">
                                            Profil: {job.upload_post_profile || 'nicht zugeordnet'}
                                        </span>
                                        {job.generation_mode && (
                                            <span className="px-2 py-1 rounded-full border border-white/10 bg-white/5 text-[10px] uppercase tracking-wider text-zinc-500">
                                                {job.generation_mode}
                                            </span>
                                        )}
                                        {job.can_resume && (
                                            <span className="px-2 py-1 rounded-full border border-amber-500/20 bg-amber-500/10 text-[10px] uppercase tracking-wider text-amber-400">
                                                fortsetzbar
                                            </span>
                                        )}
                                        {hasBulkOperation && (
                                            <span className={`px-2 py-1 rounded-full border text-[10px] uppercase tracking-wider ${
                                                bulkRunningStates.has(bulkStatus)
                                                    ? 'border-cyan-500/20 bg-cyan-500/10 text-cyan-300'
                                                    : 'border-amber-500/20 bg-amber-500/10 text-amber-300'
                                            }`}>
                                                multipost {bulkStatus}
                                            </span>
                                        )}
                                        {job.queue_status === 'waiting' && Number(job.queue_position || 0) > 0 && (
                                            <span className="px-2 py-1 rounded-full border border-cyan-500/20 bg-cyan-500/10 text-[10px] uppercase tracking-wider text-cyan-200">
                                                Queue #{job.queue_position}
                                            </span>
                                        )}
                                        {job.queue_status === 'running' && (
                                            <span className="px-2 py-1 rounded-full border border-blue-500/20 bg-blue-500/10 text-[10px] uppercase tracking-wider text-blue-200">
                                                Läuft jetzt
                                            </span>
                                        )}
                                    </div>

                                    <h2 className="text-base font-semibold text-white break-words">
                                        {job.source_label}
                                    </h2>
                                    <div className="mt-3 grid gap-2 text-xs text-zinc-500 sm:grid-cols-2">
                                        <div className="flex items-center gap-2">
                                            <Clock3 size={12} />
                                            Aktualisiert {formatTimestamp(job.updated_at)}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <CheckCircle2 size={12} />
                                            {clipCount} Ergebnis{clipCount === 1 ? '' : 'se'}
                                        </div>
                                    </div>
                                    {lastLog && (
                                        <p className="mt-4 text-xs text-zinc-400 bg-black/20 border border-white/5 rounded-lg px-3 py-2 break-words">
                                            {lastLog}
                                        </p>
                                    )}
                                    {hasBulkOperation && (
                                        <p className="mt-2 text-xs text-cyan-100 bg-cyan-500/10 border border-cyan-500/20 rounded-lg px-3 py-2 break-words">
                                            {bulkSummary}
                                        </p>
                                    )}
                                </div>

                                <div className="flex flex-col gap-2 lg:min-w-[180px]">
                                    <select
                                        value={job.upload_post_profile || ''}
                                        onChange={(event) => onAssignUploadProfile && onAssignUploadProfile(job, event.target.value)}
                                        className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-zinc-200"
                                        title="Upload-Post-Profil dieses Jobs"
                                    >
                                        <option value="">Nicht zugeordnet</option>
                                        {uploadProfiles.map((profile) => (
                                            <option key={profile.username} value={profile.username}>{profile.username}</option>
                                        ))}
                                        {activeUploadProfile && !uploadProfiles.some((profile) => profile.username === activeUploadProfile) && (
                                            <option value={activeUploadProfile}>{activeUploadProfile}</option>
                                        )}
                                    </select>
                                    <button
                                        onClick={() => onOpenJob(job)}
                                        className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-sm text-white transition-colors flex items-center justify-center gap-2"
                                    >
                                        <Play size={16} />
                                        {isCurrentJob ? 'Aktuellen Job öffnen' : 'Job öffnen'}
                                    </button>
                                    <button
                                        onClick={() => onOpenJobWithoutPreviews(job)}
                                        className="px-4 py-2 rounded-xl border border-cyan-500/20 bg-cyan-500/10 hover:bg-cyan-500/20 text-sm text-cyan-100 transition-colors flex items-center justify-center gap-2"
                                    >
                                        <EyeOff size={16} />
                                        Ohne Previews öffnen
                                    </button>
                                    {job.can_resume && (
                                        <button
                                            onClick={() => onResumeJob(job)}
                                            className="px-4 py-2 rounded-xl bg-primary hover:bg-blue-600 text-sm text-white transition-colors flex items-center justify-center gap-2"
                                        >
                                            <RotateCcw size={16} />
                                            Job fortsetzen
                                        </button>
                                    )}
                                    {!canCancel && (
                                        <button
                                            onClick={() => onReanalyzeJobWithMinimax(job)}
                                            disabled={isReanalyzing}
                                            className="px-4 py-2 rounded-xl bg-fuchsia-500/10 hover:bg-fuchsia-500/20 border border-fuchsia-500/20 text-sm text-fuchsia-200 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {isReanalyzing ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />}
                                            Mit MiniMax neu analysieren
                                        </button>
                                    )}
                                    {hasBulkOperation && bulkRunningStates.has(bulkStatus) && (
                                        <button
                                            onClick={() => onPauseBulkOperation(job)}
                                            disabled={bulkControlBusy === `history-pause:${job.job_id}`}
                                            className="px-4 py-2 rounded-xl bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/20 text-sm text-amber-200 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {bulkControlBusy === `history-pause:${job.job_id}` ? <Loader2 size={16} className="animate-spin" /> : <Pause size={16} />}
                                            Multi-Post pausieren
                                        </button>
                                    )}
                                    {hasBulkOperation && bulkResumableStates.has(bulkStatus) && (
                                        <button
                                            onClick={() => onResumeBulkOperation(job)}
                                            disabled={bulkControlBusy === `history-resume:${job.job_id}`}
                                            className="px-4 py-2 rounded-xl bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/20 text-sm text-cyan-200 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {bulkControlBusy === `history-resume:${job.job_id}` ? <Loader2 size={16} className="animate-spin" /> : <RotateCcw size={16} />}
                                            Multi-Post fortsetzen
                                        </button>
                                    )}
                                    {hasBulkOperation && (
                                        <button
                                            onClick={() => onStopBulkOperation(job)}
                                            disabled={bulkControlBusy === `history-stop:${job.job_id}`}
                                            className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-sm text-red-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {bulkControlBusy === `history-stop:${job.job_id}` ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
                                            Multi-Post stoppen
                                        </button>
                                    )}
                                    {canCancel && (
                                        <button
                                            onClick={() => onCancelJob(job)}
                                            disabled={isStopping}
                                            className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-sm text-red-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {isStopping ? <Loader2 size={16} className="animate-spin" /> : <Square size={16} />}
                                            Job stoppen
                                        </button>
                                    )}
                                    <button
                                        onClick={() => onDeleteJob(job)}
                                        disabled={isDeleting || !canDelete}
                                        className="px-4 py-2 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-sm text-red-300 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                    >
                                        {isDeleting ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                                        Job löschen
                                    </button>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

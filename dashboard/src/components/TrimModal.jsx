import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Clock, Loader2, Pause, Play, Scissors, SkipBack, SkipForward, Trash2, X } from 'lucide-react';

const MIN_TRIM_DURATION = 0.25;

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

const formatTime = (value) => {
    const total = Math.max(0, Number(value) || 0);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(1).padStart(4, '0')}`;
};

const normalizeRanges = (ranges, min, max) => {
    const sorted = (ranges || [])
        .map(([start, end]) => [clamp(Number(start), min, max), clamp(Number(end), min, max)])
        .filter(([start, end]) => end - start >= MIN_TRIM_DURATION)
        .sort((a, b) => a[0] - b[0]);

    const merged = [];
    for (const [start, end] of sorted) {
        const prev = merged[merged.length - 1];
        if (prev && start <= prev[1] + 0.05) {
            prev[1] = Math.max(prev[1], end);
        } else {
            merged.push([start, end]);
        }
    }
    return merged;
};

export default function TrimModal({ isOpen, onClose, onTrim, isProcessing, videoUrl }) {
    const videoRef = useRef(null);
    const [duration, setDuration] = useState(0);
    const [trimStart, setTrimStart] = useState(0);
    const [trimEnd, setTrimEnd] = useState(0);
    const [currentTime, setCurrentTime] = useState(0);
    const [isPlaying, setIsPlaying] = useState(false);
    const [cutStart, setCutStart] = useState(0);
    const [cutEnd, setCutEnd] = useState(0);
    const [removeRanges, setRemoveRanges] = useState([]);
    const [isPreviewLoading, setIsPreviewLoading] = useState(true);
    const [isPreviewReady, setIsPreviewReady] = useState(false);
    const [previewError, setPreviewError] = useState('');

    useEffect(() => {
        if (!isOpen) return;
        setCurrentTime(0);
        setTrimStart(0);
        setTrimEnd(0);
        setCutStart(0);
        setCutEnd(0);
        setRemoveRanges([]);
        setDuration(0);
        setIsPlaying(false);
        setIsPreviewLoading(!!videoUrl);
        setIsPreviewReady(false);
        setPreviewError(videoUrl ? '' : 'Keine Videoquelle gefunden.');
    }, [isOpen, videoUrl]);

    const safeTrimEnd = trimEnd || duration || 0;
    const normalizedRemoveRanges = useMemo(
        () => normalizeRanges(removeRanges, trimStart, safeTrimEnd),
        [removeRanges, trimStart, safeTrimEnd]
    );
    const removedDuration = normalizedRemoveRanges.reduce((sum, [start, end]) => sum + (end - start), 0);
    const trimmedDuration = Math.max(0, (safeTrimEnd - trimStart) - removedDuration);

    if (!isOpen) return null;

    const handleLoadedMetadata = () => {
        const nextDuration = videoRef.current?.duration || 0;
        setDuration(nextDuration);
        setTrimStart(0);
        setTrimEnd(nextDuration);
        setCutStart(0);
        setCutEnd(nextDuration);
    };

    const handlePreviewCanPlay = () => {
        setIsPreviewLoading(false);
        setIsPreviewReady(true);
        setPreviewError('');
    };

    const handlePreviewError = () => {
        setIsPreviewLoading(false);
        setIsPreviewReady(false);
        setPreviewError('Die Trim-Vorschau konnte nicht geladen werden.');
    };

    const seekTo = (value) => {
        const nextTime = clamp(Number(value), 0, duration || 0);
        setCurrentTime(nextTime);
        if (videoRef.current) {
            videoRef.current.currentTime = nextTime;
        }
    };

    const togglePlayback = () => {
        if (!videoRef.current) return;
        if (videoRef.current.paused) {
            videoRef.current.play();
        } else {
            videoRef.current.pause();
        }
    };

    const applyCurrentTimeToStart = () => {
        const nextStart = clamp(currentTime, 0, Math.max(0, safeTrimEnd - MIN_TRIM_DURATION));
        setTrimStart(nextStart);
    };

    const applyCurrentTimeToEnd = () => {
        const nextEnd = clamp(currentTime, trimStart + MIN_TRIM_DURATION, duration || currentTime);
        setTrimEnd(nextEnd);
    };

    const applyCurrentTimeToCutStart = () => {
        const nextStart = clamp(currentTime, trimStart, Math.max(trimStart, safeTrimEnd - MIN_TRIM_DURATION));
        setCutStart(nextStart);
    };

    const applyCurrentTimeToCutEnd = () => {
        const nextEnd = clamp(currentTime, cutStart + MIN_TRIM_DURATION, safeTrimEnd || currentTime);
        setCutEnd(nextEnd);
    };

    const handleAddCut = () => {
        const nextStart = clamp(cutStart, trimStart, safeTrimEnd);
        const nextEnd = clamp(cutEnd, trimStart, safeTrimEnd);
        if ((nextEnd - nextStart) < MIN_TRIM_DURATION) {
            return;
        }
        setRemoveRanges((prev) => normalizeRanges([...prev, [nextStart, nextEnd]], trimStart, safeTrimEnd));
    };

    const handleRemoveCut = (index) => {
        setRemoveRanges((prev) => prev.filter((_, itemIndex) => itemIndex !== index));
    };

    const handleSubmit = () => {
        onTrim({
            trimStart,
            trimEnd: safeTrimEnd,
            removeRanges: normalizedRemoveRanges,
        });
    };

    return createPortal(
        <div className="fixed inset-0 z-[1000] flex items-start md:items-center justify-center p-3 md:p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out] overflow-y-auto touch-scroll">
            <div className="bg-[#121214] border border-white/10 p-6 rounded-2xl w-full max-w-6xl shadow-2xl relative flex flex-col md:flex-row gap-6 my-4 md:my-0 max-h-[calc(100dvh-1.5rem)] md:max-h-[90vh] overflow-y-auto md:overflow-hidden touch-scroll">
                <button
                    onClick={onClose}
                    disabled={isProcessing}
                    className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10 disabled:opacity-50"
                >
                    <X size={20} />
                </button>

                <div className="flex-1 bg-black rounded-lg border border-white/5 overflow-hidden flex flex-col min-w-0 min-h-0">
                    <div className="px-4 pt-4 pb-2 border-b border-white/5 bg-[#0b0b0d]">
                        <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-zinc-500">Vorschau</div>
                        <div className="mt-1 text-xs text-zinc-400">
                            Vorschau mit Scrubbing und direkter Kontrolle der aktuellen Trim-Position.
                        </div>
                    </div>

                    <div className="relative bg-black min-h-[280px] md:min-h-[520px] flex items-center justify-center">
                        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.16),_transparent_38%),linear-gradient(180deg,_rgba(255,255,255,0.04),_rgba(255,255,255,0))]" />

                        {!videoUrl && (
                            <div className="relative z-10 w-full max-w-md mx-auto px-6 text-center">
                                <div className="rounded-2xl border border-white/10 bg-white/5 px-5 py-6">
                                    <div className="text-sm font-semibold text-white">Keine Vorschau verfuegbar</div>
                                    <div className="mt-2 text-xs text-zinc-400">
                                        Fuer diesen Clip liegt aktuell keine Video-URL vor.
                                    </div>
                                </div>
                            </div>
                        )}

                        {videoUrl && (
                            <>
                                <div className="relative z-10 w-full h-full flex items-center justify-center px-4 py-5">
                                    <div className="relative w-full max-w-[420px]">
                                        <div className="rounded-[28px] border border-white/10 bg-black shadow-[0_24px_80px_rgba(0,0,0,0.55)] p-2">
                                            <div className="rounded-[22px] overflow-hidden bg-black aspect-[9/16] relative">
                                                <video
                                                    key={videoUrl}
                                                    ref={videoRef}
                                                    src={videoUrl}
                                                    controls
                                                    preload="metadata"
                                                    className="w-full h-full object-contain"
                                                    onLoadedMetadata={handleLoadedMetadata}
                                                    onLoadedData={handlePreviewCanPlay}
                                                    onCanPlay={handlePreviewCanPlay}
                                                    onError={handlePreviewError}
                                                    onWaiting={() => setIsPreviewLoading(true)}
                                                    onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime || 0)}
                                                    onPlay={() => setIsPlaying(true)}
                                                    onPause={() => setIsPlaying(false)}
                                                    playsInline
                                                />
                                                {isPreviewLoading && !previewError && (
                                                    <div className="absolute inset-0 flex items-center justify-center bg-black/55 backdrop-blur-sm">
                                                        <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/60 px-4 py-3 text-sm text-white">
                                                            <Loader2 size={16} className="animate-spin text-cyan-400" />
                                                            Lade Vorschau...
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {previewError && (
                                    <div className="absolute inset-x-4 bottom-4 z-20 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3">
                                        <div className="text-sm font-semibold text-red-300">Vorschau konnte nicht geladen werden</div>
                                        <div className="mt-1 text-xs text-red-200/80">
                                            {previewError} Du kannst die Datei direkt oeffnen und danach erneut trimmen.
                                        </div>
                                        <div className="mt-3">
                                            <a
                                                href={videoUrl}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="inline-flex items-center rounded-lg border border-red-400/20 bg-red-500/10 px-3 py-2 text-xs font-medium text-red-100 hover:bg-red-500/20"
                                            >
                                                Video direkt oeffnen
                                            </a>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                    <div className="px-4 pt-3 space-y-3">
                        <input
                            type="range"
                            min="0"
                            max={duration || 0}
                            step="0.1"
                            value={currentTime}
                            onChange={(e) => seekTo(e.target.value)}
                            disabled={!duration || !isPreviewReady}
                            className="w-full accent-cyan-500 disabled:opacity-40"
                        />
                        <div className="flex flex-wrap gap-2">
                            <button
                                type="button"
                                onClick={() => seekTo((videoRef.current?.currentTime || 0) - 1)}
                                disabled={!isPreviewReady}
                                className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10 flex items-center gap-2"
                            >
                                <SkipBack size={14} /> -1s
                            </button>
                            <button
                                type="button"
                                onClick={togglePlayback}
                                disabled={!isPreviewReady}
                                className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10 flex items-center gap-2"
                            >
                                {isPlaying ? <Pause size={14} /> : <Play size={14} />}
                                {isPlaying ? 'Pause' : 'Abspielen'}
                            </button>
                            <button
                                type="button"
                                onClick={() => seekTo((videoRef.current?.currentTime || 0) + 1)}
                                disabled={!isPreviewReady}
                                className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10 flex items-center gap-2"
                            >
                                <SkipForward size={14} /> +1s
                            </button>
                            <button
                                type="button"
                                onClick={() => seekTo(trimStart)}
                                disabled={!isPreviewReady}
                                className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10"
                            >
                                Zum Start
                            </button>
                            <button
                                type="button"
                                onClick={() => seekTo(safeTrimEnd)}
                                disabled={!isPreviewReady}
                                className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10"
                            >
                                Zum Ende
                            </button>
                            {videoUrl && (
                                <a
                                    href={videoUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="px-3 py-2 rounded-lg bg-cyan-500/10 hover:bg-cyan-500/20 text-xs text-cyan-300 border border-cyan-500/20"
                                >
                                    Rohvideo öffnen
                                </a>
                            )}
                        </div>
                    </div>
                    <div className="px-4 py-3 border-t border-white/5 bg-white/5 flex items-center justify-between gap-3 text-xs text-zinc-400 mt-3">
                        <span className="flex items-center gap-2">
                            <Clock size={12} />
                            Aktuell: {formatTime(currentTime)}
                        </span>
                        <span>Ausgabe: {formatTime(trimmedDuration)}</span>
                    </div>
                </div>

                <div className="w-full md:w-[360px] flex flex-col min-w-0 min-h-0">
                    <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                        <Scissors className="text-cyan-400" /> Clip zuschneiden
                    </h3>

                    <div className="space-y-5 flex-1 overflow-y-auto custom-scrollbar touch-scroll pr-1 md:pr-2">
                        <div className="p-3 bg-white/5 rounded-xl border border-white/5 text-xs text-zinc-400">
                            Schneide vorne oder hinten weg und markiere optional mehrere Bereiche in der Mitte, die entfernt werden sollen.
                            Jede Speicherung erzeugt eine neue Version.
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Start behalten ab</label>
                            <input
                                type="range"
                                min="0"
                                max={duration || 0}
                                step="0.1"
                                value={trimStart}
                                onChange={(e) => setTrimStart(Math.min(Number(e.target.value), Math.max(0, safeTrimEnd - MIN_TRIM_DURATION)))}
                                className="w-full accent-cyan-500"
                            />
                            <div className="mt-3 flex gap-2">
                                <input
                                    type="number"
                                    min="0"
                                    max={Math.max(0, safeTrimEnd - MIN_TRIM_DURATION)}
                                    step="0.1"
                                    value={trimStart.toFixed(1)}
                                    onChange={(e) => setTrimStart(clamp(Number(e.target.value), 0, Math.max(0, safeTrimEnd - MIN_TRIM_DURATION)))}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-cyan-500/50"
                                />
                                <button type="button" onClick={applyCurrentTimeToStart} className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10">
                                    Aktuelle Zeit nutzen
                                </button>
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Ende behalten bis</label>
                            <input
                                type="range"
                                min="0"
                                max={duration || 0}
                                step="0.1"
                                value={safeTrimEnd}
                                onChange={(e) => setTrimEnd(Math.max(Number(e.target.value), trimStart + MIN_TRIM_DURATION))}
                                className="w-full accent-cyan-500"
                            />
                            <div className="mt-3 flex gap-2">
                                <input
                                    type="number"
                                    min={trimStart + MIN_TRIM_DURATION}
                                    max={duration || 0}
                                    step="0.1"
                                    value={safeTrimEnd.toFixed(1)}
                                    onChange={(e) => setTrimEnd(clamp(Number(e.target.value), trimStart + MIN_TRIM_DURATION, duration || Number(e.target.value)))}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-cyan-500/50"
                                />
                                <button type="button" onClick={applyCurrentTimeToEnd} className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10">
                                    Aktuelle Zeit nutzen
                                </button>
                            </div>
                        </div>

                        <div className="rounded-xl border border-white/5 bg-black/20 p-4 space-y-4">
                            <div className="flex items-center justify-between gap-3">
                                <div>
                                    <div className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Mittleren Bereich entfernen</div>
                                    <div className="text-[11px] text-zinc-500 mt-1">Mehrere Cuts stapeln, um Leerlauf in der Mitte zu entfernen.</div>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleAddCut}
                                    className="px-3 py-2 rounded-lg bg-cyan-500/15 hover:bg-cyan-500/25 text-xs text-cyan-300 border border-cyan-500/20"
                                >
                                    Cut hinzufügen
                                </button>
                            </div>

                            <div>
                                <label className="text-xs text-zinc-400 mb-2 block">Cut-Start</label>
                                <div className="flex gap-2">
                                    <input
                                        type="number"
                                        min={trimStart}
                                        max={safeTrimEnd}
                                        step="0.1"
                                        value={cutStart.toFixed(1)}
                                        onChange={(e) => setCutStart(clamp(Number(e.target.value), trimStart, safeTrimEnd))}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-cyan-500/50"
                                    />
                                    <button type="button" onClick={applyCurrentTimeToCutStart} className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10">
                                        Aktuelle Zeit nutzen
                                    </button>
                                </div>
                            </div>

                            <div>
                                <label className="text-xs text-zinc-400 mb-2 block">Cut-Ende</label>
                                <div className="flex gap-2">
                                    <input
                                        type="number"
                                        min={trimStart}
                                        max={safeTrimEnd}
                                        step="0.1"
                                        value={cutEnd.toFixed(1)}
                                        onChange={(e) => setCutEnd(clamp(Number(e.target.value), trimStart, safeTrimEnd))}
                                        className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-cyan-500/50"
                                    />
                                    <button type="button" onClick={applyCurrentTimeToCutEnd} className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10">
                                        Aktuelle Zeit nutzen
                                    </button>
                                </div>
                            </div>

                            <div className="space-y-2">
                                {normalizedRemoveRanges.length === 0 ? (
                                    <div className="text-[11px] text-zinc-500">Noch keine mittleren Cuts hinzugefügt.</div>
                                ) : normalizedRemoveRanges.map(([start, end], index) => (
                                    <div key={`${start}-${end}-${index}`} className="flex items-center justify-between gap-3 rounded-lg bg-white/5 px-3 py-2 text-xs text-zinc-300 border border-white/5">
                                        <span>{formatTime(start)} - {formatTime(end)}</span>
                                        <button
                                            type="button"
                                            onClick={() => handleRemoveCut(index)}
                                            className="text-zinc-500 hover:text-red-400"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="rounded-xl border border-white/5 bg-black/20 p-3 text-xs text-zinc-400 space-y-1">
                            <div>Start behalten: <span className="text-white">{formatTime(trimStart)}</span></div>
                            <div>Ende behalten: <span className="text-white">{formatTime(safeTrimEnd)}</span></div>
                            <div>Mittel-Cuts: <span className="text-white">{normalizedRemoveRanges.length}</span></div>
                            <div>Neue Länge: <span className="text-white">{formatTime(trimmedDuration)}</span></div>
                        </div>
                    </div>

                    <button
                        onClick={handleSubmit}
                        disabled={isProcessing || !duration || trimmedDuration < MIN_TRIM_DURATION}
                        className="w-full py-4 mt-6 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-bold rounded-xl shadow-lg shadow-cyan-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Scissors size={20} />}
                        {isProcessing ? 'Schneide...' : 'Trim-Version erstellen'}
                    </button>
                </div>
            </div>
        </div>,
        document.body
    );
}

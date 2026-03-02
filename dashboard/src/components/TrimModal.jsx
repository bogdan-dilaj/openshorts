import React, { useEffect, useRef, useState } from 'react';
import { Clock, Loader2, Scissors, X } from 'lucide-react';

const MIN_TRIM_DURATION = 0.25;

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

const formatTime = (value) => {
    const total = Math.max(0, Number(value) || 0);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(1).padStart(4, '0')}`;
};

export default function TrimModal({ isOpen, onClose, onTrim, isProcessing, videoUrl }) {
    const videoRef = useRef(null);
    const [duration, setDuration] = useState(0);
    const [trimStart, setTrimStart] = useState(0);
    const [trimEnd, setTrimEnd] = useState(0);
    const [currentTime, setCurrentTime] = useState(0);

    useEffect(() => {
        if (!isOpen) return;
        setCurrentTime(0);
        setTrimStart(0);
        setTrimEnd(0);
        setDuration(0);
    }, [isOpen, videoUrl]);

    if (!isOpen) return null;

    const safeTrimEnd = trimEnd || duration || 0;
    const trimmedDuration = Math.max(0, safeTrimEnd - trimStart);

    const handleLoadedMetadata = () => {
        const nextDuration = videoRef.current?.duration || 0;
        setDuration(nextDuration);
        setTrimStart(0);
        setTrimEnd(nextDuration);
    };

    const applyCurrentTimeToStart = () => {
        const nextStart = clamp(currentTime, 0, Math.max(0, safeTrimEnd - MIN_TRIM_DURATION));
        setTrimStart(nextStart);
    };

    const applyCurrentTimeToEnd = () => {
        const nextEnd = clamp(currentTime, trimStart + MIN_TRIM_DURATION, duration || currentTime);
        setTrimEnd(nextEnd);
    };

    const handleScrub = (value) => {
        const nextTime = clamp(Number(value), 0, duration || 0);
        setCurrentTime(nextTime);
        if (videoRef.current) {
            videoRef.current.currentTime = nextTime;
        }
    };

    const handleSubmit = () => {
        onTrim({
            trimStart,
            trimEnd: safeTrimEnd,
        });
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#121214] border border-white/10 p-6 rounded-2xl w-full max-w-5xl shadow-2xl relative flex flex-col md:flex-row gap-6 max-h-[90vh]">
                <button
                    onClick={onClose}
                    disabled={isProcessing}
                    className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10 disabled:opacity-50"
                >
                    <X size={20} />
                </button>

                <div className="flex-1 bg-black rounded-lg border border-white/5 overflow-hidden flex flex-col">
                    <div className="aspect-video bg-black">
                        <video
                            ref={videoRef}
                            src={videoUrl}
                            controls
                            className="w-full h-full object-contain"
                            onLoadedMetadata={handleLoadedMetadata}
                            onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime || 0)}
                            playsInline
                        />
                    </div>
                    <div className="px-4 pt-3">
                        <input
                            type="range"
                            min="0"
                            max={duration || 0}
                            step="0.1"
                            value={currentTime}
                            onChange={(e) => handleScrub(e.target.value)}
                            className="w-full accent-cyan-500"
                        />
                    </div>
                    <div className="px-4 py-3 border-t border-white/5 bg-white/5 flex items-center justify-between gap-3 text-xs text-zinc-400">
                        <span className="flex items-center gap-2">
                            <Clock size={12} />
                            Current: {formatTime(currentTime)}
                        </span>
                        <span>Output: {formatTime(trimmedDuration)}</span>
                    </div>
                </div>

                <div className="w-full md:w-80 flex flex-col">
                    <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                        <Scissors className="text-cyan-400" /> Trim Clip
                    </h3>

                    <div className="space-y-5 flex-1 overflow-y-auto custom-scrollbar pr-2">
                        <div className="p-3 bg-white/5 rounded-xl border border-white/5 text-xs text-zinc-400">
                            Schneide vorne oder hinten weg. Der neue Export wird als eigene Version gespeichert und fuer die naechsten Schritte verwendet.
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Start</label>
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
                                    onChange={(e) => {
                                        const value = Number(e.target.value);
                                        setTrimStart(clamp(value, 0, Math.max(0, safeTrimEnd - MIN_TRIM_DURATION)));
                                    }}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-cyan-500/50"
                                />
                                <button
                                    onClick={applyCurrentTimeToStart}
                                    type="button"
                                    className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10"
                                >
                                    Use Current
                                </button>
                            </div>
                            <div className="mt-2 text-[11px] text-zinc-500">{formatTime(trimStart)}</div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">End</label>
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
                                    onChange={(e) => {
                                        const value = Number(e.target.value);
                                        setTrimEnd(clamp(value, trimStart + MIN_TRIM_DURATION, duration || value));
                                    }}
                                    className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-cyan-500/50"
                                />
                                <button
                                    onClick={applyCurrentTimeToEnd}
                                    type="button"
                                    className="px-3 py-2 rounded-lg bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10"
                                >
                                    Use Current
                                </button>
                            </div>
                            <div className="mt-2 text-[11px] text-zinc-500">{formatTime(safeTrimEnd)}</div>
                        </div>

                        <div className="rounded-xl border border-white/5 bg-black/20 p-3 text-xs text-zinc-400 space-y-1">
                            <div>Start: <span className="text-white">{formatTime(trimStart)}</span></div>
                            <div>End: <span className="text-white">{formatTime(safeTrimEnd)}</span></div>
                            <div>Neue Laenge: <span className="text-white">{formatTime(trimmedDuration)}</span></div>
                        </div>
                    </div>

                    <button
                        onClick={handleSubmit}
                        disabled={isProcessing || !duration || trimmedDuration < MIN_TRIM_DURATION}
                        className="w-full py-4 mt-6 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-bold rounded-xl shadow-lg shadow-cyan-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Scissors size={20} />}
                        {isProcessing ? 'Trimming...' : 'Create Trim Version'}
                    </button>
                </div>
            </div>
        </div>
    );
}

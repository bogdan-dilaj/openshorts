import React, { useEffect, useState } from 'react';
import { Youtube, Upload, FileVideo, X } from 'lucide-react';

export default function MediaInput({
    onProcess,
    isProcessing,
    resetToken = 0,
    submitLabel,
    submittingLabel = 'Job wird eingereiht...',
    helperText,
    activeProfileName = '',
    profileContext = '',
}) {
    const [mode, setMode] = useState('url'); // 'url' | 'file'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [interviewMode, setInterviewMode] = useState(false);
    const [maxClips, setMaxClips] = useState(10);
    const [analysisOnly, setAnalysisOnly] = useState(true);
    const [jobInstructions, setJobInstructions] = useState('');
    const [destinationUrl, setDestinationUrl] = useState('');
    const [destinationKeyword, setDestinationKeyword] = useState('Video');

    useEffect(() => {
        if (!resetToken) return;
        setUrl('');
        setFile(null);
        setJobInstructions('');
        setDestinationUrl('');
    }, [resetToken]);

    const handleSubmit = (e) => {
        e.preventDefault();
        const normalizedMaxClips = Math.max(1, Number(maxClips) || 10);
        if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, options: { interviewMode, allowLongClips: true, maxClips: normalizedMaxClips, analysisOnly, jobInstructions, destinationUrl, destinationKeyword } });
        } else if (mode === 'file' && file) {
            onProcess({ type: 'file', payload: file, options: { interviewMode, allowLongClips: true, maxClips: normalizedMaxClips, analysisOnly, jobInstructions, destinationUrl, destinationKeyword } });
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
        }
    };

    return (
        <div className="bg-surface border border-white/5 rounded-2xl p-6 animate-[fadeIn_0.6s_ease-out]">
            <div className="flex gap-4 mb-6 border-b border-white/5 pb-4">
                <button
                    onClick={() => setMode('url')}
                    className={`flex items-center gap-2 pb-2 px-2 transition-all ${mode === 'url'
                        ? 'text-primary border-b-2 border-primary -mb-[17px]'
                        : 'text-zinc-400 hover:text-white'
                        }`}
                >
                    <Youtube size={18} />
                    YouTube URL
                </button>
                <button
                    onClick={() => setMode('file')}
                    className={`flex items-center gap-2 pb-2 px-2 transition-all ${mode === 'file'
                        ? 'text-primary border-b-2 border-primary -mb-[17px]'
                        : 'text-zinc-400 hover:text-white'
                        }`}
                >
                    <Upload size={18} />
                    Datei hochladen
                </button>
            </div>

            <form onSubmit={handleSubmit}>
                {mode === 'url' ? (
                    <div className="space-y-4">
                        <input
                            type="url"
                            value={url}
                            onChange={(e) => setUrl(e.target.value)}
                            placeholder="https://www.youtube.com/watch?v=..."
                            className="input-field"
                            required
                        />
                    </div>
                ) : (
                    <div
                        className={`border-2 border-dashed rounded-xl p-8 text-center transition-all ${file ? 'border-primary/50 bg-primary/5' : 'border-zinc-700 hover:border-zinc-500 bg-white/5'
                            }`}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={handleDrop}
                    >
                        {file ? (
                            <div className="flex items-center justify-center gap-3 text-white">
                                <FileVideo className="text-primary" />
                                <span className="font-medium">{file.name}</span>
                                <button
                                    type="button"
                                    onClick={() => setFile(null)}
                                    className="p-1 hover:bg-white/10 rounded-full"
                                >
                                    <X size={16} />
                                </button>
                            </div>
                        ) : (
                            <label className="cursor-pointer block">
                                <input
                                    type="file"
                                    accept="video/*"
                                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                                    className="hidden"
                                />
                                <Upload className="mx-auto mb-3 text-zinc-500" size={24} />
                                <p className="text-zinc-400">Klicken zum Hochladen oder per Drag & Drop ablegen</p>
                                <p className="text-xs text-zinc-600 mt-1">MP4, MOV bis 500MB</p>
                            </label>
                        )}
                    </div>
                )}

                <label className="mt-4 flex items-start gap-3 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left">
                    <input
                        type="checkbox"
                        checked={interviewMode}
                        onChange={(e) => setInterviewMode(e.target.checked)}
                        className="mt-1 h-4 w-4 rounded border-white/20 bg-transparent text-primary focus:ring-primary"
                    />
                    <span>
                        <span className="block text-sm font-medium text-white">Interview-Modus</span>
                        <span className="block text-xs text-zinc-500">
                            Fuer zwei Personen im Bild: links/rechts erkannte Gesichter werden als Split-Screen oben und unten gerendert.
                        </span>
                    </span>
                </label>

                <div className="mt-3 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left">
                    <span>
                        <span className="block text-sm font-medium text-white">Long-Shorts 1-3 Minuten</span>
                        <span className="block text-xs text-zinc-500">
                            Die KI sucht standardmaessig zusammenhaengende Mehrwert-Clips zwischen 60 und 180 Sekunden.
                        </span>
                    </span>
                </div>

                <div className="mt-3 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left">
                    <label className="block text-sm font-medium text-white mb-2">Maximale Clip-Anzahl</label>
                    <input
                        type="number"
                        min="1"
                        step="1"
                        value={maxClips}
                        onChange={(e) => setMaxClips(e.target.value)}
                        className="input-field"
                    />
                    <span className="mt-2 block text-xs text-zinc-500">
                        Standard ist 10. Erhoehe den Wert nur, wenn du bewusst mehr Vorschlaege erzeugen willst.
                    </span>
                </div>

                <label className="mt-3 flex items-start gap-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-left">
                    <input
                        type="checkbox"
                        checked={analysisOnly}
                        onChange={(e) => setAnalysisOnly(e.target.checked)}
                        className="mt-1 h-4 w-4 rounded border-white/20 bg-transparent text-primary focus:ring-primary"
                    />
                    <span>
                        <span className="block text-sm font-medium text-white">Nur analysieren + Vorschau (empfohlen)</span>
                        <span className="block text-xs text-zinc-500">
                            Erst nur AI-Timestamps erzeugen. Du waehlst danach die besten Clips und renderst nur die wirklich gewuenschten.
                        </span>
                    </span>
                </label>

                <div className="mt-3 space-y-3 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left">
                    <div>
                        <span className="block text-sm font-medium text-white">Redaktioneller Kontext</span>
                        <span className="block text-xs text-zinc-500">
                            Profil: {activeProfileName || 'nicht zugeordnet'}{profileContext ? ' · Kanalbeschreibung wird automatisch mitgesendet.' : ''}
                        </span>
                    </div>
                    <textarea
                        value={jobInstructions}
                        onChange={(event) => setJobInstructions(event.target.value)}
                        rows={3}
                        className="input-field resize-y"
                        placeholder="Optionale Job-Anweisung, z. B. jedem Titel ein bestimmtes Wort voranstellen oder einen besonderen Schwerpunkt setzen."
                    />
                </div>

                <div className="mt-3 space-y-3 rounded-xl border border-emerald-500/15 bg-emerald-500/5 px-4 py-3 text-left">
                    <div>
                        <span className="block text-sm font-medium text-white">Kommentar-DM-Link (optional)</span>
                        <span className="block text-xs text-zinc-500">Beliebige HTTP(S)-URL: Podcast, Tutorial, Website oder Landingpage.</span>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_140px]">
                        <input
                            type="url"
                            value={destinationUrl}
                            onChange={(event) => setDestinationUrl(event.target.value)}
                            className="input-field"
                            placeholder="https://example.com/inhalt"
                        />
                        <input
                            type="text"
                            value={destinationKeyword}
                            onChange={(event) => setDestinationKeyword(event.target.value)}
                            className="input-field"
                            placeholder="Video"
                        />
                    </div>
                </div>

                <button
                    type="submit"
                    disabled={isProcessing || (mode === 'url' && !url) || (mode === 'file' && !file)}
                    className="w-full btn-primary mt-6 flex items-center justify-center gap-2"
                >
                    {isProcessing ? (
                        <>
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                            {submittingLabel}
                        </>
                    ) : (
                        <>
                            {submitLabel || (analysisOnly ? 'Analysieren & Entwürfe einreihen' : 'Clips erzeugen & einreihen')}
                        </>
                    )}
                </button>
                {helperText && (
                    <p className="mt-3 text-center text-xs text-zinc-500">{helperText}</p>
                )}
            </form>
        </div>
    );
}

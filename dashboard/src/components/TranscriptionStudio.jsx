import React, { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Clock3, Download, FileAudio, FileVideo, Languages, Loader2, Type, Upload } from 'lucide-react';
import { getApiUrl } from '../config';

const STORAGE_KEY = 'openshorts_transcription_session_v1';

const DEFAULT_FORMATS = {
    txt: true,
    json: true,
    srt: true,
    vtt: true,
    tsv: false,
};

const TIMESTAMP_ONLY_FORMATS = new Set(['srt', 'vtt', 'tsv']);

const statusStyles = {
    queued: 'border-zinc-500/20 bg-zinc-500/10 text-zinc-200',
    processing: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100',
    completed: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
    failed: 'border-red-500/20 bg-red-500/10 text-red-200',
};

const readErrorMessage = async (res) => {
    const text = await res.text();
    try {
        const json = JSON.parse(text);
        return json.detail || text;
    } catch (error) {
        return text;
    }
};

const normalizeFormatSelection = (selection, withTimestamps) => Object.fromEntries(
    Object.entries(DEFAULT_FORMATS).map(([key, enabledByDefault]) => [
        key,
        TIMESTAMP_ONLY_FORMATS.has(key) ? (withTimestamps ? Boolean(selection?.[key] ?? enabledByDefault) : false) : Boolean(selection?.[key] ?? enabledByDefault),
    ]),
);

export default function TranscriptionStudio() {
    const [selectedFile, setSelectedFile] = useState(null);
    const [withTimestamps, setWithTimestamps] = useState(true);
    const [preferredLanguage, setPreferredLanguage] = useState('de');
    const [formatSelection, setFormatSelection] = useState(DEFAULT_FORMATS);
    const [session, setSession] = useState(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [statusMessage, setStatusMessage] = useState('');

    const selectedFormats = useMemo(
        () => Object.entries(normalizeFormatSelection(formatSelection, withTimestamps))
            .filter(([, enabled]) => enabled)
            .map(([format]) => format),
        [formatSelection, withTimestamps],
    );

    const fetchSession = async (sessionId) => {
        const res = await fetch(getApiUrl(`/api/transcription/${sessionId}`));
        if (!res.ok) throw new Error(await readErrorMessage(res));
        const data = await res.json();
        setSession(data.session || null);
    };

    useEffect(() => {
        const storedSessionId = localStorage.getItem(STORAGE_KEY);
        if (!storedSessionId) return;
        fetchSession(storedSessionId).catch(() => {
            localStorage.removeItem(STORAGE_KEY);
        });
    }, []);

    useEffect(() => {
        if (!session?.session_id) return;
        localStorage.setItem(STORAGE_KEY, session.session_id);
    }, [session?.session_id]);

    useEffect(() => {
        if (!withTimestamps) {
            setFormatSelection((prev) => normalizeFormatSelection(prev, false));
        }
    }, [withTimestamps]);

    useEffect(() => {
        if (!session?.session_id) return undefined;
        if (!['queued', 'processing'].includes(session.status)) return undefined;
        const interval = window.setInterval(() => {
            fetchSession(session.session_id).catch(() => {});
        }, 2000);
        return () => window.clearInterval(interval);
    }, [session?.session_id, session?.status]);

    const handleStart = async () => {
        if (!selectedFile) {
            setStatusMessage('Bitte zuerst eine Audio- oder Videodatei auswählen.');
            return;
        }

        setIsSubmitting(true);
        setStatusMessage('');

        try {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('with_timestamps', withTimestamps ? 'true' : 'false');
            formData.append('preferred_language', preferredLanguage || 'de');
            formData.append('export_formats', selectedFormats.join(','));

            const res = await fetch(getApiUrl('/api/transcription/upload'), {
                method: 'POST',
                body: formData,
            });
            if (!res.ok) throw new Error(await readErrorMessage(res));

            const data = await res.json();
            setSession(data.session || null);
            setStatusMessage('Transkription gestartet.');
        } catch (error) {
            setStatusMessage(error.message || 'Transkription konnte nicht gestartet werden.');
        } finally {
            setIsSubmitting(false);
        }
    };

    const currentFormats = normalizeFormatSelection(formatSelection, withTimestamps);
    const runtime = session?.runtime || {};
    const transcript = session?.transcript || null;

    return (
        <div className="h-full overflow-y-auto touch-scroll p-5 md:p-8 max-w-5xl mx-auto animate-[fadeIn_0.3s_ease-out]">
            <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
                <div>
                    <h1 className="text-2xl font-bold text-white">Whisper Transkription</h1>
                    <p className="mt-2 text-sm text-zinc-500 max-w-2xl">
                        Videos oder Audiodateien lokal mit GPU transkribieren, Deutsch priorisieren und die Ausgabe direkt als
                        `txt`, `json`, `srt`, `vtt` oder `tsv` exportieren.
                    </p>
                </div>
                <div className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-[11px] uppercase tracking-wide text-cyan-100">
                    GPU Whisper
                </div>
            </div>

            <div className="glass-panel p-6">
                <div className="grid gap-6 lg:grid-cols-[1.3fr_0.9fr]">
                    <div className="space-y-5">
                        <div>
                            <label className="block text-sm text-zinc-400 mb-2">Datei auswählen</label>
                            <label className="flex cursor-pointer items-center gap-3 rounded-2xl border border-dashed border-white/15 bg-black/20 px-4 py-4 text-left hover:border-cyan-400/30 hover:bg-black/30">
                                <div className="rounded-xl bg-cyan-500/10 p-3 text-cyan-200">
                                    {selectedFile?.type?.startsWith('audio/') ? <FileAudio size={20} /> : <FileVideo size={20} />}
                                </div>
                                <div className="min-w-0 flex-1">
                                    <div className="text-sm font-medium text-white truncate">
                                        {selectedFile ? selectedFile.name : 'Audio- oder Videodatei wählen'}
                                    </div>
                                    <div className="mt-1 text-xs text-zinc-500">
                                        MP3, WAV, M4A, MP4, MOV, MKV, WEBM und ähnliche Container funktionieren.
                                    </div>
                                </div>
                                <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-zinc-200">
                                    Datei wählen
                                </div>
                                <input
                                    type="file"
                                    accept="audio/*,video/*"
                                    className="hidden"
                                    onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
                                />
                            </label>
                        </div>

                        <div className="grid gap-4 md:grid-cols-2">
                            <label className="rounded-xl border border-white/10 bg-black/20 px-4 py-3">
                                <div className="flex items-center gap-2 text-sm font-medium text-white">
                                    <Languages size={16} className="text-cyan-200" />
                                    Sprache
                                </div>
                                <select
                                    value={preferredLanguage}
                                    onChange={(e) => setPreferredLanguage(e.target.value)}
                                    className="mt-3 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-400/40"
                                >
                                    <option value="de">Deutsch priorisieren</option>
                                    <option value="">Auto erkennen</option>
                                    <option value="en">Englisch priorisieren</option>
                                </select>
                                <p className="mt-2 text-xs text-zinc-500">
                                    `Deutsch priorisieren` erzwingt im Backend `large-v3` auf der GPU für maximale deutsche Whisper-Qualität dieses Stacks.
                                </p>
                            </label>

                            <label className="rounded-xl border border-white/10 bg-black/20 px-4 py-3">
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <div className="flex items-center gap-2 text-sm font-medium text-white">
                                            <Clock3 size={16} className="text-cyan-200" />
                                            Timestamps
                                        </div>
                                        <p className="mt-1 text-xs text-zinc-500">
                                            Für SRT, VTT und segmentierte Exporte.
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setWithTimestamps((prev) => !prev)}
                                        className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${withTimestamps ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100' : 'border-white/10 bg-white/5 text-zinc-300'}`}
                                    >
                                        {withTimestamps ? 'Mit' : 'Ohne'}
                                    </button>
                                </div>
                            </label>
                        </div>

                        <div>
                            <label className="block text-sm text-zinc-400 mb-2">Exportformate</label>
                            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
                                {Object.keys(DEFAULT_FORMATS).map((format) => {
                                    const disabled = TIMESTAMP_ONLY_FORMATS.has(format) && !withTimestamps;
                                    return (
                                        <label
                                            key={format}
                                            className={`rounded-xl border px-3 py-3 text-sm ${disabled ? 'border-white/5 bg-black/10 text-zinc-600' : 'border-white/10 bg-black/20 text-zinc-200'}`}
                                        >
                                            <div className="flex items-center justify-between gap-3">
                                                <span className="font-semibold uppercase">{format}</span>
                                                <input
                                                    type="checkbox"
                                                    checked={currentFormats[format]}
                                                    disabled={disabled}
                                                    onChange={(e) => setFormatSelection((prev) => ({ ...prev, [format]: e.target.checked }))}
                                                    className="h-4 w-4 rounded border-zinc-600 bg-black/50 text-cyan-400 focus:ring-cyan-400"
                                                />
                                            </div>
                                        </label>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-3">
                            <button
                                type="button"
                                onClick={handleStart}
                                disabled={isSubmitting || !selectedFile}
                                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-600 to-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:from-cyan-500 hover:to-sky-500 disabled:opacity-60"
                            >
                                {isSubmitting ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                                {isSubmitting ? 'Startet...' : 'Transkription starten'}
                            </button>
                            {statusMessage && (
                                <span className="text-sm text-zinc-400">{statusMessage}</span>
                            )}
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                            <div className="flex items-center justify-between gap-3">
                                <div className="text-sm font-medium text-white">Aktueller Status</div>
                                <span className={`rounded-full border px-3 py-1 text-[11px] uppercase tracking-wide ${statusStyles[session?.status] || 'border-white/10 bg-white/5 text-zinc-300'}`}>
                                    {session?.status || 'idle'}
                                </span>
                            </div>
                            <p className="mt-3 text-sm text-zinc-400">
                                {session?.message || 'Noch keine Transkription gestartet.'}
                            </p>
                            {session?.error && (
                                <p className="mt-2 text-sm text-red-300">{session.error}</p>
                            )}
                            {runtime?.model && (
                                <div className="mt-4 grid gap-2 text-xs text-zinc-500">
                                    <div>Modell: <span className="text-zinc-300">{runtime.model}</span></div>
                                    <div>Device: <span className="text-zinc-300">{runtime.device}</span></div>
                                    <div>Compute: <span className="text-zinc-300">{runtime.compute_type}</span></div>
                                    <div>Sprache: <span className="text-zinc-300">{session?.preferred_language || 'auto'}</span></div>
                                </div>
                            )}
                        </div>

                        {transcript && (
                            <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                                <div className="flex items-center gap-2 text-sm font-medium text-white">
                                    <Type size={16} className="text-cyan-200" />
                                    Transkript
                                </div>
                                <div className="mt-3 grid gap-2 text-xs text-zinc-500">
                                    <div>Segmente: <span className="text-zinc-300">{transcript.segment_count || 0}</span></div>
                                    <div>Dauer: <span className="text-zinc-300">{Number(transcript.duration_seconds || 0).toFixed(1)}s</span></div>
                                    <div>Erkannte Sprache: <span className="text-zinc-300">{transcript.language || 'unbekannt'}</span></div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {session?.exports?.length > 0 && (
                <div className="glass-panel p-6 mt-8">
                    <div className="flex items-center gap-2 mb-4">
                        <CheckCircle2 size={18} className="text-emerald-300" />
                        <h2 className="text-lg font-semibold text-white">Exporte</h2>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                        {session.exports.map((file) => (
                            <a
                                key={file.filename}
                                href={getApiUrl(file.url)}
                                target="_blank"
                                rel="noreferrer"
                                className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-left hover:bg-black/30"
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div>
                                        <div className="text-sm font-medium text-white uppercase">{file.format}</div>
                                        <div className="mt-1 text-xs text-zinc-500">{file.filename}</div>
                                    </div>
                                    <Download size={16} className="text-cyan-200" />
                                </div>
                            </a>
                        ))}
                    </div>
                </div>
            )}

            {transcript?.preview && (
                <div className="glass-panel p-6 mt-8">
                    <div className="flex items-center gap-2 mb-4">
                        <Type size={18} className="text-cyan-200" />
                        <h2 className="text-lg font-semibold text-white">Vorschau</h2>
                    </div>
                    <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-xl border border-white/10 bg-black/30 p-4 text-sm text-zinc-200 custom-scrollbar touch-scroll">
                        {transcript.preview}
                    </pre>
                </div>
            )}
        </div>
    );
}

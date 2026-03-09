import React, { useState, useEffect } from 'react';
import { Key, Eye, EyeOff, Check } from 'lucide-react';

export default function KeyInput({ provider, onKeySet, savedKey, ollamaBaseUrl, onOllamaBaseUrlSet, ollamaModel, onOllamaModelSet }) {
    const [key, setKey] = useState(savedKey || '');
    const [isVisible, setIsVisible] = useState(false);
    const [isSaved, setIsSaved] = useState(provider === 'gemini' ? !!savedKey : !!ollamaModel);

    useEffect(() => {
        if (savedKey) setKey(savedKey);
    }, [savedKey]);

    const handleSave = () => {
        if (provider === 'gemini' && key.trim().length > 0) {
            onKeySet(key);
            setIsSaved(true);
        }
        if (provider === 'ollama' && ollamaModel.trim().length > 0) {
            onOllamaBaseUrlSet(ollamaBaseUrl);
            onOllamaModelSet(ollamaModel);
            setIsSaved(true);
        }
    };

    useEffect(() => {
        setIsSaved(provider === 'gemini' ? !!savedKey : !!ollamaModel);
    }, [provider, savedKey, ollamaModel]);

    return (
        <div className="bg-surface border border-white/5 rounded-2xl p-6 mb-8 animate-[fadeIn_0.5s_ease-out]">
            <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-accent/20 rounded-lg text-accent">
                    <Key size={20} />
                </div>
                <h2 className="text-lg font-semibold">{provider === 'gemini' ? 'Gemini API-Key' : 'Ollama-Konfiguration'}</h2>
            </div>

            {provider === 'gemini' ? (
                <div className="flex gap-3">
                    <div className="relative flex-1">
                        <input
                            type={isVisible ? "text" : "password"}
                            value={key}
                            onChange={(e) => {
                                setKey(e.target.value);
                                setIsSaved(false);
                            }}
                            placeholder="AIzaSy..."
                            className="input-field pr-12 font-mono"
                        />
                        <button
                            onClick={() => setIsVisible(!isVisible)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white transition-colors"
                        >
                            {isVisible ? <EyeOff size={18} /> : <Eye size={18} />}
                        </button>
                    </div>
                    <button
                        onClick={handleSave}
                        disabled={!key || isSaved}
                        className={`px-6 rounded-xl font-medium transition-all flex items-center gap-2 ${isSaved
                            ? 'bg-green-500/20 text-green-400 cursor-default'
                            : 'bg-primary hover:bg-blue-600 text-white shadow-lg shadow-primary/20'
                            }`}
                    >
                        {isSaved ? <><Check size={18} /> Bereit</> : 'Key setzen'}
                    </button>
                </div>
            ) : (
                <div className="space-y-3">
                    <input
                        type="text"
                        value={ollamaBaseUrl}
                        onChange={(e) => {
                            onOllamaBaseUrlSet(e.target.value);
                            setIsSaved(false);
                        }}
                        placeholder="http://127.0.0.1:11434"
                        className="input-field font-mono"
                    />
                    <div className="flex gap-3">
                        <input
                            type="text"
                            value={ollamaModel}
                            onChange={(e) => {
                                onOllamaModelSet(e.target.value);
                                setIsSaved(false);
                            }}
                            placeholder="gemma3:12b"
                            className="input-field font-mono"
                        />
                        <button
                            onClick={handleSave}
                            disabled={!ollamaModel || isSaved}
                            className={`px-6 rounded-xl font-medium transition-all flex items-center gap-2 ${isSaved
                                ? 'bg-green-500/20 text-green-400 cursor-default'
                                : 'bg-primary hover:bg-blue-600 text-white shadow-lg shadow-primary/20'
                                }`}
                        >
                            {isSaved ? <><Check size={18} /> Bereit</> : 'Speichern'}
                        </button>
                    </div>
                </div>
            )}
            <p className="mt-3 text-xs text-zinc-500">
                {provider === 'gemini' ? (
                    <>
                        Dein Key wird zur Bequemlichkeit lokal im Browser gespeichert.
                        <br />
                        <a
                            href="https://aistudio.google.com/app/apikey"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:underline mt-1 inline-block"
                        >
                            Kostenlosen Gemini API Key holen →
                        </a>
                    </>
                ) : (
                    <>
                        Base-URL und Modell werden lokal im Browser gespeichert.
                        <br />
                        Das Backend läuft im Host-Netzwerk, daher ist lokales Ollama meist `http://127.0.0.1:11434`.
                        Verwende den exakten Tag aus `ollama list`, z.B. `gemma3:12b`.
                    </>
                )}
            </p>
        </div>
    );
}

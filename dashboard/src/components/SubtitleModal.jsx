import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X, Type, Loader2 } from 'lucide-react';
import { BACKGROUND_OPTIONS, DEFAULT_SUBTITLE_STYLE, FONT_OPTIONS } from '../overlayOptions';

export default function SubtitleModal({ isOpen, onClose, onGenerate, onApplyAsJobDefault, isProcessing, videoUrl, defaultSettings = DEFAULT_SUBTITLE_STYLE }) {
    const [yPosition, setYPosition] = useState(defaultSettings.yPosition ?? 86);
    const [fontSize, setFontSize] = useState(defaultSettings.fontSize || 24);
    const [fontFamily, setFontFamily] = useState(defaultSettings.fontFamily || DEFAULT_SUBTITLE_STYLE.fontFamily);
    const [backgroundStyle, setBackgroundStyle] = useState(defaultSettings.backgroundStyle || DEFAULT_SUBTITLE_STYLE.backgroundStyle);
    const [previewTop, setPreviewTop] = useState(0);
    const previewFrameRef = useRef(null);
    const previewBoxRef = useRef(null);

    const presetPositions = {
        top: 14,
        middle: 50,
        bottom: 86,
    };

    useEffect(() => {
        if (!isOpen) return;
        setYPosition(defaultSettings.yPosition ?? presetPositions[defaultSettings.position || 'bottom'] ?? 86);
        setFontSize(defaultSettings.fontSize || 24);
        setFontFamily(defaultSettings.fontFamily || DEFAULT_SUBTITLE_STYLE.fontFamily);
        setBackgroundStyle(defaultSettings.backgroundStyle || DEFAULT_SUBTITLE_STYLE.backgroundStyle);
    }, [isOpen, defaultSettings]);

    useEffect(() => {
        if (!isOpen) return undefined;

        const updatePlacement = () => {
            const frame = previewFrameRef.current;
            const box = previewBoxRef.current;
            if (!frame || !box) {
                return;
            }

            const frameRect = frame.getBoundingClientRect();
            const boxRect = box.getBoundingClientRect();
            const desiredCenterY = (Math.max(0, Math.min(100, Number(yPosition) || 0)) / 100) * frameRect.height;
            const maxTop = Math.max(0, frameRect.height - boxRect.height);
            const nextTop = Math.min(Math.max(0, desiredCenterY - (boxRect.height / 2)), maxTop);
            setPreviewTop(nextTop);
        };

        updatePlacement();

        const resizeObserver = new ResizeObserver(updatePlacement);
        if (previewFrameRef.current) resizeObserver.observe(previewFrameRef.current);
        if (previewBoxRef.current) resizeObserver.observe(previewBoxRef.current);
        window.addEventListener('resize', updatePlacement);

        return () => {
            resizeObserver.disconnect();
            window.removeEventListener('resize', updatePlacement);
        };
    }, [isOpen, yPosition, fontSize, fontFamily, backgroundStyle]);

    if (!isOpen) return null;

    const position = Object.entries(presetPositions).reduce((closestKey, [key, value]) => {
        const currentDistance = Math.abs(value - yPosition);
        const closestDistance = Math.abs(presetPositions[closestKey] - yPosition);
        return currentDistance < closestDistance ? key : closestKey;
    }, 'bottom');

    const previewStyle = backgroundStyle === 'light-box'
        ? { backgroundColor: 'rgba(255,255,255,0.86)', color: '#111' }
        : backgroundStyle === 'yellow-box'
            ? { backgroundColor: 'rgba(255,228,92,0.92)', color: '#111' }
            : backgroundStyle === 'transparent'
                ? { backgroundColor: 'transparent', color: '#fff', textShadow: '0 0 12px rgba(0,0,0,0.9), 0 2px 4px rgba(0,0,0,0.9)' }
            : { backgroundColor: 'rgba(0,0,0,0.62)', color: '#fff' };

    return createPortal(
        <div className="fixed inset-0 z-[1000] flex items-start md:items-center justify-center p-2 md:p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out] overflow-y-auto touch-scroll">
            <div className="bg-[#121214] border border-white/10 p-4 md:p-6 rounded-2xl w-full max-w-4xl shadow-2xl relative flex flex-col md:flex-row gap-4 md:gap-6 my-2 md:my-0 max-h-[calc(100dvh-1rem)] md:max-h-[90vh] overflow-y-auto md:overflow-hidden touch-scroll">
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10"
                >
                    <X size={20} />
                </button>

                {/* Left: Preview */}
                <div
                    ref={previewFrameRef}
                    className="relative w-full flex-none aspect-[9/16] overflow-hidden rounded-lg border border-white/5 bg-black md:flex-1 md:min-h-0"
                >
                     <video src={videoUrl} className="w-full h-full object-contain opacity-50" muted playsInline />
                     
                     {/* Subtitle Overlay Preview */}
                     <div
                        className="absolute left-1/2 -translate-x-1/2 transition-all duration-200 pointer-events-none flex justify-center text-center"
                        style={{ top: `${previewTop}px`, width: '100%' }}
                     >
                        <span 
                            ref={previewBoxRef}
                            className="font-bold px-2 py-1 rounded shadow-lg backdrop-blur-sm border border-white/10 text-center"
                            style={{ 
                                fontSize: `${Math.max(14, Math.round(fontSize * 0.6))}px`,
                                maxWidth: '80%',
                                display: 'inline-block',
                                margin: '0 auto',
                                textAlign: 'center',
                                fontFamily,
                                ...previewStyle,
                            }} 
                        >
                            So sehen deine Untertitel<br/>im Video aus
                        </span>
                     </div>
                </div>

                {/* Right: Controls */}
                <div className="w-full md:w-80 flex flex-col md:min-h-0">
                    <h3 className="text-lg md:text-xl font-bold text-white mb-4 md:mb-6 flex items-center gap-2">
                        <Type className="text-primary" /> Auto-Untertitel
                    </h3>

                    <div className="space-y-4 md:space-y-6 md:flex-1 md:overflow-y-auto custom-scrollbar touch-scroll pr-1 md:pr-2">
                        {/* Position Selector */}
                        <div>
                            <label className="text-[11px] md:text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 md:mb-3 block">Schnellposition</label>
                            <div className="grid grid-cols-1 gap-2">
                                <button 
                                    onClick={() => setYPosition(presetPositions.top)}
                                    className={`p-2.5 md:p-3 rounded-lg md:rounded-xl border flex items-center gap-2 md:gap-3 transition-all ${Math.abs(yPosition - presetPositions.top) < 1 ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                >
                                    <div className="w-7 h-7 md:w-8 md:h-8 rounded-lg bg-black/50 border border-white/10 flex items-start justify-center pt-1">
                                        <div className="w-4 h-0.5 bg-white/50 rounded-full"></div>
                                    </div>
                                    <span className="text-sm md:text-base font-medium">Oben</span>
                                </button>
                                
                                <button 
                                    onClick={() => setYPosition(presetPositions.middle)}
                                    className={`p-2.5 md:p-3 rounded-lg md:rounded-xl border flex items-center gap-2 md:gap-3 transition-all ${Math.abs(yPosition - presetPositions.middle) < 1 ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                >
                                    <div className="w-7 h-7 md:w-8 md:h-8 rounded-lg bg-black/50 border border-white/10 flex items-center justify-center">
                                        <div className="w-4 h-0.5 bg-white/50 rounded-full"></div>
                                    </div>
                                    <span className="text-sm md:text-base font-medium">Mitte</span>
                                </button>
                                
                                <button 
                                    onClick={() => setYPosition(presetPositions.bottom)}
                                    className={`p-2.5 md:p-3 rounded-lg md:rounded-xl border flex items-center gap-2 md:gap-3 transition-all ${Math.abs(yPosition - presetPositions.bottom) < 1 ? 'bg-primary/20 border-primary text-white' : 'bg-white/5 border-white/5 text-zinc-400 hover:bg-white/10'}`}
                                >
                                    <div className="w-7 h-7 md:w-8 md:h-8 rounded-lg bg-black/50 border border-white/10 flex items-end justify-center pb-1">
                                        <div className="w-4 h-0.5 bg-white/50 rounded-full"></div>
                                    </div>
                                    <span className="text-sm md:text-base font-medium">Unten</span>
                                </button>
                            </div>
                        </div>

                        <div>
                            <label className="text-[11px] md:text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 md:mb-3 block">Y-Position</label>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                step="1"
                                value={yPosition}
                                onChange={(e) => setYPosition(Number(e.target.value))}
                                className="w-full accent-yellow-500"
                            />
                            <div className="mt-2 flex justify-between text-[11px] text-zinc-500">
                                <span>Oben</span>
                                <span>{yPosition}%</span>
                                <span>Unten</span>
                            </div>
                        </div>

                        <div>
                            <label className="text-[11px] md:text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 md:mb-3 block">Schriftart</label>
                            <select
                                value={fontFamily}
                                onChange={(e) => setFontFamily(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg md:rounded-xl p-2.5 md:p-3 text-sm text-white focus:outline-none focus:border-primary/50"
                            >
                                {FONT_OPTIONS.map((option) => (
                                    <option key={option} value={option}>{option}</option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label className="text-[11px] md:text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 md:mb-3 block">Hintergrund</label>
                            <select
                                value={backgroundStyle}
                                onChange={(e) => setBackgroundStyle(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-lg md:rounded-xl p-2.5 md:p-3 text-sm text-white focus:outline-none focus:border-primary/50"
                            >
                                {BACKGROUND_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label className="text-[11px] md:text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 md:mb-3 block">Größe</label>
                            <input
                                type="range"
                                min="18"
                                max="44"
                                value={fontSize}
                                onChange={(e) => setFontSize(Number(e.target.value))}
                                className="w-full"
                            />
                            <div className="text-[11px] md:text-xs text-zinc-500 mt-2">{fontSize}px</div>
                        </div>
                    </div>

                    {onApplyAsJobDefault && (
                        <button
                            onClick={() => onApplyAsJobDefault({ position, yPosition, fontSize, fontFamily, backgroundStyle })}
                            disabled={isProcessing}
                            className="w-full py-2.5 md:py-3 mt-4 border border-white/15 bg-white/5 hover:bg-white/10 text-zinc-100 text-sm font-semibold rounded-xl transition-all active:scale-[0.98]"
                        >
                            Für alle Clips im Job übernehmen
                        </button>
                    )}

                    <button
                        onClick={() => onGenerate({ position, yPosition, fontSize, fontFamily, backgroundStyle })}
                        disabled={isProcessing}
                        className="w-full py-3 md:py-4 mt-3 bg-gradient-to-r from-yellow-500 to-orange-500 hover:from-yellow-400 hover:to-orange-400 text-black text-sm md:text-base font-bold rounded-xl shadow-lg shadow-orange-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2"
                    >
                        {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Type size={20} />}
                        {isProcessing ? 'Generiere...' : 'Untertitel einbrennen'}
                    </button>
                    
                    <p className="text-[10px] text-zinc-500 text-center mt-3">
                        Nutzt Wort-Timestamps aus der KI für saubere Synchronisation.
                    </p>
                </div>
            </div>
        </div>,
        document.body
    );
}

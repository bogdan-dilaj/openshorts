import React, { useEffect, useRef, useState } from 'react';
import { X, Sparkles, Loader2, Maximize, MoveVertical, MoveHorizontal, Columns3, AlignLeft, AlignCenter, AlignRight } from 'lucide-react';
import { BACKGROUND_OPTIONS, DEFAULT_HOOK_STYLE, FONT_OPTIONS, GRID_OPTIONS, HOOK_WIDTH_OPTIONS } from '../overlayOptions';

export default function HookModal({ isOpen, onClose, onGenerate, isProcessing, videoUrl, initialText, defaultSettings = DEFAULT_HOOK_STYLE }) {
    const [text, setText] = useState(initialText || 'POV: You are using the viral hook feature');
    const [size, setSize] = useState(defaultSettings.size || 'M'); // S, M, L
    const [widthPreset, setWidthPreset] = useState(defaultSettings.widthPreset || 'wide');
    const [fontFamily, setFontFamily] = useState(defaultSettings.fontFamily || DEFAULT_HOOK_STYLE.fontFamily);
    const [backgroundStyle, setBackgroundStyle] = useState(defaultSettings.backgroundStyle || DEFAULT_HOOK_STYLE.backgroundStyle);
    const [xPosition, setXPosition] = useState(defaultSettings.xPosition ?? 50);
    const [yPosition, setYPosition] = useState(defaultSettings.yPosition ?? 12);
    const [textAlign, setTextAlign] = useState(defaultSettings.textAlign || 'center');
    const [previewPlacement, setPreviewPlacement] = useState({ left: 0, top: 0 });
    const previewFrameRef = useRef(null);
    const previewBoxRef = useRef(null);

    const legacyVerticalToPercent = {
        top: 12,
        center: 50,
        bottom: 88,
    };

    const legacyHorizontalToPercent = {
        left: 18,
        center: 50,
        right: 82,
    };

    useEffect(() => {
        if (!isOpen) return;
        setText(initialText || 'POV: You are using the viral hook feature');
        setSize(defaultSettings.size || 'M');
        setWidthPreset(defaultSettings.widthPreset || 'wide');
        setFontFamily(defaultSettings.fontFamily || DEFAULT_HOOK_STYLE.fontFamily);
        setBackgroundStyle(defaultSettings.backgroundStyle || DEFAULT_HOOK_STYLE.backgroundStyle);
        setXPosition(
            defaultSettings.xPosition
                ?? legacyHorizontalToPercent[defaultSettings.horizontalPosition || 'center']
                ?? 50
        );
        setYPosition(
            defaultSettings.yPosition
                ?? legacyVerticalToPercent[defaultSettings.position || 'top']
                ?? 12
        );
        setTextAlign(defaultSettings.textAlign || defaultSettings.horizontalPosition || 'center');
    }, [isOpen, initialText, defaultSettings]);

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

            const desiredCenterX = (Math.max(0, Math.min(100, Number(xPosition) || 0)) / 100) * frameRect.width;
            const desiredCenterY = (Math.max(0, Math.min(100, Number(yPosition) || 0)) / 100) * frameRect.height;

            const maxLeft = Math.max(0, frameRect.width - boxRect.width);
            const maxTop = Math.max(0, frameRect.height - boxRect.height);
            const nextLeft = Math.min(Math.max(0, desiredCenterX - (boxRect.width / 2)), maxLeft);
            const nextTop = Math.min(Math.max(0, desiredCenterY - (boxRect.height / 2)), maxTop);

            setPreviewPlacement({ left: nextLeft, top: nextTop });
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
    }, [isOpen, text, size, widthPreset, fontFamily, backgroundStyle, xPosition, yPosition, textAlign]);

    if (!isOpen) return null;

    const getSizeStyle = () => {
        switch (size) {
            case 'S': return { fontSize: '14px' };
            case 'L': return { fontSize: '24px' };
            case 'M': default: return { fontSize: '18px' };
        }
    };

    const widthStyleMap = {
        full: '92%',
        wide: '78%',
        medium: '62%',
        narrow: '46%',
    };

    const backgroundPreview = backgroundStyle === 'dark-box'
        ? { backgroundColor: 'rgba(20,20,20,0.86)', color: '#fff' }
        : backgroundStyle === 'yellow-box'
            ? { backgroundColor: 'rgba(255,228,92,0.92)', color: '#111' }
            : backgroundStyle === 'transparent'
                ? { backgroundColor: 'transparent', color: '#fff', textShadow: '0 0 12px rgba(0,0,0,0.95), 0 2px 4px rgba(0,0,0,0.95)' }
                : { backgroundColor: 'rgba(255,255,255,0.82)', color: '#111' };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-[fadeIn_0.2s_ease-out]">
            <div className="bg-[#121214] border border-white/10 p-6 rounded-2xl w-full max-w-4xl shadow-2xl relative flex flex-col md:flex-row gap-6 max-h-[90vh]">
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 text-zinc-500 hover:text-white z-10"
                >
                    <X size={20} />
                </button>

                {/* Left: Preview */}
                <div
                    ref={previewFrameRef}
                    className="flex-1 flex flex-col items-center justify-center bg-black rounded-lg border border-white/5 overflow-hidden relative aspect-[9/16] max-h-[600px]"
                >
                    <video src={videoUrl} className="w-full h-full object-contain opacity-50" muted playsInline />

                    {/* Hook Overlay Preview */}
                    <div
                        ref={previewBoxRef}
                        className="absolute pointer-events-none transition-all duration-200"
                        style={{
                            left: `${previewPlacement.left}px`,
                            top: `${previewPlacement.top}px`,
                            width: 'fit-content',
                            maxWidth: widthStyleMap[widthPreset] || widthStyleMap.wide,
                        }}
                    >
                        <div
                            className="text-black font-bold px-3 py-2 rounded-xl shadow-2xl whitespace-pre-wrap break-words transition-all duration-200"
                            style={{
                                ...getSizeStyle(),
                                ...backgroundPreview,
                                fontFamily,
                                boxShadow: backgroundStyle === 'transparent' ? 'none' : '0 4px 15px rgba(0,0,0,0.5)',
                                paddingTop: '10px', // Reduced to scale (backend is 20px on 1080p ~ 2%)
                                paddingBottom: '10px',
                                paddingLeft: '12px',
                                paddingRight: '12px',
                                textAlign,
                            }}
                        >
                            {text || "Enter your text..."}
                        </div>
                    </div>
                </div>

                {/* Right: Controls */}
                <div className="w-full md:w-80 flex flex-col">
                    <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                        <Sparkles className="text-yellow-400" /> Viral Hook
                    </h3>

                    <div className="space-y-6 flex-1 overflow-y-auto custom-scrollbar pr-2">
                        {/* Text Input */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Text</label>
                            <textarea
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                rows={4}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white placeholder-zinc-600 focus:outline-none focus:border-yellow-500/50 resize-none font-serif"
                                placeholder={"Enter text that will stop the scroll...\nUse line breaks if you want manual wrapping."}
                            />
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                                <Columns3 size={12} /> Quick Presets
                            </label>
                            <div className="grid grid-cols-3 gap-2">
                                {GRID_OPTIONS.map((option) => (
                                    <button
                                        key={option.value}
                                        onClick={() => {
                                            const [nextVertical, nextHorizontal = 'center'] = option.value.split('-');
                                            setXPosition(legacyHorizontalToPercent[nextHorizontal] ?? 50);
                                            setYPosition(legacyVerticalToPercent[nextVertical === 'center' ? 'center' : nextVertical] ?? 12);
                                        }}
                                        className={`py-2 px-1 rounded-lg text-[11px] font-bold transition-all border ${Math.abs((legacyHorizontalToPercent[(option.value.split('-')[1] || 'center')] ?? 50) - xPosition) < 1
                                            && Math.abs((legacyVerticalToPercent[(option.value.split('-')[0] === 'center' ? 'center' : option.value.split('-')[0])] ?? 12) - yPosition) < 1
                                            ? 'bg-white text-black border-white'
                                            : 'bg-white/5 text-zinc-400 border-white/5 hover:bg-white/10'
                                            }`}
                                    >
                                        {option.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                                <MoveHorizontal size={12} /> X Position
                            </label>
                            <input
                                type="range"
                                min="0"
                                max="100"
                                step="1"
                                value={xPosition}
                                onChange={(e) => setXPosition(Number(e.target.value))}
                                className="w-full accent-yellow-500"
                            />
                            <div className="mt-2 flex justify-between text-[11px] text-zinc-500">
                                <span>Left</span>
                                <span>{xPosition}%</span>
                                <span>Right</span>
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                                <MoveVertical size={12} /> Y Position
                            </label>
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
                                <span>Top</span>
                                <span>{yPosition}%</span>
                                <span>Bottom</span>
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Text Align</label>
                            <div className="grid grid-cols-3 gap-2">
                                {[
                                    { value: 'left', label: 'Left', icon: AlignLeft },
                                    { value: 'center', label: 'Center', icon: AlignCenter },
                                    { value: 'right', label: 'Right', icon: AlignRight },
                                ].map((option) => {
                                    const Icon = option.icon;
                                    return (
                                        <button
                                            key={option.value}
                                            onClick={() => setTextAlign(option.value)}
                                            className={`py-2 px-1 rounded-lg text-xs font-bold transition-all border flex items-center justify-center gap-2 ${textAlign === option.value
                                                ? 'bg-white text-black border-white'
                                                : 'bg-white/5 text-zinc-400 border-white/5 hover:bg-white/10'
                                                }`}
                                        >
                                            <Icon size={12} />
                                            {option.label}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        {/* Size Control */}
                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                                <Maximize size={12} /> Size
                            </label>
                            <div className="grid grid-cols-3 gap-2">
                                {['S', 'M', 'L'].map((sz) => (
                                    <button
                                        key={sz}
                                        onClick={() => setSize(sz)}
                                        className={`py-2 px-1 rounded-lg text-xs font-bold transition-all border ${size === sz
                                            ? 'bg-white text-black border-white'
                                            : 'bg-white/5 text-zinc-400 border-white/5 hover:bg-white/10'
                                            }`}
                                    >
                                        {sz === 'S' ? 'Small' : sz === 'M' ? 'Medium' : 'Large'}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Width</label>
                            <div className="grid grid-cols-2 gap-2">
                                {HOOK_WIDTH_OPTIONS.map((option) => (
                                    <button
                                        key={option.value}
                                        onClick={() => setWidthPreset(option.value)}
                                        className={`py-2 px-2 rounded-lg text-xs font-bold transition-all border ${widthPreset === option.value
                                            ? 'bg-white text-black border-white'
                                            : 'bg-white/5 text-zinc-400 border-white/5 hover:bg-white/10'
                                            }`}
                                    >
                                        {option.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Font</label>
                            <select
                                value={fontFamily}
                                onChange={(e) => setFontFamily(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-yellow-500/50"
                            >
                                {FONT_OPTIONS.map((option) => (
                                    <option key={option} value={option}>{option}</option>
                                ))}
                            </select>
                        </div>

                        <div>
                            <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3 block">Background</label>
                            <select
                                value={backgroundStyle}
                                onChange={(e) => setBackgroundStyle(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white focus:outline-none focus:border-yellow-500/50"
                            >
                                {BACKGROUND_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>{option.label}</option>
                                ))}
                            </select>
                        </div>

                        <div className="p-3 bg-white/5 rounded-lg border border-white/5 text-[11px] text-zinc-400">
                            <strong>Tip:</strong> Keep it short and punchy. Using "POV:" or specific questions works best for retention.
                        </div>
                    </div>

                    <button
                        onClick={() => onGenerate({ text, xPosition, yPosition, textAlign, size, widthPreset, fontFamily, backgroundStyle })}
                        disabled={isProcessing || !text.trim()}
                        className="w-full py-4 mt-4 bg-gradient-to-r from-yellow-500 to-amber-600 hover:from-yellow-400 hover:to-amber-500 text-black font-bold rounded-xl shadow-lg shadow-amber-500/20 transition-all active:scale-[0.98] flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                    >
                        {isProcessing ? <Loader2 size={20} className="animate-spin" /> : <Sparkles size={20} />}
                        {isProcessing ? 'Generating...' : 'Add Hook'}
                    </button>
                </div>
            </div>
        </div>
    );
}

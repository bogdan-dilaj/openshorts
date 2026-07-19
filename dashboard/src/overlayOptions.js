export const FONT_OPTIONS = [
  'Noto Sans',
  'Noto Serif',
  'Montserrat',
  'Anton',
  'Poppins',
  'Bebas Neue',
  'Archivo Black',
  'Barlow Condensed',
  'Merriweather',
];

export const BACKGROUND_OPTIONS = [
  { value: 'dark-box', label: 'Dunkle Box' },
  { value: 'light-box', label: 'Helle Box' },
  { value: 'yellow-box', label: 'Gelbe Box' },
  { value: 'transparent', label: 'Transparent' },
];

export const HOOK_WIDTH_OPTIONS = [
  { value: 'full', label: 'Volle Breite' },
  { value: 'wide', label: 'Breit' },
  { value: 'medium', label: 'Mittel' },
  { value: 'narrow', label: 'Schmal' },
];

export const PATTERN_FLASH_MODE_OPTIONS = [
  { value: 'none', label: 'Keine Flashes', description: 'Keine hellen Flash-Blitze rendern.' },
  { value: 'start', label: 'Nur am Anfang', description: 'Ein kurzer Flash beim Einstieg.' },
  { value: 'every_30s', label: 'Alle 30 Sekunden', description: 'Sehr selten, gut fuer lange ruhige 1-3-Minuten-Clips.' },
  { value: 'every_20s', label: 'Alle 20 Sekunden', description: 'Dezent, mit wenigen Pattern-Interrupts ueber laengere Clips.' },
  { value: 'every_10s', label: 'Alle 10 Sekunden', description: 'Selten, gut fuer ruhigere 1-3-Minuten-Clips.' },
  { value: 'every_8s', label: 'Alle 8 Sekunden', description: 'Ausgewogener Pattern-Interrupt.' },
  { value: 'every_5s', label: 'Alle 5 Sekunden', description: 'Sehr auffaellig, nur wenn der Stil aggressiver sein soll.' },
];

export const GRID_OPTIONS = [
  { value: 'top-left', label: 'Oben Links' },
  { value: 'top-center', label: 'Oben Mitte' },
  { value: 'top-right', label: 'Oben Rechts' },
  { value: 'center-left', label: 'Mitte Links' },
  { value: 'center', label: 'Mitte' },
  { value: 'center-right', label: 'Mitte Rechts' },
  { value: 'bottom-left', label: 'Unten Links' },
  { value: 'bottom-center', label: 'Unten Mitte' },
  { value: 'bottom-right', label: 'Unten Rechts' },
];

export const DEFAULT_SUBTITLE_STYLE = {
  fontFamily: 'Noto Sans',
  backgroundStyle: 'dark-box',
  fontSize: 24,
  position: 'bottom',
  yPosition: 86,
};

export const DEFAULT_HOOK_STYLE = {
  fontFamily: 'Noto Serif',
  backgroundStyle: 'light-box',
  size: 'M',
  position: 'top',
  horizontalPosition: 'center',
  xPosition: 50,
  yPosition: 12,
  textAlign: 'center',
  widthPreset: 'wide',
  startZoomFactor: 0,
  zoomFactor: 0.45,
  flashMode: 'every_30s',
};

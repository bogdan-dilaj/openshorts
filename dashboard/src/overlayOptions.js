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
};

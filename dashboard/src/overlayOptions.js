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
  { value: 'dark-box', label: 'Dark Box' },
  { value: 'light-box', label: 'Light Box' },
  { value: 'yellow-box', label: 'Yellow Box' },
  { value: 'transparent', label: 'Transparent' },
];

export const HOOK_WIDTH_OPTIONS = [
  { value: 'full', label: 'Full Width' },
  { value: 'wide', label: 'Wide' },
  { value: 'medium', label: 'Medium' },
  { value: 'narrow', label: 'Narrow' },
];

export const GRID_OPTIONS = [
  { value: 'top-left', label: 'Top Left' },
  { value: 'top-center', label: 'Top Center' },
  { value: 'top-right', label: 'Top Right' },
  { value: 'center-left', label: 'Center Left' },
  { value: 'center', label: 'Center' },
  { value: 'center-right', label: 'Center Right' },
  { value: 'bottom-left', label: 'Bottom Left' },
  { value: 'bottom-center', label: 'Bottom Center' },
  { value: 'bottom-right', label: 'Bottom Right' },
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
